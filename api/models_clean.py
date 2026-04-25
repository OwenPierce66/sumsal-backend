from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.conf import settings
from . import models as ms

User = get_user_model()

# ============================================================================
# UTILIDADES
# ============================================================================

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

# ============================================================================
# SERIALIZERS DE USUARIO Y PERFIL (Sumsal Sync)
# ============================================================================

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


class SimpleUserSerializer(serializers.ModelSerializer):
    """Versión ligera de usuario para listas y comentarios"""
    profile = ProfileSerializer(read_only=True)
    likes_count = serializers.SerializerMethodField()
    user_image = serializers.SerializerMethodField()
    has_liked = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "profile",
            "likes_count",
            "user_image",
            "has_liked",
        ]

    def get_likes_count(self, obj):
        return ms.LikeP.objects.filter(profile=obj).count()

    def get_user_image(self, obj):
        imagen_fija = ms.ImagenFija.objects.filter(user=obj).last()
        if imagen_fija and imagen_fija.image:
            request = self.context.get("request")
            return file_to_abs_url(imagen_fija.image, request)
        return None

    def get_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return ms.LikeP.objects.filter(user=request.user, profile=obj).exists()
        return False

# ============================================================================
# SERIALIZERS PARA CONTENIDO (Tasks, Comments, Categories)
# ============================================================================

class NewCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.NewCategory
        fields = ["id", "name"]


class CategoryPSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.CategoryP
        fields = ["id", "name", "user"]
        read_only_fields = ["id", "user"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class RecursiveCommentSerializer(serializers.Serializer):
    """Maneja la recursividad de los hilos de comentarios"""
    def to_representation(self, value):
        serializer = NewPeticionCommentSerializer(value, context=self.context)
        return serializer.data


class NewPeticionCommentPost(TimeStampedModel):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_comments")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    
    # CAMBIA ESTA LÍNEA: debe ser related_name="comments"
    post = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments") 
    
    aportacion = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="contributions")
    text = models.TextField(_("comment text"))
    
class NewPeticionCommentSerializer(serializers.ModelSerializer):
    created_by = SimpleUserSerializer(read_only=True)
    children = RecursiveCommentSerializer(many=True, read_only=True)
    likes_count = serializers.SerializerMethodField()
    user_has_liked = serializers.SerializerMethodField()

    class Meta:
        model = ms.NewPeticionCommentPost
        fields = [
            "id", "created_by", "parent", "post", "aportacion", 
            "text", "children", "likes_count", "user_has_liked", "created_at"
        ]
        read_only_fields = ["id", "created_by", "created_at"]

    def get_likes_count(self, obj):
        return obj.likes.count()

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False


class TaskSerializer(serializers.ModelSerializer):
    user = SimpleUserSerializer(read_only=True)
    likes_count = serializers.SerializerMethodField()
    user_has_liked = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()

    class Meta:
        model = ms.Task
        fields = [
            "id", "user", "title", "description", "pch", "username",
            "categories", "image", "video", "share_count", "likes_count",
            "user_has_liked", "comments_count", "created_at"
        ]
        read_only_fields = ["id", "user", "share_count", "created_at"]

    def get_likes_count(self, obj):
        return obj.likes.count()

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_comments_count(self, obj):
        return obj.comments.count()


class SharedTaskSerializer(serializers.ModelSerializer):
    task = TaskSerializer(read_only=True)
    shared_by = SimpleUserSerializer(read_only=True)

    class Meta:
        model = ms.SharedTask
        fields = ["id", "task", "shared_by", "description", "created_at"]
        read_only_fields = ["id", "shared_by", "created_at"]

# ============================================================================
# IMÁGENES Y OTROS
# ============================================================================

class PortadaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.Portada
        fields = ["id", "title", "image", "user", "created_at"]
        read_only_fields = ["id", "user", "created_at"]


class ImagenFijaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.ImagenFija
        fields = ["id", "image", "user", "created_at"]
        read_only_fields = ["id", "user", "created_at"]


class PosttSerializer(serializers.ModelSerializer):
    user = SimpleUserSerializer(read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = ms.Postt
        fields = ["id", "title", "content", "user", "parent", "replies", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def get_replies(self, obj):
        replies = ms.Postt.objects.filter(parent=obj)
        return PosttSerializer(replies, many=True, context=self.context).data