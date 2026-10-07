from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models import OuterRef, Subquery, Count, Q
from django.conf import settings
from . import models as ms
from .upload_validation import validate_image_upload, validate_video_upload

User = get_user_model()

# Slug de la etiqueta de aprobación (espejo de ms.APPROVED_TAG).
APPROVED_TAG = "aprobada"


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


# ---------------------------------------------------------------------------
# Helpers anti N+1 (Fase 36)
# ---------------------------------------------------------------------------

def is_prefetched(obj, relation):
    """True si `relation` ya fue cargada con prefetch_related en `obj`."""
    return relation in getattr(obj, "_prefetched_objects_cache", {})


def related_count(obj, relation):
    """Cuenta una relaci??n reutilizando el prefetch si existe (evita un COUNT por fila)."""
    if is_prefetched(obj, relation):
        return len(getattr(obj, relation).all())
    return getattr(obj, relation).count()


def related_has_user(obj, relation, user):
    """??`user` aparece en `relation` (likes, etc.)? Usa el prefetch si existe."""
    if is_prefetched(obj, relation):
        return any(item.user_id == user.id for item in getattr(obj, relation).all())
    return getattr(obj, relation).filter(user=user).exists()


def my_ids(request, key, model, field):
    """
    Conjunto de ids (`field`) de los registros de `model` creados por el usuario
    autenticado. Se consulta UNA vez por petici??n y se reutiliza para todos los
    items de la lista (en vez de un `.exists()` por item).
    """
    if not request or not request.user.is_authenticated:
        return set()
    cache = request.__dict__.setdefault("_perf_cache", {})
    if key not in cache:
        cache[key] = set(
            model.objects.filter(user=request.user).values_list(field, flat=True)
        )
    return cache[key]


def latest_user_image_url(user, request=None):
    """URL absoluta de la ??ltima ImagenFija del usuario (usa prefetch `fixed_images`)."""
    if is_prefetched(user, "fixed_images"):
        images = list(user.fixed_images.all())
        image = max(images, key=lambda i: i.id) if images else None
    else:
        image = ms.ImagenFija.objects.filter(user=user).order_by("-id").first()
    return file_to_abs_url(image.image if image and image.image else None, request)


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
            "favorite_profiles_public",
            "favorite_tasks_public",
        ]
        read_only_fields = ["id"]


class ImagenFijaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.ImagenFija
        fields = ["id", "image", "user", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    password = serializers.CharField(write_only=True, required=False, style={"input_type": "password"})
    user_image = serializers.ImageField(write_only=True, required=False)
    
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
            "user_image",
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

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


# ============================================================================
# SERIALIZERS PARA CATEGORÍAS
# ============================================================================

class NewCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.NewCategory
        fields = ["id", "name", "pch", "parent", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        """Solo se rechaza si el mismo nombre ya existe DENTRO del mismo PCH."""
        name = str(attrs.get("name") or "").strip()
        pch = str(attrs.get("pch") or "").strip()
        request = self.context.get("request")
        is_admin = bool(
            request and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )
        normalized_name = " ".join(name.split()).casefold()
        approval_aliases = {"aprobada", "aprobadas", "aprovada", "aprovadas"}
        if normalized_name in approval_aliases:
            raise serializers.ValidationError({
                "name": "Aprobada es un estado del sistema y no puede crearse como categoría."
            })
        if name:
            qs = ms.NewCategory.objects.filter(name__iexact=name, pch__iexact=pch)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({
                    "name": f"La categoría '{name}' ya existe en este tema."
                })
        attrs["name"] = name
        attrs["pch"] = pch
        return attrs


class CategoryPSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.CategoryP
        fields = ["id", "name", "user", "parent", "position", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("El filtro necesita un nombre.")
        if value.casefold() == APPROVED_TAG.casefold():
            raise serializers.ValidationError(
                "La etiqueta 'aprobada' es exclusiva de administradores, no puede usarse en tu filtro personal."
            )
        return value

    def validate_parent(self, value):
        if value is None:
            return value
        request = self.context.get("request")
        if request and value.user_id != request.user.id:
            raise serializers.ValidationError("Esa categoría padre no es tuya.")
        return value

    def create(self, validated_data):
        user = self.context["request"].user
        validated_data["user"] = user
        if "position" not in validated_data:
            last = ms.CategoryP.objects.filter(
                user=user, parent=validated_data.get("parent")
            ).order_by("-position").first()
            validated_data["position"] = (last.position + 1) if last else 0
        return super().create(validated_data)


class PersonalFilterVisibilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.Profile
        fields = [
            "personal_filter_public",
            "favorite_profiles_public",
            "favorite_tasks_public",
        ]


class UserSavedFilterSerializer(serializers.ModelSerializer):
    class Meta:
        model = ms.UserSavedFilter
        fields = ["id", "name", "filters", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("El filtro necesita un nombre.")
        return value

    def validate_filters(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("El filtro debe ser un objeto de criterios.")
        return value

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
            "is_superuser",
            "is_staff",
            "likes_count",
            "user_image",
            "has_liked",
            "is_favorited",
        ]

    def get_is_favorited(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            # `pFavorito` se relaciona con el usuario objetivo, no con el perfil.
            return obj.pk in my_ids(request, "pfav", ms.pFavorito, "perfil_id")
        return False

    def get_likes_count(self, obj):
        # ✅ FIX DEFINITIVO: El modelo LikeP.profile ahora apunta a User, no a Profile.
        # Usamos `obj` (que es un User) directamente en la consulta.
        # Esto soluciona el error fatal que tumbaba el servidor.
        return related_count(obj, "likes_received")

    def get_user_image(self, obj):
        return latest_user_image_url(obj, self.context.get("request"))

    def get_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            # ✅ FIX DEFINITIVO: Usamos `obj` (User) directamente, igual que en get_likes_count.
            return obj.pk in my_ids(request, "likep", ms.LikeP, "profile_id")
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
        return related_count(obj, "likes")

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return related_has_user(obj, "likes", request.user)
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
    views_count = serializers.SerializerMethodField()
    user_has_liked = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()
    # ✅ FIX: Especificamos que el campo 'comments' debe leer de la relación 'post_comments' del modelo Task.
    comments = NewPeticionCommentSerializer(source='post_comments', many=True, read_only=True)
    subtasks = SubTaskSerializer(many=True, read_only=True)
    subfactores = SubFactoresSerializer(many=True, read_only=True)
    subfuentes = SubFuentesSerializer(many=True, read_only=True)
    is_favorited = serializers.SerializerMethodField()
    is_original = serializers.SerializerMethodField()
    shared_by_list = serializers.SerializerMethodField()
    favorite_shared_by_list = serializers.SerializerMethodField()
    favorite_shared_by = serializers.SerializerMethodField()
    favorite_sharers_count = serializers.SerializerMethodField()
    tagged_users = serializers.SerializerMethodField()
    podcast_invitation_status = serializers.SerializerMethodField()

    class Meta:
        model = ms.Task
        fields = '__all__'
        read_only_fields = ["id", "user", "share_count", "created_at"]

    def validate_video(self, value):
        return validate_video_upload(value)

    def validate_image(self, value):
        return validate_image_upload(value)

    def get_is_original(self, obj):
        # Por defecto, si serializamos una Task directamente, es original.
        return True

    def get_tagged_users(self, obj):
        return [
            {
                "id": str(tag.user.id),
                "username": getattr(tag.user, "username", None),
                "first_name": getattr(tag.user, "first_name", "") or "",
                "last_name": getattr(tag.user, "last_name", "") or "",
            }
            for tag in obj.tagged_users.all()
        ]

    def get_podcast_invitation_status(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        if is_prefetched(obj, "podcast_invitations"):
            invitation = next(
                (i for i in obj.podcast_invitations.all() if i.user_id == request.user.id),
                None,
            )
        else:
            invitation = obj.podcast_invitations.filter(user=request.user).first()
        return invitation.status if invitation else None

    def validate(self, attrs):
        """La etiqueta reservada 'aprobada' solo la puede poner o quitar el staff."""
        if "categories" in attrs:
            request = self.context.get("request")
            user = getattr(request, "user", None)
            is_admin = bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))

            def normalize(cat_list):
                return [str(c).strip().lower() for c in cat_list if str(c).strip()]

            new_cats = normalize(str(attrs.get("categories") or "").split(","))
            instance = getattr(self, "instance", None)
            old_cats = normalize(str(getattr(instance, "categories", "") or "").split(",")) if instance else []

            adds_approved = APPROVED_TAG in new_cats and APPROVED_TAG not in old_cats
            removes_approved = APPROVED_TAG in old_cats and APPROVED_TAG not in new_cats

            if (adds_approved or removes_approved) and not is_admin:
                raise serializers.ValidationError({
                    "categories": "La etiqueta 'aprobada' solo puede modificarla un administrador."
                })

            is_podcast = "grabar podcast" in new_cats
            has_approved = APPROVED_TAG in new_cats
            if is_podcast and not has_approved and "procesando" not in new_cats:
                categories_value = str(attrs.get("categories") or "")
                categories_value = f"{categories_value}, Procesando".strip(", ")
                attrs["categories"] = categories_value
        return attrs

    def get_is_favorited(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.pk in my_ids(request, "fav", ms.Favorito, "task_id")
        return False

    def _get_share_img_cache(self):
        if not hasattr(self, "_share_img_cache"):
            self._share_img_cache = {}
        return self._share_img_cache

    def _get_sorted_shared_instances(self, obj):
        if not hasattr(self, "_sorted_shared_instances_cache"):
            self._sorted_shared_instances_cache = {}

        task_key = str(obj.id)
        if task_key not in self._sorted_shared_instances_cache:
            shared_instances = list(obj.shared_instances.all())
            shared_instances.sort(key=lambda share: (share.created_at, str(share.id)))
            self._sorted_shared_instances_cache[task_key] = shared_instances
        return self._sorted_shared_instances_cache[task_key]

    def _serialize_shared_instance(self, share, request):
        shared_by = share.shared_by
        if not shared_by:
            return {
                "id": None,
                "username": "unknown",
                "description": share.description or "",
                "user_image": None,
            }

        share_img_cache = self._get_share_img_cache()
        if shared_by.id not in share_img_cache:
            share_img_cache[shared_by.id] = latest_user_image_url(shared_by, request)

        return {
            "id": shared_by.id,
            "username": getattr(shared_by, "username", "unknown"),
            "description": share.description or "",
            "user_image": share_img_cache[shared_by.id],
        }

    def _get_favorite_profile_ids(self):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return set()

        if not hasattr(self, "_favorite_profile_ids_cache"):
            self._favorite_profile_ids_cache = my_ids(
                request, "pfav", ms.pFavorito, "perfil_id"
            )
        return self._favorite_profile_ids_cache

    def _get_favorite_shared_by_list(self, obj):
        if not hasattr(self, "_favorite_shared_by_cache"):
            self._favorite_shared_by_cache = {}

        task_key = str(obj.id)
        if task_key in self._favorite_shared_by_cache:
            return self._favorite_shared_by_cache[task_key]

        request = self.context.get("request")
        favorite_profile_ids = self._get_favorite_profile_ids()
        if not favorite_profile_ids:
            self._favorite_shared_by_cache[task_key] = []
            return self._favorite_shared_by_cache[task_key]

        favorite_shared = []
        for share in self._get_sorted_shared_instances(obj):
            if share.shared_by_id in favorite_profile_ids:
                favorite_shared.append(self._serialize_shared_instance(share, request))
        self._favorite_shared_by_cache[task_key] = favorite_shared
        return self._favorite_shared_by_cache[task_key]

    def get_shared_by_list(self, obj):
        request = self.context.get("request")
        return [
            self._serialize_shared_instance(share, request)
            for share in self._get_sorted_shared_instances(obj)
        ]

    def get_favorite_shared_by_list(self, obj):
        return self._get_favorite_shared_by_list(obj)

    def get_favorite_shared_by(self, obj):
        favorite_shared = self._get_favorite_shared_by_list(obj)
        return favorite_shared[-1] if favorite_shared else None

    def get_favorite_sharers_count(self, obj):
        return len(self._get_favorite_shared_by_list(obj))

    def _count_nested_comments(self, comment):
        """Cuenta un comentario y todas sus respuestas recursivamente"""
        count = 1  # Contar el comentario actual
        replies = comment.replies.all()  # Acceder a las respuestas anidadas (usa prefetch si existe)
        for reply in replies:
            count += self._count_nested_comments(reply)
        return count

    def get_likes_count(self, obj):
        return related_count(obj, "likes")

    def get_views_count(self, obj):
        if obj.pch != "historias":
            return 0
        annotated_count = getattr(obj, "views_count", None)
        if annotated_count is not None:
            return annotated_count
        return obj.story_views.count()

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return related_has_user(obj, "likes", request.user)
        return False
    
    def get_comments_count(self, obj):
        """Devuelve el total de comentarios anidados"""
        try:
            # Obtener solo los comentarios padre (sin parent). Se filtra en Python
            # para reutilizar el prefetch de `post_comments`.
            parent_comments = [c for c in obj.post_comments.all() if c.parent_id is None]
            total = sum(self._count_nested_comments(c) for c in parent_comments)
            return total
        except Exception as e:
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
        return related_count(obj, "likes")

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return related_has_user(obj, "likes", request.user)
        return False

    def get_comments_count(self, obj):
        parent_comments = [c for c in obj.comments.all() if c.parent_id is None]
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
# SERIALIZER PARA EL FEED UNIFICADO
# ============================================================================

class FeedItemSerializer(serializers.Serializer):
    """
    Serializador "adaptador" que sabe cómo manejar la clase proxy FeedItem.
    Determina si el item es una Task o una SharedTask y usa el serializador correcto.
    """
    def to_representation(self, instance):
        # `instance` aquí es un objeto `FeedItem`
        if instance.is_original:
            # Es una Task original
            serializer = TaskSerializer(instance.item, context=self.context)
        else:
            # Es una SharedTask
            serializer = SharedTaskSerializer(instance.item, context=self.context)
        
        data = serializer.data
        data['is_original'] = instance.is_original # Añadimos el flag para el frontend
        return data

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
        # `forum_replies.all()` reutiliza el prefetch de la vista (si existe).
        replies = obj.forum_replies.all()
        return PosttSerializer(replies, many=True, context=self.context).data

    def get_likes_count(self, obj):
        return related_count(obj, "likes")

    def get_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return related_has_user(obj, "likes", request.user)
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
        return related_count(obj, "likes")

    def get_user_has_liked(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return related_has_user(obj, "likes", request.user)
        return False


class SharedTaskDetailSerializer(serializers.ModelSerializer):
    """Serializer extendido para tareas compartidas con comentarios y likes"""
    task = TaskSerializer(read_only=True)
    shared_by = SimpleUserSerializer(read_only=True)
    comments = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    user_has_liked = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()
    # ✅ AÑADIMOS EL NUEVO CAMPO
    favorite_sharers_count = serializers.IntegerField(read_only=True, default=0)

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
            "favorite_sharers_count",
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
