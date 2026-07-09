from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models import OuterRef, Subquery, Count, Q
from django.conf import settings
from . import models as ms

User = get_user_model()


def file_to_abs_url(file_or_str, request=None):
    """Convierte FieldFile o string a URL absoluta"""
    if not file_or_str:
        return None

    if hasattr(file_or_str, "url"):
        url = file_or_str.url
    else:
        url = str(file_or_str).strip()
        if not url:
            return None

        if url.startswith(("http://", "https://")):
            return url

        media_url = (getattr(settings, "MEDIA_URL", "/media/") or "/media/").rstrip("/")

        if not url.startswith("/") and not url.startswith(media_url + "/"):
            url = f"{media_url}/{url.lstrip('/')}"
        elif not url.startswith("/"):
            url = "/" + url

    if request and url and not url.startswith(("http://", "https://")):
        if not url.startswith("/"):
            url = "/" + url
        return request.build_absolute_uri(url)

    return url


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.Profile
        fields = [
            "id",
            "is_verified",
            "is_recommended",
            "subscriptionActive",
            "subscription_amount",
            "role",
        ]
        read_only_fields = ["id"]


class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    password = serializers.CharField(
        write_only=True, required=True, style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "profile",
            "is_superuser",
            "is_staff",
            "date_joined",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "is_superuser",
            "is_staff",
            "date_joined",
            "updated_at",
        ]

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User.objects.create_user(**validated_data)
        user.set_password(password)
        user.save()
        return user


# ============================================================================
# SERIALIZERS PARA CATEGORÍAS
# ============================================================================

class NewCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.NewCategory
        fields = ["id", "name", "created_at"]
        read_only_fields = ["id", "created_at"]


class CategoryPSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.CategoryP
        fields = ["id", "name", "user", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


# ============================================================================
# SERIALIZERS PARA USUARIO SIMPLE
# ============================================================================

class SimpleUserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    likes_count = serializers.SerializerMethodField()
    user_image = serializers.SerializerMethodField()
    has_liked = serializers.SerializerMethodField()
    is_favorited = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "profile",
            "likes_count",
            "user_image",
            "has_liked",
            "is_favorited",
        ]

    def get_is_favorited(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            # ✅ FIX: `pFavorito` se relaciona con `Profile`, no con `User`.
            if hasattr(obj, 'profile'):
                return ms.pFavorito.objects.filter(user=request.user, perfil=obj.profile).exists()
        return False

    def get_likes_count(self, obj):
        # ✅ FIX: `LikeP` se relaciona con `Profile`, no con `User`.
        if hasattr(obj, 'profile'):
            return ms.LikeP.objects.filter(profile=obj.profile).count()
        return 0

    def get_user_image(self, obj):
        imagen_fija = ms.ImagenFija.objects.filter(user=obj).last()
        if imagen_fija and imagen_fija.image:
            request = self.context.get("request")
            return file_to_abs_url(imagen_fija.image, request)
        return None

    def get_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            # ✅ FIX: `LikeP` se relaciona con `Profile`, no con `User`.
            if hasattr(obj, 'profile'):
                return ms.LikeP.objects.filter(user=request.user, profile=obj.profile).exists()
        return False


# ============================================================================
# SERIALIZERS PARA LIKES Y FAVORITOS
# ============================================================================

class LikeSerializer(serializers.ModelSerializer):
    user = SimpleUserSerializer(read_only=True)

    class Meta:
        model = ms.Like
        fields = ["id", "user", "task", "created_at"]
        read_only_fields = ["id", "created_at"]


class LikeCommentPostSerializer(serializers.ModelSerializer):
    user = SimpleUserSerializer(read_only=True)

    class Meta:
        model = ms.LikeCommentPost
        fields = ["id", "user", "comment", "created_at"]
        read_only_fields = ["id", "created_at"]


class FavoritoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.Favorito
        fields = ["id", "user", "task", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class pFavoritoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.pFavorito
        fields = ["id", "user", "perfil", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


# ============================================================================
# SERIALIZERS PARA TAREAS Y COMENTARIOS
# ============================================================================

class RecursiveCommentSerializer(serializers.Serializer):
    """Serializer recursivo para comentarios anidados"""
    def to_representation(self, value):
        serializer = NewPeticionCommentSerializer(value, context=self.context)
        return serializer.data


class NewPeticionCommentSerializer(serializers.ModelSerializer):
    created_by = SimpleUserSerializer(read_only=True)
    
    # 🛡️ FIX 500: Lee del related_name "replies", pero lo exporta como "children" para React Native
    children = RecursiveCommentSerializer(source='replies', many=True, read_only=True)
    
    likes_count = serializers.SerializerMethodField()
    user_has_liked = serializers.SerializerMethodField()

    class Meta:
        model = ms.NewPeticionCommentPost
        fields = [
            "id",
            "created_by",
            "parent",
            "post",
            "aportacion",
            "text",
            "children",
            "likes_count",
            "user_has_liked",
            "created_at",
            "updated_at",
        ]
        # 🛡️ FIX 400: Añadimos 'post' para que DRF no lo exija en la validación inicial
        read_only_fields = ["id", "created_by", "post"]

    def get_likes_count(self, obj):
        return obj.likes.count()

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False
    
class SubTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.SubTask # Asegúrate de que el modelo sea el correcto
        fields = '__all__'

class SubFactoresSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.SubFactores
        fields = '__all__'

class SubFuentesSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.SubFuentes
        fields = '__all__'



class TaskSerializer(serializers.ModelSerializer):
    user = SimpleUserSerializer(read_only=True)
    likes_count = serializers.SerializerMethodField()
    user_has_liked = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()
    comments = NewPeticionCommentSerializer(many=True, read_only=True) 
    subtasks = SubTaskSerializer(many=True, read_only=True)
    subfactores = SubFactoresSerializer(many=True, read_only=True)
    subfuentes = SubFuentesSerializer(many=True, read_only=True)
    is_favorited = serializers.SerializerMethodField()

    class Meta:
        model = ms.Task
        fields = '__all__'
        read_only_fields = ["id", "user", "share_count", "created_at"]

    def get_is_favorited(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return ms.Favorito.objects.filter(user=request.user, task=obj).exists()
        return False

    def _count_nested_comments(self, comment):
        """Cuenta un comentario y todas sus respuestas recursivamente"""
        count = 1  # Contar el comentario actual
        replies = comment.replies.all()  # Acceder a las respuestas anidadas
        for reply in replies:
            count += self._count_nested_comments(reply)
        return count

    def get_likes_count(self, obj):
        return obj.likes.count()

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False
    
    def get_comments_count(self, obj):
        """Devuelve el total de comentarios anidados"""
        try:
            # Obtener solo los comentarios padre (sin parent)
            parent_comments = obj.comments.filter(parent__isnull=True)
            total = sum(self._count_nested_comments(c) for c in parent_comments)
            return total
        except Exception as e:
            print(f"Error counting comments: {e}")
            return 0
    

class SharedTaskSerializer(serializers.ModelSerializer):
    task = TaskSerializer(read_only=True)
    shared_by = SimpleUserSerializer(read_only=True)
    likes_count = serializers.SerializerMethodField()
    user_has_liked = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()

    class Meta:
        model = ms.SharedTask
        fields = [
            "id",
            "task",
            "shared_by",
            "description",
            "likes_count",
            "user_has_liked",
            "comments_count",
            "created_at",
        ]
        read_only_fields = ["id", "shared_by", "created_at"]

    def get_likes_count(self, obj):
        return obj.likes.count()

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return ms.LikeSharedTask.objects.filter(user=request.user, shared_task=obj).exists()
        return False

    def get_comments_count(self, obj):
        parent_comments = obj.comments.filter(parent__isnull=True)
        total = 0
        for comment in parent_comments:
            total += self._count_nested_comments(comment)
        return total

    def _count_nested_comments(self, comment):
        count = 1
        for child in comment.replies.all():
            count += self._count_nested_comments(child)
        return count

    def create(self, validated_data):
        validated_data["shared_by"] = self.context["request"].user
        return super().create(validated_data)


# ============================================================================
# SERIALIZERS PARA IMÁGENES Y PERFILES
# ============================================================================

class PortadaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.Portada
        fields = ["id", "title", "image", "user", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class ImagenFijaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.ImagenFija
        fields = ["id", "image", "user", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class PosttSerializer(serializers.ModelSerializer):
    user = SimpleUserSerializer(read_only=True)
    replies = serializers.SerializerMethodField()
    title = serializers.CharField(required=False, allow_blank=True)
    likes_count = serializers.SerializerMethodField()
    has_liked = serializers.SerializerMethodField()

    class Meta:
        model = ms.Postt
        fields = ["id", "title", "content", "user", "parent", "replies", "created_at", "likes_count", "has_liked"]
        read_only_fields = ["id", "user", "created_at", "likes_count", "has_liked"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        # Si no hay title o está vacío, usar null o un valor por defecto
        if not validated_data.get("title"):
            validated_data["title"] = ""
        return super().create(validated_data)

    def get_replies(self, obj):
        replies = ms.Postt.objects.filter(parent=obj)
        return PosttSerializer(replies, many=True, context=self.context).data

    def get_likes_count(self, obj):
        return ms.LikePostt.objects.filter(post=obj).count()

    def get_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return ms.LikePostt.objects.filter(user=request.user, post=obj).exists()
        return False


# ============================================================================
# SERIALIZERS PARA COMENTARIOS Y LIKES DE TAREAS COMPARTIDAS
# ============================================================================

class RecursiveSharedCommentSerializer(serializers.Serializer):
    """Serializer recursivo para comentarios anidados de tareas compartidas"""
    def to_representation(self, value):
        serializer = SharedTaskCommentSerializer(value, context=self.context)
        return serializer.data


class SharedTaskCommentSerializer(serializers.ModelSerializer):
    created_by = SimpleUserSerializer(read_only=True)
    children = RecursiveSharedCommentSerializer(source='replies', many=True, read_only=True)
    likes_count = serializers.SerializerMethodField()
    user_has_liked = serializers.SerializerMethodField()

    class Meta:
        model = ms.SharedTaskComment
        fields = [
            "id",
            "created_by",
            "parent",
            "shared_task",
            "text",
            "children",
            "likes_count",
            "user_has_liked",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "shared_task"]

    def get_likes_count(self, obj):
        return obj.likes.count()

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return ms.LikeSharedTaskComment.objects.filter(user=request.user, comment=obj).exists()
        return False


class SharedTaskDetailSerializer(serializers.ModelSerializer):
    """Serializer extendido para tareas compartidas con comentarios y likes"""
    task = TaskSerializer(read_only=True)
    shared_by = SimpleUserSerializer(read_only=True)
    comments = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    user_has_liked = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()

    class Meta:
        model = ms.SharedTask
        fields = [
            "id",
            "task",
            "shared_by",
            "description",
            "comments",
            "likes_count",
            "user_has_liked",
            "comments_count",
            "created_at",
        ]
        read_only_fields = ["id", "shared_by", "created_at"]

    def get_comments(self, obj):
        """Retorna solo comentarios padre (nivel raíz)"""
        parent_comments = obj.comments.filter(parent__isnull=True)
        return SharedTaskCommentSerializer(parent_comments, many=True, context=self.context).data

    def get_likes_count(self, obj):
        return obj.likes.count()

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return ms.LikeSharedTask.objects.filter(user=request.user, shared_task=obj).exists()
        return False

    def _count_nested_comments(self, comment):
        """Cuenta comentarios anidados recursivamente"""
        count = 1
        for child in comment.replies.all():
            count += self._count_nested_comments(child)
        return count

    def get_comments_count(self, obj):
        """Retorna el conteo total de comentarios (incluyendo anidados)"""
        parent_comments = obj.comments.filter(parent__isnull=True)
        total = 0
        for comment in parent_comments:
            total += self._count_nested_comments(comment)
        return total
