from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from django.db.models import Case, When, Value, IntegerField, CharField
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError
from datetime import timedelta

from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.pagination import PageNumberPagination, LimitOffsetPagination
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
import re
import json

from .serializers import ProfileSerializer, file_to_abs_url
from .serializers import (
    UserSerializer,
    SimpleUserSerializer,
    NewCategorySerializer,
    CategoryPSerializer,
    UserSavedFilterSerializer,
    TaskSerializer,
    SharedTaskSerializer,
    SharedTaskDetailSerializer,
    NewPeticionCommentSerializer,
    FeedItemSerializer,
    SharedTaskCommentSerializer,
    FavoritoSerializer,
    PortadaSerializer,
    ImagenFijaSerializer,
    PosttSerializer
)
from . import models as ms
from .notifications import retire_notification, create_notification
from itertools import chain
from massaging.models import Message
from . import throttling as ts
from django.db.models import F

User = get_user_model()


def filter_by_categories(queryset, category_filter, field_name):
    categories = []
    seen = set()
    for raw_category in (category_filter or "").split(","):
        category = raw_category.strip()
        normalized = category.casefold()
        if category and normalized not in seen:
            categories.append(category)
            seen.add(normalized)

    for category in categories:
        if category.casefold() == "aprobada":
            pattern = r"(?:^|,)\s*aprobada?s?\s*(?:,|$)"
        else:
            pattern = rf"(?:^|,)\s*{re.escape(category)}\s*(?:,|$)"
        queryset = queryset.filter(**{f"{field_name}__iregex": pattern})
    return queryset


# ============================================================================
# CONFIGURACIÓN DE PAGINACIÓN
# ============================================================================

from rest_framework.exceptions import NotFound

class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        try:
            return super().paginate_queryset(queryset, request, view=view)
        except NotFound:
            # Gracefully handle the error by returning an empty list instead of throwing 404
            self.request = request
            return []

    def get_paginated_response(self, data):
        if not hasattr(self, 'page') or self.page is None:
            return Response({
                'count': 0,
                'next': None,
                'previous': None,
                'results': data
            })
        return super().get_paginated_response(data)

class CommentPagination(LimitOffsetPagination):
    default_limit = 10
    max_limit = 50


class StoriesPagination(LimitOffsetPagination):
    default_limit = 60
    max_limit = 100

# ============================================================================
# AUTENTICACIÓN Y USUARIOS
# ============================================================================

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = UserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            "user": UserSerializer(user, context={'request': request}).data,
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }, status=status.HTTP_201_CREATED)

class UserMeView(APIView):
    permission_classes = [IsAuthenticated]
    # ⚡ AÑADIMOS PARSERS PARA ACEPTAR IMÁGENES (multipart/form-data)
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        serializer = SimpleUserSerializer(request.user, context={'request': request})
        return Response(serializer.data)

    def patch(self, request, *args, **kwargs):
        """
        Permite a un usuario actualizar su propio perfil (nombre, apellido, imagen).
        """
        print("\n[DEBUG] --- Petición PATCH a /api/users/me/ ---")
        print(f"[DEBUG] Usuario: {request.user.email}")
        print(f"[DEBUG] Content-Type: {request.content_type}")
        print(f"[DEBUG] Datos recibidos (request.data): {request.data}")
        print(f"[DEBUG] Archivos recibidos (request.FILES): {request.FILES}")

        user = request.user
        
        image_file = request.FILES.get('user_image')
        if image_file:
            print(f"[DEBUG] Archivo de imagen encontrado: {image_file.name}")
        else:
            print("[DEBUG] No se encontró 'user_image' en request.FILES.")

        # La imagen se valida y guarda por separado para no volver a validar
        # el archivo después de que Django ya lo haya consumido.
        profile_data = request.data.copy()
        profile_data.pop('user_image', None)
        print(f"[DEBUG] Datos de usuario a pasar al serializador: {profile_data}")

        with transaction.atomic():
            serializer = UserSerializer(
                user,
                data=profile_data,
                partial=True,
                context={'request': request},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            if image_file:
                ms.ImagenFija.objects.create(user=user, image=image_file)
                print("[DEBUG] Objeto ImagenFija creado en la base de datos.")

        return Response(SimpleUserSerializer(user, context={'request': request}).data)

class UserMyTasksView(generics.ListAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        return ms.Task.objects.filter(user=self.request.user).select_related(
            "user"
        ).prefetch_related(
            "shared_instances__shared_by"
        ).order_by('-created_at')

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_users(request):
    users = User.objects.all().select_related("profile")
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response({
        "users": serializer.data,
        "is_admin": request.user.is_staff or request.user.is_superuser
    })

# ============================================================================
# TAREAS Y PETICIONES
# ============================================================================

class TaskListCreateView(generics.ListCreateAPIView):
    queryset = ms.Task.objects.all()
    serializer_class = TaskSerializer
    # ✅ FIX 401: Permitir que cualquiera vea la lista (GET),
    # pero solo usuarios autenticados puedan crear (POST).
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Count
        
        qs = super().get_queryset()
        pch = self.request.query_params.get("pch")
        user_id = self.request.query_params.get("user_id")
        date_filter = self.request.query_params.get("date_filter")
        category = self.request.query_params.get("category")
        status_filter = self.request.query_params.get("status")
        sort_by = self.request.query_params.get("sort_by")
        favorites_only = self.request.query_params.get("favorites_only")
        favorite_users_only = self.request.query_params.get("favorite_users_only")
        verified_users_only = self.request.query_params.get("verified_users_only")
        recommended_users_only = self.request.query_params.get("recommended_users_only")
        verified_users_only = self.request.query_params.get("verified_users_only")
        recommended_users_only = self.request.query_params.get("recommended_users_only")
        
        if pch:
            qs = qs.filter(pch=pch)
        if user_id and favorites_only not in ["true", "1", "True", True]:
            qs = qs.filter(user_id=user_id)
            
        if date_filter == "hoy":
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=1))
        elif date_filter == "esta_semana":
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=7))
        elif date_filter == "este_mes":
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=30))
            
        if category:
            qs = filter_by_categories(qs, category, "categories")

        if status_filter:
            qs = filter_by_categories(qs, status_filter, "categories")
            
        if favorites_only in ['true', '1', 'True', True]:
            if user_id:
                qs = qs.filter(favorited_by__user_id=user_id)
            else:
                qs = qs.filter(favorited_by__user=self.request.user)

        if favorite_users_only in ['true', '1', 'True', True]:
            qs = qs.filter(user__profile_favorites_received__user=self.request.user).distinct()
            
        if verified_users_only in ['true', '1', 'True', True]:
            qs = qs.filter(user__profile__is_verified=True)
            
        if recommended_users_only in ['true', '1', 'True', True]:
            qs = qs.filter(user__profile__is_recommended=True)
            
        qs = qs.select_related("user").prefetch_related(
            "likes", "post_comments", "subtasks", "subfuentes", "subfactores", "shared_instances__shared_by"
        )
        
        if sort_by == "likes":
            qs = qs.annotate(like_count=Count('likes')).order_by('-like_count', '-created_at')
        else:
            qs = qs.order_by('-created_at')
            
        return qs

    def list(self, request, *args, **kwargs):
        favorite_profile_ids = []
        if request.user.is_authenticated:
            favorite_profile_ids = list(
                ms.pFavorito.objects.filter(user=request.user).values_list("perfil_id", flat=True)
            )

        print("[TaskListCreateView] list auth debug", {
            "is_authenticated": bool(request.user and request.user.is_authenticated),
            "request_user_id": str(request.user.id) if request.user.is_authenticated else None,
            "request_user_username": getattr(request.user, "username", None) if request.user.is_authenticated else None,
            "favorite_profile_ids": [str(profile_id) for profile_id in favorite_profile_ids],
            "query_params": dict(request.query_params),
        })

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        payload = serializer.data

        preview = payload[:5] if isinstance(payload, list) else payload.get("results", [])[:5]
        print("[TaskListCreateView] list payload preview", [
            {
                "task_id": str(item.get("id")),
                "shared_by_list_count": len(item.get("shared_by_list") or []),
                "favorite_sharers_count": item.get("favorite_sharers_count"),
                "favorite_shared_by": item.get("favorite_shared_by"),
                "favorite_shared_by_list": item.get("favorite_shared_by_list"),
            }
            for item in preview
        ])

        if page is not None:
            return self.get_paginated_response(payload)
        return Response(payload)
    def post(self, request, *args, **kwargs):
        print("====== LLAVES RECIBIDAS DESDE REACT NATIVE ======")
        print(request.data.keys())
        print("=================================================")
        
        # 1. Extraemos los datos básicos y creamos la tarea PRINCIPAL
        data = request.data.dict() if hasattr(request.data, 'dict') else request.data
        data['user'] = request.user.id
        
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(user=request.user)

        # 2. PROCESAMIENTO DE ARRAYS (Usando el FOR seguro)
        
        # --- Procesar Subtasks ---
        for index in range(20):
            title = request.data.get(f'subtasks[{index}][title]')
            if title:
                ms.SubTask.objects.create(
                    parent_task=task,
                    title=title,
                    description=request.data.get(f'subtasks[{index}][description]', ''),
                    image=request.FILES.get(f'subtasks[{index}][image]'),
                    video=request.FILES.get(f'subtasks[{index}][video]'),
                    link=request.data.get(f'subtasks[{index}][link]', '')
                )

        # --- Procesar SubFuentes ---
        for index in range(20):
            title = request.data.get(f'subfuentes[{index}][title]')
            if title:
                ms.SubFuentes.objects.create(
                    parent_task=task,
                    title=title,
                    description=request.data.get(f'subfuentes[{index}][description]', ''),
                    image=request.FILES.get(f'subfuentes[{index}][image]'),
                    video=request.FILES.get(f'subfuentes[{index}][video]'),
                    link=request.data.get(f'subfuentes[{index}][link]', '')
                )

        # --- Procesar SubFactores ---
        for index in range(20):
            title = request.data.get(f'subfactores[{index}][title]')
            if title:
                ms.SubFactores.objects.create(
                    parent_task=task,
                    title=title,
                    description=request.data.get(f'subfactores[{index}][description]', ''),
                    image=request.FILES.get(f'subfactores[{index}][image]'),
                    video=request.FILES.get(f'subfactores[{index}][video]'),
                    link=request.data.get(f'subfactores[{index}][link]', '')
                )

        # 3. Devolvemos el objeto completo
        full_serializer = self.get_serializer(task)
        return Response(full_serializer.data, status=status.HTTP_201_CREATED)


class StoryListCreateView(generics.ListCreateAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = StoriesPagination

    def get_queryset(self):
        stories_window_start = timezone.now() - timedelta(hours=24)
        media_filter = (
            (Q(video__isnull=False) & ~Q(video=""))
            | (Q(image__isnull=False) & ~Q(image=""))
            | (Q(subtasks__video__isnull=False) & ~Q(subtasks__video=""))
            | (Q(subtasks__image__isnull=False) & ~Q(subtasks__image=""))
            | (Q(subfactores__video__isnull=False) & ~Q(subfactores__video=""))
            | (Q(subfactores__image__isnull=False) & ~Q(subfactores__image=""))
            | (Q(subfuentes__video__isnull=False) & ~Q(subfuentes__video=""))
            | (Q(subfuentes__image__isnull=False) & ~Q(subfuentes__image=""))
        )

        return (
            ms.Task.objects.filter(
                pch="historias",
                created_at__gte=stories_window_start,
            )
            .filter(media_filter)
            .annotate(views_count=Count("story_views", distinct=True))
            .select_related("user")
            .prefetch_related(
                "likes",
                "post_comments",
                "subtasks",
                "subfactores",
                "subfuentes",
                "shared_instances__shared_by",
            )
            .order_by("-created_at")
            .distinct()
        )

    def create(self, request, *args, **kwargs):
        # ⚡ FIX: QueryDict.copy() hace deepcopy y truena al clonar el archivo subido
        # (TypeError: cannot pickle 'BufferedRandom'). Usamos .dict() como en TaskListCreateView.
        incoming_data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
        caption_value = (incoming_data.get("caption") or "").strip()
        if hasattr(incoming_data, "pop"):
            incoming_data.pop("caption", None)
        incoming_data["pch"] = "historias"
        incoming_data["username"] = request.user.username or ""
        if not incoming_data.get("description"):
            incoming_data["description"] = caption_value
        if not incoming_data.get("title"):
            incoming_data["title"] = "Historia"

        serializer = self.get_serializer(data=incoming_data)
        serializer.is_valid(raise_exception=True)
        story = serializer.save(user=request.user)
        output = self.get_serializer(story)
        return Response(output.data, status=status.HTTP_201_CREATED)
    
    
    
class TaskDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ms.Task.objects.all()
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"

    def perform_update(self, serializer):
        if serializer.instance.user != self.request.user and not self.request.user.is_staff:
            raise PermissionDenied("No tienes permiso para editar esta tarea.")
        task = serializer.save()
        print("[TaskDetailView] task updated", {
            "task_id": str(task.id),
            "user_id": str(self.request.user.id),
            "fields": list(serializer.validated_data.keys()),
        })
        block_models = {
            "subtasks": ms.SubTask,
            "subfactores": ms.SubFactores,
            "subfuentes": ms.SubFuentes,
        }

        for field_name, block_model in block_models.items():
            has_json_blocks = field_name in self.request.data
            has_multipart_blocks = any(
                key.startswith(f"{field_name}[") for key in self.request.data.keys()
            )
            if not has_json_blocks and not has_multipart_blocks:
                continue

            if has_json_blocks:
                blocks = self.request.data.get(field_name) or []
                if isinstance(blocks, str):
                    try:
                        blocks = json.loads(blocks)
                    except (TypeError, ValueError):
                        raise ValidationError({field_name: "Formato de bloques inválido."})
            else:
                blocks = []
                for index in range(20):
                    prefix = f"{field_name}[{index}]"
                    block = {
                        "id": self.request.data.get(f"{prefix}[id]"),
                        "title": self.request.data.get(f"{prefix}[title]", ""),
                        "description": self.request.data.get(f"{prefix}[description]", ""),
                        "image_file": self.request.FILES.get(f"{prefix}[image]"),
                        "video_file": self.request.FILES.get(f"{prefix}[video]"),
                    }
                    if any((block["id"], block["title"], block["description"], block["image_file"], block["video_file"])):
                        blocks.append(block)

            kept_ids = set()
            for block_data in blocks:
                block_id = block_data.get("id")
                values = {
                    "title": (block_data.get("title") or "").strip(),
                    "description": block_data.get("description") or "",
                }
                image_file = block_data.get("image_file")
                video_file = block_data.get("video_file")
                if block_id:
                    block = get_object_or_404(block_model, id=block_id, parent_task=task)
                    for field, value in values.items():
                        setattr(block, field, value)
                    update_fields = list(values)
                    if image_file:
                        block.image = image_file
                        update_fields.append("image")
                    if video_file:
                        block.video = video_file
                        update_fields.append("video")
                    block.save(update_fields=update_fields)
                    kept_ids.add(block.id)
                elif values["title"] or values["description"]:
                    create_values = {**values}
                    if image_file:
                        create_values["image"] = image_file
                    if video_file:
                        create_values["video"] = video_file
                    block = block_model.objects.create(parent_task=task, **create_values)
                    kept_ids.add(block.id)

            block_model.objects.filter(parent_task=task).exclude(id__in=kept_ids).delete()
            print("[TaskDetailView] nested blocks synced", {
                "task_id": str(task.id),
                "field": field_name,
                "kept_ids": [str(block_id) for block_id in kept_ids],
            })

    def perform_destroy(self, instance):
        if instance.user != self.request.user and not self.request.user.is_staff:
            return Response({"error": "No autorizado"}, status=403)
        instance.delete()

# ============================================================================
# LIKES Y SOCIAL
# ============================================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_task_like(request, task_id):
    task = get_object_or_404(ms.Task, id=task_id)
    like, created = ms.Like.objects.get_or_create(user=request.user, task=task)
    if not created:
        like.delete()
        return Response({"liked": False, "likes_count": task.likes.count()})
    return Response({"liked": True, "likes_count": task.likes.count()}, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def record_story_view(request, story_id):
    story = get_object_or_404(ms.Task, id=story_id, pch="historias")
    created = False
    if story.user_id != request.user.id:
        _, created = ms.StoryView.objects.get_or_create(
            story=story,
            viewer=request.user,
        )

    return Response({
        "created": created,
        "views_count": story.story_views.count(),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def story_viewers(request, story_id):
    story = get_object_or_404(ms.Task, id=story_id, pch="historias")
    if story.user_id != request.user.id:
        return Response(
            {"detail": "No tienes permiso para ver las visualizaciones de esta historia."},
            status=status.HTTP_403_FORBIDDEN,
        )

    latest_viewer_image = ms.ImagenFija.objects.filter(
        user_id=OuterRef("viewer_id")
    ).order_by("-created_at").values("image")[:1]
    views = list(
        story.story_views.select_related("viewer", "viewer__profile")
        .annotate(activity_image=Subquery(latest_viewer_image))
        .order_by("-viewed_at")
    )

    latest_liker_image = ms.ImagenFija.objects.filter(
        user_id=OuterRef("user_id")
    ).order_by("-created_at").values("image")[:1]
    likes = list(
        story.likes.select_related("user", "user__profile")
        .annotate(activity_image=Subquery(latest_liker_image))
        .order_by("-created_at")
    )

    users_by_id = {}

    def activity_user(user, image_value):
        user_id = str(user.id)
        if user_id not in users_by_id:
            full_name = " ".join(
                part for part in (user.first_name, user.last_name) if part
            )
            image = file_to_abs_url(image_value, request)
            users_by_id[user_id] = {
                "id": user_id,
                "username": user.username,
                "name": full_name or user.username or user.email,
                "image": image,
                "user_image": image,
                "profile": ProfileSerializer(user.profile).data,
                "viewed": False,
                "liked": False,
                "viewed_at": None,
                "liked_at": None,
                "_activity_at": None,
            }
        return users_by_id[user_id]

    for story_view in views:
        viewer = story_view.viewer
        item = activity_user(viewer, story_view.activity_image)
        item["viewed"] = True
        item["viewed_at"] = story_view.viewed_at
        item["_activity_at"] = story_view.viewed_at

    for like in likes:
        item = activity_user(like.user, like.activity_image)
        item["liked"] = True
        item["liked_at"] = like.created_at
        if item["_activity_at"] is None or like.created_at > item["_activity_at"]:
            item["_activity_at"] = like.created_at

    users = sorted(
        users_by_id.values(),
        key=lambda item: (item["_activity_at"], item["id"]),
        reverse=True,
    )
    for item in users:
        item.pop("_activity_at")

    return Response({
        "views_count": len(views),
        "likes_count": len(likes),
        "count": len(users),
        "users": users,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_comment_like(request, comment_id):
    comment = get_object_or_404(ms.NewPeticionCommentPost, id=comment_id)
    like, created = ms.LikeCommentPost.objects.get_or_create(user=request.user, comment=comment)
    
    # ⚡ Sincronizar: Likear también los posibles clones en las tareas compartidas
    shared_clones = ms.SharedTaskComment.objects.filter(
        shared_task__task=comment.post, created_by=comment.created_by, text=comment.text
    )
    
    if not created:
        like.delete()
        for sc in shared_clones:
            ms.LikeSharedTaskComment.objects.filter(user=request.user, comment=sc).delete()
        return Response({"liked": False, "likes_count": comment.likes.count()})
        
    for sc in shared_clones:
        ms.LikeSharedTaskComment.objects.get_or_create(user=request.user, comment=sc)
        
    return Response({"liked": True, "likes_count": comment.likes.count()}, status=201)

class TaskCommentListCreateView(generics.ListCreateAPIView):
    serializer_class = NewPeticionCommentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommentPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser] # ⚡ Soportar tanto JSON como FormData

    def get_queryset(self):
        task_id = self.kwargs.get("task_id")
        # 🛡️ FIX 500: Usamos "replies" porque así se llama el related_name en models.py
        return ms.NewPeticionCommentPost.objects.filter(
            post_id=task_id, parent__isnull=True
        ).select_related("created_by__profile").prefetch_related("replies", "likes")

    def perform_create(self, serializer):
        task_id = self.kwargs.get("task_id")
        original_comment = serializer.save(created_by=self.request.user, post_id=task_id)

        # ⚡ SINCRONIZAR BIDIRECCIONAL: Replicar respuesta en la tarea compartida si el padre es un clon
        if original_comment.parent:
            shared_clones = ms.SharedTaskComment.objects.filter(
                shared_task__task_id=task_id,
                created_by=original_comment.parent.created_by,
                text=original_comment.parent.text
            )
            for sc in shared_clones:
                ms.SharedTaskComment.objects.create(
                    shared_task=sc.shared_task,
                    created_by=self.request.user,
                    text=original_comment.text,
                    parent=sc
                )


class NewPeticionCommentDetailsView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ms.NewPeticionCommentPost.objects.all()
    serializer_class = NewPeticionCommentSerializer
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "comment_id" # Django buscará el <int:comment_id> de la URL
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def perform_destroy(self, instance):
        # 🛡️ SEGURIDAD: Solo el creador del comentario (o un admin) puede borrarlo
        if instance.created_by != self.request.user and not self.request.user.is_staff:
            raise PermissionDenied("No tienes permiso para eliminar este comentario.")
            
        # ⚡ Sincronizar: borrar clones en tareas compartidas si borran de la original
        ms.SharedTaskComment.objects.filter(
            shared_task__task=instance.post,
            created_by=instance.created_by,
            text=instance.text
        ).delete()
        
        instance.delete()
        

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def like_unlike_profile(request, profile_id):
    """
    Da o quita like a un perfil.
    Devuelve el estado final del like y el nuevo contador total.
    """
    # ✅ FIX 500: El ID puede ser de User o de Profile. Buscamos el User directamente.
    try:
        target_user = get_object_or_404(User, Q(id=profile_id) | Q(profile__id=profile_id))
    except (ValueError, User.DoesNotExist):
        return Response({"error": "User or Profile not found"}, status=status.HTTP_404_NOT_FOUND)

    # El modelo LikeP.profile apunta a un User, así que usamos target_user.
    like, created = ms.LikeP.objects.get_or_create(user=request.user, profile=target_user)


    if not created:
        like.delete()
        liked = False
    else:
        liked = True

    # Devolvemos el estado final y el nuevo contador
    likes_count = target_user.likes_received.count()
    return Response({'liked': liked, 'likes_count': likes_count}, status=status.HTTP_200_OK)

# ============================================================================
# REPOST (IMPULSO)
# ============================================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def repost_task(request, task_id):
    """
    Activa o desactiva un 'repost' de una tarea por parte de un usuario.
    Esto solo afecta la puntuación de interacción de la tarea original para el feed,
    sin crear un objeto SharedTask. Funciona como un interruptor (toggle).
    """
    try:
        # Usamos select_for_update para bloquear la fila y evitar race conditions
        task = ms.Task.objects.select_for_update().get(id=task_id)

        # Usamos el modelo 'Like' como si fuera 'Repost' para registrar la acción.
        repost_instance, created = ms.Like.objects.get_or_create(user=request.user, task=task)

        if not created:
            # El usuario ya había reposteado, así que revertimos la acción.
            repost_instance.delete()
            task.interaction_score = F('interaction_score') - 1
            reposted = False
        else:
            # Es la primera vez que repostea, aumentamos la popularidad.
            task.interaction_score = F('interaction_score') + 1
            reposted = True
            retire_notification(dedupe_key=f"api.like:{repost_instance.pk}")

        task.save(update_fields=['interaction_score'])
        # Usamos refresh_from_db para obtener el valor actualizado del score
        task.refresh_from_db(fields=['interaction_score'])

        return Response({"reposted": reposted, "interaction_score": task.interaction_score}, status=status.HTTP_200_OK)

    except ms.Task.DoesNotExist:
        return Response({"error": "Task not found"}, status=status.HTTP_404_NOT_FOUND)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def share_task_to_story(request):
    source_task_id = request.data.get("task_id")
    caption = (request.data.get("caption") or "").strip()
    source_item_type = (request.data.get("source_item_type") or request.data.get("source_type") or "").strip()
    source_item_id = request.data.get("source_item_id") or request.data.get("source_id")

    if not source_task_id:
        return Response({"error": "task_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    source_task = get_object_or_404(ms.Task, id=source_task_id)

    source_item = None
    if source_item_type and source_item_id:
        related_name = source_item_type.rstrip("s") if source_item_type.endswith("s") else source_item_type
        normalized_type = {
            "subtask": "subtasks",
            "subtasks": "subtasks",
            "subfactor": "subfactores",
            "subfactores": "subfactores",
            "subfuente": "subfuentes",
            "subfuentes": "subfuentes",
        }.get(str(source_item_type).lower(), str(source_item_type).lower())
        related_manager = {
            "subtasks": source_task.subtasks,
            "subfactores": source_task.subfactores,
            "subfuentes": source_task.subfuentes,
        }.get(normalized_type)
        if related_manager is not None:
            source_item = related_manager.filter(id=source_item_id).first()

    if not source_item:
        for related_name in ["subtasks", "subfactores", "subfuentes"]:
            manager = getattr(source_task, related_name, None)
            if manager is None:
                continue
            candidates = manager.all().order_by("created_at")
            chosen = next((item for item in candidates if item.image or item.video), None)
            if chosen:
                source_item = chosen
                source_item_type = related_name
                break

    story_media = source_item if source_item and (source_item.image or source_item.video) else None
    story_image = story_media.image if story_media and story_media.image else source_task.image
    story_video = story_media.video if story_media and story_media.video else source_task.video

    if not story_image and not story_video:
        return Response(
            {"error": "Solo se puede compartir a historia una tarea o subtarea con imagen o video."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    story_title = source_task.title or (source_item.title if source_item else "Historia compartida")
    story_description = caption if caption else ((source_item.description if source_item and source_item.description else source_task.description) or "")

    story = ms.Task.objects.create(
        user=request.user,
        username=(source_task.user.username if source_task.user else request.user.username) or request.user.username or "",
        title=story_title,
        description=story_description,
        pch="historias",
        categories=source_task.categories or "",
        image=story_image,
        video=story_video,
        story_is_shared=True,
        story_source_task=source_task,
    )

    serializer = TaskSerializer(story, context={"request": request})
    response_data = serializer.data
    response_data['source_task_id'] = str(source_task.id)
    response_data['source_task_title'] = source_task.title or ""
    response_data['source_task_user'] = source_task.user.username if source_task.user else ""
    response_data['source_task_user_id'] = str(source_task.user_id) if source_task.user_id else None
    response_data['source_task_description'] = source_task.description or ""
    response_data['source_task_image'] = file_to_abs_url(source_task.image, request) if source_task.image else None
    response_data['source_task_video'] = file_to_abs_url(source_task.video, request) if source_task.video else None
    response_data['source_item_type'] = source_item_type or None
    response_data['source_item_id'] = str(source_item.id) if source_item else None
    response_data['source_item_title'] = source_item.title if source_item else ""
    response_data['source_item_description'] = source_item.description if source_item else ""
    response_data['source_item_image'] = file_to_abs_url(source_item.image, request) if source_item and source_item.image else None
    response_data['source_item_video'] = file_to_abs_url(source_item.video, request) if source_item and source_item.video else None
    return Response(response_data, status=status.HTTP_201_CREATED)

# ============================================================================
# FUNCIONES DE COMPATIBILIDAD URLS
# ============================================================================

@api_view(["GET"])
@permission_classes([AllowAny])
def users_who_liked_task(request, task_id):
    """ 
    Obtiene la lista de usuarios a los que les gustó una tarea.
    Esta es la versión optimizada y correcta.
    """
    users_qs = User.objects.filter(task_likes__task_id=task_id).distinct()
    # Subconsulta para obtener la imagen de perfil más reciente
    latest_img = ms.ImagenFija.objects.filter(user=OuterRef("pk")).order_by("-id").values("image")[:1]

    # Subconsulta para verificar si el usuario dio like a esta tarea
    # likes_exists = ms.Like.objects.filter(task_id=task_id, user_id=OuterRef("pk")) # No se usa actualmente

    # Obtenemos los usuarios que dieron like a esta tarea específica
    users_qs = users_qs.annotate(user_image=Subquery(latest_img)).distinct()

    # Construimos la respuesta manualmente para que coincida con lo que el modal espera
    out = []
    for u in users_qs:
        try:
            p = u.profile
        except Exception:
            p = None

        out.append({
            "id": u.id,
            "username": u.username,
            # ✅ FIX DEFINITIVO: El modelo LikeP.profile ahora apunta a User.
            # Usamos el related_name `likes_received` para contar eficientemente.
            # Esto soluciona el error fatal que tumbaba el servidor.
            "likes_count": u.likes_received.count(),
            "user_image": file_to_abs_url(getattr(u, "user_image", None), request),
            "profile": ProfileSerializer(p).data if p else None
        })

    return Response(out, status=status.HTTP_200_OK)

@api_view(["GET"])
@permission_classes([AllowAny])
def users_who_liked_comment(request, comment_id):
    likes = ms.LikeCommentPost.objects.filter(comment_id=comment_id).select_related("user__profile")
    users = [like.user for like in likes if like.user]
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response(serializer.data)

@api_view(["GET"])
@permission_classes([AllowAny])
def users_who_liked_shared_task(request, shared_task_id):
    likes = ms.LikeSharedTask.objects.filter(shared_task_id=shared_task_id).select_related("user__profile")
    users = [like.user for like in likes if like.user]
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response(serializer.data)

@api_view(["GET"])
@permission_classes([AllowAny])
def users_who_liked_shared_comment(request, comment_id):
    likes = ms.LikeSharedTaskComment.objects.filter(comment_id=comment_id).select_related("user__profile")
    users = [like.user for like in likes if like.user]
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response(serializer.data)

@api_view(["GET"])
@permission_classes([AllowAny])
def users_who_shared_task(request, task_id):
    shares = ms.SharedTask.objects.filter(task_id=task_id).select_related("shared_by__profile")
    users = [share.shared_by for share in shares if share.shared_by]
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response(serializer.data)

class SharedTaskListCreateView(generics.ListCreateAPIView):
    """Lista tareas compartidas y permite crear nuevas compartidas."""
    queryset = ms.SharedTask.objects.all()
    serializer_class = SharedTaskSerializer
    # ✅ FIX 401: Permitir que cualquiera vea la lista (GET),
    # pero solo usuarios autenticados puedan compartir (POST).
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination

    def get_queryset(self):
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Count
        
        qs = super().get_queryset()
        date_filter = self.request.query_params.get("date_filter")
        category = self.request.query_params.get("category")
        status_filter = self.request.query_params.get("status")
        sort_by = self.request.query_params.get("sort_by")
        favorites_only = self.request.query_params.get("favorites_only")
        favorite_users_only = self.request.query_params.get("favorite_users_only")
        verified_users_only = self.request.query_params.get("verified_users_only")
        recommended_users_only = self.request.query_params.get("recommended_users_only")
        
        if date_filter == "hoy":
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=1))
        elif date_filter == "esta_semana":
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=7))
        elif date_filter == "este_mes":
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=30))
            
        if category:
            qs = filter_by_categories(qs, category, "task__categories")
        if status_filter:
            qs = filter_by_categories(qs, status_filter, "task__categories")
            
        if favorites_only in ['true', '1', 'True', True]:
            qs = qs.filter(task__favorited_by__user=self.request.user)

        if favorite_users_only in ['true', '1', 'True', True]:
            qs = qs.filter(Q(shared_by__profile_favorites_received__user=self.request.user) | Q(task__user__profile_favorites_received__user=self.request.user)).distinct()

        if verified_users_only in ['true', '1', 'True', True]:
            qs = qs.filter(shared_by__profile__is_verified=True) | qs.filter(task__user__profile__is_verified=True)

        if recommended_users_only in ['true', '1', 'True', True]:
            qs = qs.filter(shared_by__profile__is_recommended=True) | qs.filter(task__user__profile__is_recommended=True)
            
        qs = qs.select_related("task", "shared_by").prefetch_related("likes", "comments")
        
        if sort_by == "likes":
            qs = qs.annotate(like_count=Count('likes')).order_by('-like_count', '-created_at')
        else:
            qs = qs.order_by('-created_at')
            
        return qs

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        task_id = request.data.get("task_id")
        if not task_id:
            return Response({"error": "task_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        print(f"\n[BACKEND LOG] --- Iniciando 'create' en SharedTaskListCreateView para task_id: {task_id} ---")

        # Bloqueamos la tarea para actualizarla de forma segura
        task = get_object_or_404(ms.Task.objects.select_for_update(), id=task_id)
        print(f"[BACKEND LOG] Tarea encontrada. Valores ANTES de actualizar: share_count={task.share_count}, interaction_score={task.interaction_score}")

        shared, created = ms.SharedTask.objects.get_or_create(
            task=task,
            shared_by=request.user,
            defaults={"description": request.data.get("description", "")},
        )
        print(f"[BACKEND LOG] SharedTask 'created': {created}")

        # ✅ FIX LÓGICA DE CONTADORES:
        # 1. El share_count SIEMPRE se incrementa.
        # 2. El interaction_score solo se incrementa si el usuario NUNCA ha interactuado
        #    (ni con un 'share' ni con un 'repost', que se registran en el modelo Like).
        has_interacted_before = ms.Like.objects.filter(user=request.user, task=task).exists()

        update_fields = {'share_count': F('share_count') + 1}
        if not has_interacted_before:
            print("[BACKEND LOG] Primera interacción del usuario. Incrementando interaction_score.")
            update_fields['interaction_score'] = F('interaction_score') + 1
            # Registramos la interacción en el modelo Like para que no vuelva a contar.
            interaction, interaction_created = ms.Like.objects.get_or_create(
                user=request.user,
                task=task,
            )
            if interaction_created:
                # Like también se usa aquí como marcador interno, no como un like real.
                retire_notification(dedupe_key=f"api.like:{interaction.pk}")
        
        ms.Task.objects.filter(pk=task.pk).update(**update_fields)

        # Recargamos la tarea desde la DB para obtener los contadores actualizados.
        task.refresh_from_db()
        print(f"[BACKEND LOG] Tarea recargada desde DB. Valores DESPUÉS de actualizar: share_count={task.share_count}, interaction_score={task.interaction_score}")

        if created:
            status_code = status.HTTP_201_CREATED
        else:
            # Si ya existía, solo actualizamos la descripción.
            shared.description = request.data.get("description", shared.description)
            shared.save(update_fields=['description'])
            status_code = status.HTTP_200_OK

        serializer = self.get_serializer(shared)
        print("[BACKEND LOG] Serializando y enviando respuesta al frontend...")
        print(f"[BACKEND LOG] --- Fin del proceso para task_id: {task_id} ---\n")
        return Response(serializer.data, status=status_code)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agregar_favorito(request):
    task = get_object_or_404(ms.Task, id=request.data.get("task_id"))
    fav, created = ms.Favorito.objects.get_or_create(user=request.user, task=task)
    if not created:
        fav.delete()
        return Response({"mensaje": "Removed"}, status=204)
    return Response({"mensaje": "Added"}, status=201)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def listar_favoritos(request, user_id=None):
    user = get_object_or_404(User, id=user_id) if user_id else request.user
    favoritos = ms.Favorito.objects.filter(user=user).values_list('task_id', flat=True)
    return Response(list(favoritos))

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agregar_pfavorito(request):
    # En la base viva, `api_pfavorito.perfil_id` apunta a `api_user.id`, no a `api_profile.id`.
    perfil = get_object_or_404(User, id=request.data.get("perfil_id"))
    fav, created = ms.pFavorito.objects.get_or_create(user=request.user, perfil=perfil)
    if not created:
        fav.delete()
        return Response({"mensaje": "Removed"}, status=204)
    return Response({"mensaje": "Added"}, status=201)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def listar_pfavoritos(request, user_id=None):
    user = get_object_or_404(User, id=user_id) if user_id else request.user
    favoritos = ms.pFavorito.objects.filter(user=user).select_related("perfil__profile")
    perfiles = [f.perfil for f in favoritos]
    serializer = SimpleUserSerializer(perfiles, many=True, context={"request": request})
    return Response(serializer.data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_likes(request, profile_id):
    """
    Lista todos los usuarios que han dado like a un perfil específico.
    Incluye un campo 'viewer_has_liked' para el usuario que hace la petición.
    """
    try:
        # Buscamos el perfil a través del ID de usuario (UUID) o el ID de perfil (numérico)
        profile = get_object_or_404(ms.Profile, Q(user_id=profile_id) | Q(id=profile_id))
    except (ValueError, ms.Profile.DoesNotExist):
        return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)

    # ✅ FIX 500: La relación `likes_received` está en el modelo User, no en Profile.
    # El campo `profile` en el modelo `LikeP` apunta a un `User`.
    # Por lo tanto, para obtener los usuarios que dieron "like", filtramos
    # los `LikeP` donde el `profile` (que es un User) es `profile.user`.
    likes = ms.LikeP.objects.filter(profile=profile.user).select_related('user')
    users = [like.user for like in likes]
    serializer = SimpleUserSerializer(users, many=True, context={'request': request})

    viewer_has_liked = False
    if request.user.is_authenticated:
        # Usamos `profile.user` para que coincida con el modelo LikeP.
        viewer_has_liked = ms.LikeP.objects.filter(user=request.user, profile=profile.user).exists()

    return Response({ 'results': serializer.data, 'viewer_has_liked': viewer_has_liked })

@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def create_categoryp(request, pk=None):
    if request.method == "GET":
        cats = ms.CategoryP.objects.filter(user=request.user)
        return Response(CategoryPSerializer(cats, many=True).data)
    elif request.method == "POST":
        serializer = CategoryPSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == "DELETE":
        cat = get_object_or_404(ms.CategoryP, pk=pk, user=request.user)
        cat.delete()
        return Response(status=204)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def reorder_categoryp(request):
    """Persiste el nuevo orden del filtro personal del usuario (arrastrar y soltar,
    igual que hacen los admins con las categorías globales del filtro)."""
    order = request.data.get("order")
    if not isinstance(order, list) or not order:
        return Response({"order": "Debes enviar una lista de ids en el nuevo orden."}, status=400)

    owned_ids = set(str(pk) for pk in ms.CategoryP.objects.filter(user=request.user).values_list("id", flat=True))
    for position, cat_id in enumerate(order):
        if str(cat_id) not in owned_ids:
            continue
        ms.CategoryP.objects.filter(pk=cat_id, user=request.user).update(position=position)

    cats = ms.CategoryP.objects.filter(user=request.user)
    return Response(CategoryPSerializer(cats, many=True).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def list_categoryp_for_user(request, user_id):
    """Lectura pública del filtro personal de OTRO usuario, para mostrarlo
    junto al propio cuando se está viendo su perfil (como en la versión anterior)."""
    cats = ms.CategoryP.objects.filter(user_id=user_id)
    return Response(CategoryPSerializer(cats, many=True).data)


# ============================================================================
# FILTROS GUARDADOS POR PERFIL (CRUD propio, un solo campo JSON)
# ============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def saved_filters_list_create(request):
    """Lista o crea los filtros guardados del perfil autenticado.
    No toca el feed de tareas: se consulta aparte, sin renderizar tareas."""
    if request.method == "GET":
        filters_qs = ms.UserSavedFilter.objects.filter(user=request.user)
        return Response(UserSavedFilterSerializer(filters_qs, many=True).data)

    serializer = UserSavedFilterSerializer(data=request.data, context={"request": request})
    if serializer.is_valid():
        try:
            serializer.save()
        except IntegrityError:
            return Response(
                {"name": "Ya tienes un filtro guardado con ese nombre."}, status=400
            )
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)


@api_view(["PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def saved_filter_detail(request, pk):
    saved_filter = get_object_or_404(ms.UserSavedFilter, pk=pk, user=request.user)

    if request.method == "DELETE":
        saved_filter.delete()
        return Response(status=204)

    partial = request.method == "PATCH"
    serializer = UserSavedFilterSerializer(
        saved_filter, data=request.data, partial=partial, context={"request": request}
    )
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=400)

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticatedOrReadOnly])
def new_category_list_create(request):
    if request.method == "GET":
        pch = (request.query_params.get("pch") or "").strip()
        qs = ms.NewCategory.objects.all()
        if pch:
            # Globales (pch vacío) + las del tema solicitado
            qs = qs.filter(Q(pch="") | Q(pch__iexact=pch))
        include_approval = request.query_params.get("include_approval") in ["true", "1", "True"]
        if not include_approval and not request.user.is_staff and not request.user.is_superuser:
            qs = qs.exclude(name__iexact=ms.APPROVED_TAG)
        serializer = NewCategorySerializer(qs, many=True)
        return Response(serializer.data)
    if not request.user.is_staff: return Response(status=403)
    serializer = NewCategorySerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)

@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def new_category_detail(request, pk):
    cat = get_object_or_404(ms.NewCategory, pk=pk)
    if request.method == "GET": return Response(NewCategorySerializer(cat).data)
    if not request.user.is_staff: return Response(status=403)
    if request.method == "PUT":
        serializer = NewCategorySerializer(cat, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)
    cat.delete()
    return Response(status=204)

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def imagen_fija_list_create(request):
    if request.method == "GET":
        imagen = ms.ImagenFija.objects.filter(user=request.user).last()
        if not imagen: return Response(status=404)
        return Response(ImagenFijaSerializer(imagen).data)
    serializer = ImagenFijaSerializer(data=request.data, context={"request": request})
    if serializer.is_valid():
        serializer.save(user=request.user)
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def obtener_portadas_usuario(request, user_id):
    portadas = ms.Portada.objects.filter(user_id=user_id)
    return Response(PortadaSerializer(portadas, many=True, context={'request': request}).data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def obtener_imagen_fija_usuario(request, user_id):
    imagen = ms.ImagenFija.objects.filter(user_id=user_id).last()
    if not imagen: return Response(status=404)
    return Response(ImagenFijaSerializer(imagen).data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_user_details(request):
    # ✅ DEBUG: Imprime los datos del usuario en la terminal del backend
    print(f"[DEBUG] get_user_details para: {request.user.username}, is_staff: {request.user.is_staff}, is_superuser: {request.user.is_superuser}")
    # 1. Obtenemos los datos base del serializador
    user_data = UserSerializer(request.user, context={'request': request}).data
    # 2. Añadimos los campos de admin
    user_data['is_staff'] = request.user.is_staff
    user_data['is_superuser'] = request.user.is_superuser
    
    print(f"[DEBUG] Enviando user_data: {user_data}")
    return Response(user_data) # 3. Enviamos la respuesta completa

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_current_user_profile(request):
    return Response(UserSerializer(request.user, context={'request': request}).data)

class PortadaListCreateView(generics.ListCreateAPIView):
    serializer_class = PortadaSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self): return ms.Portada.objects.filter(user=self.request.user)
    def perform_create(self, serializer): serializer.save(user=self.request.user)

@api_view(["PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def portada_update_delete(request, portada_id):
    portada = get_object_or_404(ms.Portada, id=portada_id, user=request.user)
    if request.method == "DELETE":
        portada.delete()
        return Response(status=204)
    serializer = PortadaSerializer(portada, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=400)


class FeedItem:
    """
    Clase proxy para unificar Task y SharedTask en un solo tipo de objeto para el feed.
    Esto simplifica la serialización y el ordenamiento.
    """
    def __init__(self, item, priority, is_original):
        self.item = item
        self.priority = priority
        self.is_original = is_original
        self.created_at = item.created_at

class FeedView(generics.ListAPIView):
    """
    Vista unificada que combina Tasks y SharedTasks en un solo feed,
    ordenado por prioridad de usuario y luego por fecha.
    """
    # ✅ FIX: No usamos un serializer_class único, ya que manejamos dos tipos de objetos.
    # La serialización se hará manualmente en get_queryset.
    serializer_class = FeedItemSerializer
    permission_classes = [IsAuthenticatedOrReadOnly] # Cualquiera puede ver el feed
    pagination_class = StandardPagination

    def get_queryset(self):
        # ✅ LÓGICA DE FILTRO: Leemos el parámetro 'sort_by' para decidir qué feed mostrar.
        # El frontend enviará 'all' para el feed unificado.
        sort_by = self.request.query_params.get("sort_by")

        # Prioridad: admin > recomendado > verificado > regular
        # 1. Definir las prioridades para el ordenamiento
        user_priority = Case(
            When(Q(user__is_staff=True) | Q(user__is_superuser=True), then=Value(4)),
            When(user__profile__is_recommended=True, then=Value(3)),
            When(user__profile__is_verified=True, then=Value(2)),
            default=Value(1),
            output_field=IntegerField(),
        )
        shared_by_priority = Case(
            When(Q(shared_by__is_staff=True) | Q(shared_by__is_superuser=True), then=Value(4)),
            When(shared_by__profile__is_recommended=True, then=Value(3)),
            When(shared_by__profile__is_verified=True, then=Value(2)),
            default=Value(1),
            output_field=IntegerField(),
        )

        # ✅ COMPORTAMIENTO POR DEFECTO: Mostrar solo tareas originales.
        if sort_by != 'all':
            tasks = ms.Task.objects.annotate(
                priority=user_priority
            ).select_related('user__profile').prefetch_related('likes', 'post_comments', 'subtasks', 'subfactores', 'subfuentes')

        # ✅ COMPORTAMIENTO PARA "all": Mostrar el feed unificado.
        else:
            tasks = ms.Task.objects.annotate(priority=user_priority).select_related('user__profile')
            shared_tasks = ms.SharedTask.objects.annotate(priority=shared_by_priority).select_related('shared_by__profile', 'task__user__profile')

            task_items = [
                FeedItem(item=task, priority=task.priority, is_original=True)
                for task in tasks
            ]
            shared_task_items = [
                FeedItem(item=shared_task, priority=shared_task.priority, is_original=False)
                for shared_task in shared_tasks
            ]

            combined_list_unord = task_items + shared_task_items
            combined_list = sorted(
                combined_list_unord,
                key=lambda x: (x.priority, x.created_at),
                reverse=True
            )
            return combined_list
            
        # Aplicar ordenamiento de likes si se solicita
        if sort_by == 'likes':
            tasks = tasks.annotate(like_count=Count('likes')).order_by('-like_count', '-created_at')
        else: # Orden por defecto (más recientes)
            tasks = tasks.order_by('-priority', '-created_at')

        # ✅ FIX: Devolvemos el queryset de Task directamente, el serializador se encargará del resto.
        return tasks

        


    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        # ✅ FIX: Si el queryset es de Tasks, usamos TaskSerializer.
        # Si es una lista de FeedItem, usamos FeedItemSerializer.
        if isinstance(queryset, list) and queryset and isinstance(queryset[0], FeedItem):
             serializer = self.get_serializer(page, many=True)
        elif page:
             # Si es un queryset de Task, usamos el serializador de Task.
             serializer = TaskSerializer(page, many=True, context={'request': request})
        else:
            serializer = self.get_serializer(page, many=True)

        return self.get_paginated_response(serializer.data)


# ============================================================================
# ACCIONES ADMIN
# ============================================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_verify_user(request, user_id):
    if not request.user.is_superuser: return Response(status=403)
    user = get_object_or_404(User, id=user_id)
    user.profile.is_verified = bool(request.data.get("is_verified", True))
    user.profile.save()
    return Response({"is_verified": user.profile.is_verified})

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_recommend_user(request, user_id):
    if not request.user.is_superuser: return Response(status=403)
    user = get_object_or_404(User, id=user_id)
    user.profile.is_recommended = bool(request.data.get("is_recommended", True))
    user.profile.save()
    return Response({"is_recommended": user.profile.is_recommended})

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def verify_admin(request):
    return Response({
        "is_staff": request.user.is_staff,
        "is_admin": request.user.is_staff or request.user.is_superuser,
    })

# ============================================================================
# ACCIONES ADMIN ADICIONALES (FIX PARA URLS)
# ============================================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_app_like_task(request, task_id):
    """Admin: dar like a una tarea con la cuenta bot de la app"""
    if not request.user.is_superuser:
        return Response({"detail": "Forbidden"}, status=403)
    
    task = get_object_or_404(ms.Task, id=task_id)
    # Aquí podrías definir un usuario bot específico, por ahora usamos el actual
    like, created = ms.Like.objects.get_or_create(user=request.user, task=task)
    
    return Response({
        "task_id": task.id,
        "liked": True,
        "likes_count": task.likes.count()
    })

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_app_like_profile(request, profile_id):
    """Admin: dar like a un perfil con la cuenta bot de la app"""
    if not request.user.is_superuser:
        return Response({"detail": "Forbidden"}, status=403)
    
    profile_user = get_object_or_404(User, id=profile_id)
    ms.LikeP.objects.get_or_create(user=request.user, profile=profile_user)
    
    return Response({
        "profile_id": profile_user.id,
        "liked": True,
        "likes_count": profile_user.likes_received.count()
    })

# ============================================================================
# ETIQUETADO DE PERSONAS EN PUBLICACIONES
# ============================================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sync_task_tags(request, task_id):
    """Sincroniza las personas etiquetadas en una tarea. Solo el autor (o staff)."""
    task = get_object_or_404(ms.Task, id=task_id)
    if task.user_id != request.user.id and not request.user.is_staff:
        return Response({"detail": "Solo el autor puede editar las etiquetas."}, status=403)

    user_ids = request.data.get("user_ids", [])
    if not isinstance(user_ids, list):
        return Response({"detail": "user_ids debe ser una lista."}, status=400)

    # El autor no tiene sentido etiquetándose a sí mismo
    desired_ids = {str(uid) for uid in user_ids if str(uid) != str(request.user.id)}
    users_map = {str(u.id): u for u in User.objects.filter(id__in=desired_ids)}

    existing_tags = {str(tag.user_id): tag for tag in task.tagged_users.all()}

    # Altas (la señal post_save dispara la notificación al etiquetado)
    for uid in desired_ids - set(existing_tags):
        user = users_map.get(uid)
        if user:
            ms.TaskTag.objects.get_or_create(
                task=task, user=user, defaults={"tagged_by": request.user}
            )

    # Bajas
    removed = set(existing_tags) - desired_ids
    if removed:
        task.tagged_users.filter(user_id__in=removed).delete()

    tagged = [
        {
            "id": str(tag.user.id),
            "username": getattr(tag.user, "username", None),
            "first_name": getattr(tag.user, "first_name", "") or "",
            "last_name": getattr(tag.user, "last_name", "") or "",
        }
        for tag in task.tagged_users.select_related("user").all()
    ]
    return Response({"task_id": str(task.id), "tagged_users": tagged})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_task_approval(request, task_id):
    """Solo staff: aprueba una propuesta de podcast y notifica a sus involucrados."""
    if not (request.user.is_staff or request.user.is_superuser):
        return Response({"detail": "Solo administradores."}, status=403)

    task = get_object_or_404(ms.Task, id=task_id)
    approve = bool(request.data.get("approve", True))

    cats = [c.strip() for c in (task.categories or "").split(",") if c.strip()]
    is_podcast = any(ms.PODCAST_CATEGORY.casefold() == category.casefold() for category in cats)
    if not is_podcast:
        return Response(
            {"detail": "Solo se pueden aprobar tareas con la categoría Grabar Podcast."},
            status=400,
        )
    has_tag = ms.APPROVED_TAG in [c.lower() for c in cats]

    if approve and not has_tag:
        cats = [c for c in cats if c.casefold() != "procesando"]
        cats.append(ms.APPROVED_TAG)
    elif not approve and has_tag:
        cats = [c for c in cats if c.lower() != ms.APPROVED_TAG]

    task.categories = ", ".join(cats)
    task.save(update_fields=["categories"])

    is_podcast = ms.PODCAST_CATEGORY.lower() in (task.categories or "").lower()
    kind = "podcast" if is_podcast else "tarea"

    if approve:
        actor_name = request.user.username or request.user.email
        recipients = [task.user] + [
            tag.user for tag in task.tagged_users.select_related("user").all()
        ]
        seen = set()
        for recipient in recipients:
            if not recipient or recipient.id == request.user.id or recipient.id in seen:
                continue
            seen.add(recipient.id)
            if is_podcast:
                text = "🎉 ¡Felicidades! El podcast donde fuiste etiquetado fue aprobado. ¡A grabar se ha dicho! 🎙️"
                ntype = "podcast_approved"
            else:
                text = f"✅ Tu aportación fue aprobada por {actor_name}"
                ntype = "task_approved"
            create_notification(
                recipient=recipient,
                actor=request.user,
                notification_type=ntype,
                target_type="task",
                target_id=task.id,
                data={"text": text, "task_title": task.title[:80]},
                dedupe_key=f"approved:{kind}:{task.id}",
            )
        for tag in task.tagged_users.select_related("user").all():
            invitation, _ = ms.PodcastInvitation.objects.get_or_create(
                task=task,
                user=tag.user,
                defaults={"status": ms.PodcastInvitation.STATUS_PENDING},
            )
            if invitation.status == ms.PodcastInvitation.STATUS_PENDING:
                Message.objects.filter(
                    sender=request.user,
                    receiver=tag.user,
                    content__startswith=f"🎙️ Invitación a podcast aprobada | tarea:{task.id}",
                ).first() or Message.objects.create(
                    sender=request.user,
                    receiver=tag.user,
                    content=(
                        f"↪ Publicación compartida: {task.title} [task:{task.id}]\n"
                        "🎙️ Invitación a podcast aprobada.\n"
                        "Fuiste invitado a participar. Abre la tarea para aceptar o rechazar la invitación."
                    ),
                )
    else:
        # Al quitar la aprobación, retiramos la felicitación
        retire_notification(dedupe_key=f"approved:{kind}:{task.id}")

    return Response({
        "task_id": str(task.id),
        "approved": approve,
        "categories": task.categories,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def respond_podcast_invitation(request, task_id):
    task = get_object_or_404(ms.Task, id=task_id)
    invitation = get_object_or_404(
        ms.PodcastInvitation,
        task=task,
        user=request.user,
    )
    if invitation.status != ms.PodcastInvitation.STATUS_PENDING:
        return Response({"status": invitation.status, "detail": "La invitación ya fue respondida."}, status=400)

    accepted = bool(request.data.get("accepted", True))
    invitation.status = (
        ms.PodcastInvitation.STATUS_ACCEPTED
        if accepted else ms.PodcastInvitation.STATUS_DECLINED
    )
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at", "updated_at"])

    actor_name = request.user.username or request.user.email
    status_text = "aceptó" if accepted else "rechazó"
    admins = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True)).exclude(id=request.user.id)
    for admin in admins:
        create_notification(
            recipient=admin,
            actor=request.user,
            notification_type="podcast_invitation_response",
            target_type="task",
            target_id=task.id,
            data={"text": f"{actor_name} {status_text} la invitación al podcast.", "task_title": task.title[:80]},
            dedupe_key=f"podcast-response:{task.id}:{request.user.id}",
        )

    admin_recipient = User.objects.filter(email__iexact="owen@hotmail.com").first()
    if admin_recipient and admin_recipient.id != request.user.id:
        Message.objects.create(
            sender=request.user,
            receiver=admin_recipient,
            content=(
                f"↪ Publicación compartida: {task.title} [task:{task.id}]\n"
                f"🎙️ Invitación al podcast {status_text}.\n"
                f"El usuario {actor_name} respondió {status_text} la invitación."
            ),
        )

    return Response({"task_id": str(task.id), "status": invitation.status})


# ============================================================================
# FORO (Posts)
# ============================================================================

class PostListCreateView(generics.ListCreateAPIView):
    queryset = ms.Postt.objects.filter(parent__isnull=True)
    serializer_class = PosttSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_queryset(self):
        return ms.Postt.objects.filter(parent__isnull=True).select_related("user").prefetch_related("likes", "forum_replies").order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PostDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ms.Postt.objects.all()
    serializer_class = PosttSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        return super().get_queryset().select_related("user").prefetch_related("likes", "forum_replies")

    def perform_destroy(self, instance):
        if instance.user != self.request.user and not self.request.user.is_staff:
            raise PermissionDenied("No autorizado para eliminar este post.")
        instance.delete()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_post_like(request, post_id):
    post = get_object_or_404(ms.Postt, id=post_id)
    like, created = ms.LikePostt.objects.get_or_create(user=request.user, post=post)
    if not created:
        like.delete()
        return Response({"liked": False, "likes_count": post.likes.count()})
    return Response({"liked": True, "likes_count": post.likes.count()}, status=201)


# ============================================================================
# COMENTARIOS Y LIKES PARA TAREAS COMPARTIDAS
# ============================================================================

class SharedTaskDetailView(generics.RetrieveAPIView):
    """Obtiene el detalle de una tarea compartida con comentarios"""
class SharedTaskDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Obtiene, actualiza o elimina una tarea compartida."""
    queryset = ms.SharedTask.objects.all()
    serializer_class = SharedTaskDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        return super().get_queryset().select_related("task", "shared_by").prefetch_related("comments", "likes")

    def perform_destroy(self, instance):
        if instance.shared_by != self.request.user and not self.request.user.is_staff:
            raise PermissionDenied("No tienes permiso para eliminar esta publicación compartida.")
        instance.delete()

    def perform_update(self, serializer):
        if serializer.instance.shared_by != self.request.user and not self.request.user.is_staff:
            raise PermissionDenied("No tienes permiso para editar esta publicación compartida.")
        serializer.save()


class SharedTaskCommentListCreateView(generics.ListCreateAPIView):
    """Lista comentarios padre de una tarea compartida y permite crear nuevos"""
    serializer_class = SharedTaskCommentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommentPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        shared_task_id = self.kwargs.get("shared_task_id")
        return ms.SharedTaskComment.objects.filter(
            shared_task_id=shared_task_id, parent__isnull=True
        ).select_related("created_by__profile").prefetch_related("replies", "likes")

    def perform_create(self, serializer):
        shared_task_id = self.kwargs.get("shared_task_id")
        
        # 1. Guardar el comentario en la Tarea Compartida
        shared_comment = serializer.save(created_by=self.request.user, shared_task_id=shared_task_id)
        
        # 2. ⚡ SINCRONIZAR ("Como la función de likes"): Replicarlo en la tarea original
        shared_task = get_object_or_404(ms.SharedTask, id=shared_task_id)
        
        # ⚡ Respetar el ANIDADO buscando a su equivalente padre
        original_parent = None
        if shared_comment.parent:
            original_parent = ms.NewPeticionCommentPost.objects.filter(
                post=shared_task.task,
                created_by=shared_comment.parent.created_by,
                text=shared_comment.parent.text
            ).first()
            
        ms.NewPeticionCommentPost.objects.create(
            post=shared_task.task,
            created_by=self.request.user,
            text=shared_comment.text,
            parent=original_parent
        )


class SharedTaskCommentDetailsView(generics.RetrieveUpdateDestroyAPIView):
    """Obtiene, actualiza o elimina un comentario específico de tarea compartida"""
    queryset = ms.SharedTaskComment.objects.all()
    serializer_class = SharedTaskCommentSerializer
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "comment_id"
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def perform_destroy(self, instance):
        if instance.created_by != self.request.user and not self.request.user.is_staff:
            raise PermissionDenied("No tienes permiso para eliminar este comentario.")
            
        # ⚡ Borrar también el clon en la tarea original si el usuario decide eliminar su comentario
        ms.NewPeticionCommentPost.objects.filter(
            post=instance.shared_task.task,
            created_by=instance.created_by,
            text=instance.text
        ).delete()
            
        instance.delete()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_shared_task_like(request, shared_task_id):
    """Da o quita like a una tarea compartida y sincroniza el like con la tarea original."""
    shared_task = get_object_or_404(ms.SharedTask, id=shared_task_id)

    like_shared, created_shared = ms.LikeSharedTask.objects.get_or_create(
        user=request.user,
        shared_task=shared_task,
    )

    if not created_shared:
        like_shared.delete()
        ms.Like.objects.filter(user=request.user, task=shared_task.task).delete()
        liked = False
    else:
        ms.Like.objects.get_or_create(user=request.user, task=shared_task.task)
        liked = True

    return Response({
        "liked": liked,
        "likes_count_shared": shared_task.likes.count(),
        "likes_count_original": shared_task.task.likes.count(),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_shared_task_comment_like(request, shared_task_id, comment_id):
    """Da o quita like a un comentario de tarea compartida"""
    comment = get_object_or_404(ms.SharedTaskComment, id=comment_id, shared_task_id=shared_task_id)
    
    like, created = ms.LikeSharedTaskComment.objects.get_or_create(
        user=request.user, comment=comment
    )
    
    # ⚡ Sincronizar: Likear el clon original
    original_clone = ms.NewPeticionCommentPost.objects.filter(
        post=comment.shared_task.task, created_by=comment.created_by, text=comment.text
    ).first()
    
    if not created:
        like.delete()
        if original_clone:
            ms.LikeCommentPost.objects.filter(user=request.user, comment=original_clone).delete()
        return Response({
            "liked": False,
            "likes_count": comment.likes.count()
        })
        
    if original_clone:
        ms.LikeCommentPost.objects.get_or_create(user=request.user, comment=original_clone)
    
    return Response({
        "liked": True,
        "likes_count": comment.likes.count()
    }, status=201)