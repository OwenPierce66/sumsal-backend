from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.db.models import Case, When, Value, IntegerField, CharField
from django.conf import settings
from rest_framework.exceptions import PermissionDenied

from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.pagination import PageNumberPagination, LimitOffsetPagination
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import ProfileSerializer, file_to_abs_url
from .serializers import (
    UserSerializer,
    SimpleUserSerializer,
    NewCategorySerializer,
    CategoryPSerializer,
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
from itertools import chain
from . import throttling as ts
from django.db.models import F

User = get_user_model()

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
    def get(self, request):
        serializer = UserSerializer(request.user, context={'request': request})
        return Response(serializer.data)

class UserMyTasksView(generics.ListAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        return ms.Task.objects.filter(user=self.request.user).order_by('-created_at')

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_users(request):
    users = User.objects.all().select_related("profile")
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response(serializer.data)

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
            qs = qs.filter(categories__icontains=category)
            
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
            "likes", "post_comments", "subtasks", "subfuentes", "subfactores"
        )
        
        if sort_by == "likes":
            qs = qs.annotate(like_count=Count('likes')).order_by('-like_count', '-created_at')
        else:
            qs = qs.order_by('-created_at')
            
        return qs
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
    
    
    
class TaskDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ms.Task.objects.all()
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"

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
    Registra un 'reposteo' de una tarea, incrementando su contador de compartidos
    y su puntuación de interacción para mejorar su visibilidad en el feed.
    """
    try:
        # Usamos select_for_update para bloquear la fila y evitar race conditions
        task = ms.Task.objects.select_for_update().get(id=task_id)
        
        # Actualización atómica: incrementa ambos contadores en una sola operación de BD.
        task.share_count = F('share_count') + 1
        task.interaction_score = F('interaction_score') + 3 # Damos 3 puntos por repostear
        
        task.save(update_fields=['share_count', 'interaction_score'])
        
        task.refresh_from_db()

        return Response({ "status": "success", "share_count": task.share_count }, status=status.HTTP_200_OK)

    except ms.Task.DoesNotExist:
        return Response({"error": "Task not found"}, status=status.HTTP_404_NOT_FOUND)

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
    # ✅ FIX: Ahora que Task.id es un UUID, la consulta es directa y sin conversiones.
    # Esto soluciona el error 500.
    users_qs = User.objects.filter(task_likes__task_id=task_id)

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
            qs = qs.filter(task__categories__icontains=category)
            
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

        # Bloqueamos la tarea para actualizarla de forma segura
        task = get_object_or_404(ms.Task.objects.select_for_update(), id=task_id)

        shared, created = ms.SharedTask.objects.get_or_create(
            task=task,
            shared_by=request.user,
            defaults={"description": request.data.get("description", "")},
        )

        if created:
            # Si es la primera vez que comparte, incrementamos contadores.
            task.share_count = F('share_count') + 1
            task.interaction_score = F('interaction_score') + 1  # 1 punto por compartir
            task.save(update_fields=['share_count', 'interaction_score'])
            status_code = status.HTTP_201_CREATED
        else:
            # Si ya existía, actualizamos la descripción.
            shared.description = request.data.get("description", shared.description)
            shared.save(update_fields=['description'])
            status_code = status.HTTP_200_OK

        serializer = self.get_serializer(shared)
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

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticatedOrReadOnly])
def new_category_list_create(request):
    if request.method == "GET":
        serializer = NewCategorySerializer(ms.NewCategory.objects.all(), many=True)
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
    return Response(UserSerializer(request.user, context={'request': request}).data)

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

        # 1. Obtener TAREAS ORIGINALES con todas sus relaciones precargadas
        tasks = ms.Task.objects.annotate(
            priority=user_priority
        ).select_related('user__profile').prefetch_related('likes', 'post_comments', 'subtasks', 'subfactores', 'subfuentes')

        # 2. Obtener TAREAS COMPARTIDAS con todas sus relaciones precargadas
        shared_tasks = ms.SharedTask.objects.annotate(
            priority=shared_by_priority
        ).select_related(
            'shared_by__profile', 'task__user__profile'
        ).prefetch_related(
            'likes', 'comments', 'task__post_comments', 'task__subtasks', 
            'task__subfactores', 'task__subfuentes', 'task__likes'
        )

        # ✅ LÓGICA DE FAVORITOS: Anotar cuántos de los que compartieron son favoritos del viewer
        if self.request.user.is_authenticated:
            favorite_sharers_subquery = ms.SharedTask.objects.filter(
                task_id=OuterRef('task_id'),
                shared_by__profile_favorites_received__user=self.request.user
            ).values('task_id').annotate(count=Count('id')).values('count')
            
            shared_tasks = shared_tasks.annotate(
                favorite_sharers_count=Subquery(favorite_sharers_subquery, output_field=IntegerField())
            )

        # 3. Normalizar Tasks para que tengan una estructura similar a SharedTask
        # Esto evita errores en el serializador.
        normalized_tasks = []
        for task in tasks:
            normalized_tasks.append(FeedItem(item=task, priority=task.priority, is_original=True))

        # 4. Combinar y ordenar en Python
        combined_list = sorted(
            normalized_tasks,
            key=lambda x: (x.priority, x.created_at),
            reverse=True
        )
        return combined_list

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        # ✅ FIX: Serializar la página de resultados, no el queryset completo.
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
class SharedTaskDetailView(generics.RetrieveDestroyAPIView):
    """Obtiene el detalle de una tarea compartida con comentarios o la elimina"""
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