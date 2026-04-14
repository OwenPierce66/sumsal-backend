from django.contrib.auth import get_user_model
from django.db.models import OuterRef, Subquery, Exists, Count
from django.shortcuts import get_object_or_404
from django.conf import settings

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
    NewPeticionCommentSerializer,
    FavoritoSerializer,
    PortadaSerializer,
    ImagenFijaSerializer,
    PosttSerializer,
    file_to_abs_url,
)
from . import models as ms
from . import throttling as ts

User = get_user_model()


# ============================================================================
# AUTENTICACIÓN (Existente + Mejorado)
# ============================================================================

class UserMeView(APIView):
    """Get current user data"""
    permission_classes = [IsAuthenticated]
    throttle_classes = [ts.UserMeThrottle, ts.VaultThrottle]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class RegisterView(generics.CreateAPIView):
    """Register new user"""
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = UserSerializer
    throttle_classes = [ts.RegisterAnonThrottle, ts.RegisterUserThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "user": UserSerializer(user).data,
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            status=status.HTTP_201_CREATED,
        )


# ============================================================================
# PAGINACIÓN
# ============================================================================

class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


class CommentPagination(LimitOffsetPagination):
    default_limit = 10
    max_limit = 50


# ============================================================================
# TASKS / PETICIONES
# ============================================================================

class TaskListCreateView(generics.ListCreateAPIView):
    """List and create tasks"""
    queryset = ms.Task.objects.all()
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = super().get_queryset()
        pch = self.request.query_params.get("pch")
        if pch:
            qs = qs.filter(pch=pch)
        return qs.select_related("user__profile").prefetch_related(
            "likes", "comments", "shared_tasks"
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class TaskDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, delete task"""
    queryset = ms.Task.objects.all()
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    lookup_field = "id"

    def get_queryset(self):
        return ms.Task.objects.select_related("user__profile").prefetch_related(
            "likes", "comments", "shared_tasks"
        )

    def perform_destroy(self, instance):
        if instance.user_id != self.request.user.id and not self.request.user.is_superuser:
            raise PermissionError("No autorizado")
        instance.delete()


# ============================================================================
# LIKES EN TAREAS
# ============================================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_task_like(request, task_id):
    """Toggle like on task"""
    task = get_object_or_404(ms.Task, id=task_id)
    like = ms.Like.objects.filter(user=request.user, task=task).first()

    if like:
        like.delete()
        return Response(
            {"liked": False, "likes_count": task.likes.count()},
            status=status.HTTP_200_OK,
        )
    else:
        ms.Like.objects.create(user=request.user, task=task)
        return Response(
            {"liked": True, "likes_count": task.likes.count()},
            status=status.HTTP_201_CREATED,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def users_who_liked_task(request, task_id):
    """List users who liked a task"""
    get_object_or_404(ms.Task.objects.only("id"), id=task_id)

    likes = ms.Like.objects.filter(task_id=task_id).select_related("user__profile")
    users = [like.user for like in likes if like.user]
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# COMENTARIOS EN TAREAS
# ============================================================================

class TaskCommentListCreateView(generics.ListCreateAPIView):
    """List and create comments on task"""
    serializer_class = NewPeticionCommentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CommentPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        task_id = self.kwargs.get("task_id")
        get_object_or_404(ms.Task, id=task_id)
        return ms.NewPeticionCommentPost.objects.filter(
            post_id=task_id, parent__isnull=True
        ).select_related("created_by__profile").prefetch_related("children", "likes")

    def perform_create(self, serializer):
        task_id = self.kwargs.get("task_id")
        serializer.save(created_by=self.request.user, post_id=task_id)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_comment_like(request, comment_id):
    """Toggle like on comment"""
    comment = get_object_or_404(ms.NewPeticionCommentPost, id=comment_id)
    like = comment.likes.filter(user=request.user).first()

    if like:
        like.delete()
        return Response(
            {"liked": False, "likes_count": comment.likes.count()},
            status=status.HTTP_200_OK,
        )
    else:
        ms.LikeCommentPost.objects.create(user=request.user, comment=comment)
        return Response(
            {"liked": True, "likes_count": comment.likes.count()},
            status=status.HTTP_201_CREATED,
        )


# ============================================================================
# COMPARTIR TAREAS
# ============================================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_shared_task(request):
    """Share a task"""
    task_id = request.data.get("task_id")
    if not task_id:
        return Response(
            {"error": "task_id required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task = get_object_or_404(ms.Task, id=task_id)

    shared_task, created = ms.SharedTask.objects.get_or_create(
        task=task,
        shared_by=request.user,
        defaults={"description": request.data.get("description", "")},
    )

    if not created:
        return Response(
            {"detail": "Already shared"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task.share_count = (task.share_count or 0) + 1
    task.save(update_fields=["share_count"])

    task.refresh_from_db()
    return Response(
        TaskSerializer(task, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_shared_task(request, shared_task_id):
    """Remove share"""
    shared_task = get_object_or_404(ms.SharedTask, id=shared_task_id)
    if shared_task.shared_by_id != request.user.id and not request.user.is_superuser:
        return Response(
            {"error": "Forbidden"},
            status=status.HTTP_403_FORBIDDEN,
        )

    task = shared_task.task
    shared_task.delete()

    task.share_count = max((task.share_count or 0) - 1, 0)
    task.save(update_fields=["share_count"])

    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([AllowAny])
def users_who_shared_task(request, task_id):
    """List users who shared a task"""
    get_object_or_404(ms.Task.objects.only("id"), id=task_id)

    shares = ms.SharedTask.objects.filter(task_id=task_id).select_related(
        "shared_by__profile"
    )
    users = [share.shared_by for share in shares if share.shared_by]
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# FAVORITOS DE TAREAS
# ============================================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agregar_favorito(request):
    """Add/remove task favorite"""
    task_id = request.data.get("task_id")
    if not task_id:
        return Response(
            {"error": "task_id required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task = get_object_or_404(ms.Task, id=task_id)
    favorito = ms.Favorito.objects.filter(user=request.user, task=task).first()

    if favorito:
        favorito.delete()
        return Response(
            {"mensaje": "Removed"},
            status=status.HTTP_204_NO_CONTENT,
        )
    else:
        ms.Favorito.objects.create(user=request.user, task=task)
        return Response(
            {"mensaje": "Added"},
            status=status.HTTP_201_CREATED,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def listar_favoritos(request, user_id=None):
    """List favorites"""
    if user_id:
        user = get_object_or_404(User, id=user_id)
    else:
        user = request.user

    favoritos = ms.Favorito.objects.filter(user=user).select_related(
        "task__user__profile"
    )
    data = [fav.task_id for fav in favoritos]
    return Response(data, status=status.HTTP_200_OK)


# ============================================================================
# FAVORITOS DE PERFILES
# ============================================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agregar_pfavorito(request):
    """Add/remove profile favorite"""
    perfil_id = request.data.get("perfil_id")
    if not perfil_id:
        return Response(
            {"error": "perfil_id required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    perfil = get_object_or_404(User, id=perfil_id)
    pfavorito = ms.pFavorito.objects.filter(user=request.user, perfil=perfil).first()

    if pfavorito:
        pfavorito.delete()
        return Response(
            {"mensaje": "Removed"},
            status=status.HTTP_204_NO_CONTENT,
        )
    else:
        ms.pFavorito.objects.create(user=request.user, perfil=perfil)
        return Response(
            {"mensaje": "Added"},
            status=status.HTTP_201_CREATED,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def listar_pfavoritos(request, user_id=None):
    """List profile favorites"""
    if user_id:
        user = get_object_or_404(User, id=user_id)
    else:
        user = request.user

    pfavoritos = ms.pFavorito.objects.filter(user=user).select_related(
        "perfil__profile"
    )
    perfiles = [pf.perfil for pf in pfavoritos]
    serializer = SimpleUserSerializer(
        perfiles, many=True, context={"request": request}
    )
    return Response(serializer.data)


# ============================================================================
# LIKES EN PERFILES
# ============================================================================

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def like_unlike_profile(request, profile_id):
    """Toggle like on profile"""
    profile_user = get_object_or_404(User, id=profile_id)
    like = ms.LikeP.objects.filter(user=request.user, profile=profile_user).first()

    if like:
        like.delete()
        return Response(
            {
                "status": "removed",
                "likes_count": ms.LikeP.objects.filter(profile=profile_user).count(),
            }
        )
    else:
        ms.LikeP.objects.create(user=request.user, profile=profile_user)
        return Response(
            {
                "status": "added",
                "likes_count": ms.LikeP.objects.filter(profile=profile_user).count(),
            }
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_likes(request, profile_id):
    """List profile likes"""
    get_object_or_404(User, id=profile_id)

    likes = ms.LikeP.objects.filter(profile_id=profile_id).select_related(
        "user__profile"
    )
    users = [like.user for like in likes]
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response(serializer.data)


# ============================================================================
# CATEGORÍAS
# ============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def new_category_list_create(request):
    """List/create global categories"""
    if request.method == "GET":
        categories = ms.NewCategory.objects.all()
        serializer = NewCategorySerializer(categories, many=True)
        return Response(serializer.data)

    elif request.method == "POST":
        if not request.user.is_staff:
            return Response(
                {"detail": "Forbidden"},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = NewCategorySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "DELETE", "PUT"])
@permission_classes([IsAuthenticated])
def new_category_detail(request, pk):
    """Category detail/edit/delete"""
    category = get_object_or_404(ms.NewCategory, pk=pk)

    if request.method == "GET":
        serializer = NewCategorySerializer(category)
        return Response(serializer.data)

    if not request.user.is_staff:
        return Response(
            {"detail": "Forbidden"},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == "PUT":
        serializer = NewCategorySerializer(category, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == "DELETE":
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def create_categoryp(request, pk=None):
    """User personal categories"""
    if request.method == "GET":
        categories = ms.CategoryP.objects.filter(user=request.user)
        serializer = CategoryPSerializer(categories, many=True)
        return Response(serializer.data)

    elif request.method == "POST":
        serializer = CategoryPSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == "DELETE" and pk:
        category = get_object_or_404(ms.CategoryP, pk=pk, user=request.user)
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================================
# IMÁGENES DE PERFIL
# ============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def imagen_fija_list_create(request):
    """Manage fixed image"""
    if request.method == "GET":
        imagen = ms.ImagenFija.objects.filter(user=request.user).last()
        if imagen:
            serializer = ImagenFijaSerializer(imagen)
            return Response(serializer.data)
        return Response(
            {"detail": "No image"},
            status=status.HTTP_404_NOT_FOUND,
        )

    elif request.method == "POST":
        serializer = ImagenFijaSerializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def obtener_imagen_fija_usuario(request, user_id):
    """Get user fixed image"""
    imagen = ms.ImagenFija.objects.filter(user__id=user_id).last()
    if imagen:
        serializer = ImagenFijaSerializer(imagen)
        return Response(serializer.data)
    return Response(
        {"detail": "Not found"},
        status=status.HTTP_404_NOT_FOUND,
    )


# ============================================================================
# PORTADAS
# ============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def portada_list_create(request):
    """Manage portadas"""
    if request.method == "GET":
        portadas = ms.Portada.objects.filter(user=request.user)
        serializer = PortadaSerializer(portadas, many=True)
        return Response(serializer.data)

    elif request.method == "POST":
        serializer = PortadaSerializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["PUT", "DELETE"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def portada_update_delete(request, portada_id):
    """Update/delete portada"""
    portada = get_object_or_404(ms.Portada, pk=portada_id, user=request.user)

    if request.method == "PUT":
        serializer = PortadaSerializer(portada, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == "DELETE":
        portada.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def obtener_portadas_usuario(request, user_id):
    """Get user portadas"""
    portadas = ms.Portada.objects.filter(user__id=user_id)
    serializer = PortadaSerializer(portadas, many=True)
    return Response(serializer.data)


# ============================================================================
# USUARIOS
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_users(request):
    """List all users"""
    users = User.objects.all().select_related("profile")
    serializer = SimpleUserSerializer(users, many=True, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_user_details(request):
    """Get current user details"""
    serializer = UserSerializer(request.user)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_current_user_profile(request):
    """Get current user profile"""
    serializer = UserSerializer(request.user)
    return Response(serializer.data)


# ============================================================================
# ADMIN ACTIONS
# ============================================================================

def _get_app_user():
    """Get app bot user"""
    app_id = getattr(settings, "APP_USER_ID", 1)
    return get_object_or_404(User, id=app_id)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_verify_user(request, user_id):
    """Admin: verify user"""
    if not request.user.is_superuser:
        return Response(
            {"detail": "Forbidden"},
            status=status.HTTP_403_FORBIDDEN,
        )

    user = get_object_or_404(User, id=user_id)
    is_verified = bool(request.data.get("is_verified", True))
    user.profile.is_verified = is_verified
    user.profile.save(update_fields=["is_verified"])

    return Response(
        {"user_id": user.id, "is_verified": user.profile.is_verified},
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_recommend_user(request, user_id):
    """Admin: recommend user"""
    if not request.user.is_superuser:
        return Response(
            {"detail": "Forbidden"},
            status=status.HTTP_403_FORBIDDEN,
        )

    user = get_object_or_404(User, id=user_id)
    is_recommended = bool(request.data.get("is_recommended", True))
    user.profile.is_recommended = is_recommended
    user.profile.save(update_fields=["is_recommended"])

    return Response(
        {"user_id": user.id, "is_recommended": user.profile.is_recommended},
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_app_like_task(request, task_id):
    """Admin: like task with app account"""
    if not request.user.is_superuser:
        return Response(
            {"detail": "Forbidden"},
            status=status.HTTP_403_FORBIDDEN,
        )

    task = get_object_or_404(ms.Task, id=task_id)
    app_user = _get_app_user()

    liked = bool(request.data.get("liked", True))

    qs = ms.Like.objects.filter(user=app_user, task=task)

    if liked:
        if not qs.exists():
            ms.Like.objects.create(user=app_user, task=task)
        else:
            keep = qs.first()
            qs.exclude(id=keep.id).delete()
    else:
        qs.delete()

    return Response(
        {
            "task_id": task.id,
            "app_user_id": app_user.id,
            "liked": liked,
            "likes_count": task.likes.count(),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_app_like_profile(request, profile_id):
    """Admin: like profile with app account"""
    if not request.user.is_superuser:
        return Response(
            {"detail": "Forbidden"},
            status=status.HTTP_403_FORBIDDEN,
        )

    profile_user = get_object_or_404(User, id=profile_id)
    app_user = _get_app_user()

    liked = bool(request.data.get("liked", True))

    if liked:
        ms.LikeP.objects.get_or_create(user=app_user, profile=profile_user)
    else:
        ms.LikeP.objects.filter(user=app_user, profile=profile_user).delete()

    return Response(
        {
            "profile_id": profile_user.id,
            "app_user_id": app_user.id,
            "liked": liked,
            "likes_count": ms.LikeP.objects.filter(profile=profile_user).count(),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def verify_admin(request):
    """Check if user is admin"""
    return Response(
        {
            "is_staff": request.user.is_staff,
            "is_superuser": request.user.is_superuser,
            "is_admin": bool(request.user.is_staff or request.user.is_superuser),
        },
        status=status.HTTP_200_OK,
    )
