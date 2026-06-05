from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.conf import settings
from rest_framework.exceptions import PermissionDenied

from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.pagination import PageNumberPagination, LimitOffsetPagination
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import (
    UserSerializer,
    SimpleUserSerializer,
    NewCategorySerializer,
    CategoryPSerializer,
    TaskSerializer,
    SharedTaskSerializer,
    SharedTaskDetailSerializer,
    NewPeticionCommentSerializer,
    SharedTaskCommentSerializer,
    FavoritoSerializer,
    PortadaSerializer,
    ImagenFijaSerializer,
    PosttSerializer,
)
from . import models as ms
from . import throttling as ts

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
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        from django.utils import timezone
        from datetime import timedelta
        
        qs = super().get_queryset()
        pch = self.request.query_params.get("pch")
        user_id = self.request.query_params.get("user_id")
        date_filter = self.request.query_params.get("date_filter")
        category = self.request.query_params.get("category")
        
        if pch:
            qs = qs.filter(pch=pch)
        if user_id:
            qs = qs.filter(user_id=user_id)
            
        if date_filter == "hoy":
            qs = qs.filter(created_at__date=timezone.now().date())
        elif date_filter == "esta_semana":
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=7))
        elif date_filter == "este_mes":
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=30))
            
        if category:
            qs = qs.filter(categories__icontains=category)
            
        return qs.select_related("user").prefetch_related(
            "likes", "comments", "subtasks", "subfuentes", "subfactores"
        ).order_by('-created_at')
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
    profile_user = get_object_or_404(User, id=profile_id)
    like, created = ms.LikeP.objects.get_or_create(user=request.user, profile=profile_user)
    if not created:
        like.delete()
        return Response({"status": "removed"})
    return Response({"status": "added", "likes_count": ms.LikeP.objects.filter(profile=profile_user).count()})

# ============================================================================
# FUNCIONES DE COMPATIBILIDAD URLS
# ============================================================================

@api_view(["GET"])
@permission_classes([AllowAny])
def users_who_liked_task(request, task_id):
    likes = ms.Like.objects.filter(task_id=task_id).select_related("user__profile")
    users = [like.user for like in likes if like.user]
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response(serializer.data)

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
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("task", "shared_by")
            .prefetch_related("likes", "comments")
        )

    def create(self, request, *args, **kwargs):
        task = get_object_or_404(ms.Task, id=request.data.get("task_id"))
        shared, created = ms.SharedTask.objects.get_or_create(
            task=task,
            shared_by=request.user,
            defaults={"description": request.data.get("description", "")},
        )
        if not created:
            return Response({"detail": "Ya compartido"}, status=400)

        task.share_count += 1
        task.save()

        serializer = self.get_serializer(shared)
        return Response(serializer.data, status=201)


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
    likes = ms.LikeP.objects.filter(profile_id=profile_id).select_related("user__profile")
    users = [l.user for l in likes]
    return Response(SimpleUserSerializer(users, many=True, context={'request': request}).data)

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
@permission_classes([IsAuthenticated])
def new_category_list_create(request):
    if request.method == "GET":
        return Response(NewCategorySerializer(ms.NewCategory.objects.all(), many=True).data)
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
        "likes_count": ms.LikeP.objects.filter(profile=profile_user).count()
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