# serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models.fields.files import ImageFieldFile, FieldFile

User = get_user_model()

from .models import (
    Message,
    MessageAttachment,
    Group,
    GroupMembership,
    GroupMessage,
    GroupMessageAttachment,
)


class UserSerializer(serializers.ModelSerializer):
    """
    Usuario con campo de imagen listo para el chat.
    Intenta encontrar cualquier ImageField en User o en algún perfil 1-a-1.
    """
    image = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "name", "email", "image", "profile_image", "avatar"]

    def get_name(self, obj):
        full_name = " ".join(
            part for part in (obj.first_name, obj.last_name) if part
        ).strip()
        return full_name or obj.username or obj.email

    def _get_any_image_field(self, obj):
        """
        Devuelve el FieldFile de la imagen de perfil, buscando:
        1) Atributos típicos en User (image, profile_image, etc.)
        2) Cualquier ImageField directo en User
        3) Cualquier ImageField en relaciones OneToOne (perfil, profile, etc.)
        """
        if not obj or not hasattr(obj, '_meta'):
            return None

        # 1) Atributos típicos en el propio User
        candidate_attrs = [
            "image",
            "profile_image",
            "avatar",
            "image_profile",
            "foto",
            "photo",
            "picture",
            "imagen_perfil",
            "user_image",
        ]
        for attr in candidate_attrs:
            if hasattr(obj, attr):
                val = getattr(obj, attr)
                if isinstance(val, (ImageFieldFile, FieldFile)) and getattr(val, "url", None):
                    return val

        # 2) Buscar cualquier ImageField directo en User
        for field in obj._meta.fields:
            try:
                val = getattr(obj, field.name)
            except Exception:
                continue

            if isinstance(val, (ImageFieldFile, FieldFile)) and getattr(val, "url", None):
                return val

        # 3) Buscar en relaciones OneToOne (perfiles) reversas
        for rel in obj._meta.related_objects:
            if not rel.one_to_one:
                continue

            accessor_name = rel.get_accessor_name()  # p.ej. "profile", "perfilusuario", etc.
            profile_obj = getattr(obj, accessor_name, None)
            if not profile_obj:
                continue

            for field in profile_obj._meta.fields:
                try:
                    val = getattr(profile_obj, field.name)
                except Exception:
                    continue

                if isinstance(val, (ImageFieldFile, FieldFile)) and getattr(val, "url", None):
                    return val

        # Si no encontramos nada, devolvemos None
        return None

    def _build_url(self, file_field):
        if not file_field:
            return None
        request = self.context.get("request")
        url = getattr(file_field, "url", None)
        if not url:
          return None
        return request.build_absolute_uri(url) if request else url

    def get_image(self, obj):
        if not obj: return None
        return self._build_url(self._get_any_image_field(obj))

    def get_profile_image(self, obj):
        # Para simplificar, reutilizamos el mismo campo
        return self.get_image(obj)

    def get_avatar(self, obj):
        # Igual que image
        return self.get_image(obj)


class MessageAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageAttachment
        fields = ["id", "file", "file_type", "is_image", "is_video"]


class GroupMessageAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupMessageAttachment
        fields = ["id", "file", "file_type", "is_image", "is_video"]


class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    receiver = UserSerializer(read_only=True)
    attachments = MessageAttachmentSerializer(many=True, read_only=True)

    # respuesta a otro mensaje
    replied_to = serializers.SerializerMethodField()

    # campos top-level por compat con el front: msg.sender_image / msg.user_image
    sender_image = serializers.SerializerMethodField()
    user_image = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "sender",
            "receiver",
            "content",
            "translated_content",
            "image",
            "video",
            "timestamp",
            "is_read",
            "read_at",
            "replied_to",
            "attachments",
            "sender_image",
            "user_image",
        ]

    def get_replied_to(self, obj):
        if not obj.replied_to:
            return None
        rep = obj.replied_to
        
        # Safe check in case replied_to message has no sender
        sender_id = rep.sender.id if rep.sender else None
        sender_username = getattr(rep.sender, "username", None) if rep.sender else None
        
        return {
            "id": rep.id,
            "content": rep.content,
            "sender": {
                "id": sender_id,
                "username": sender_username,
            },
            "timestamp": rep.timestamp,
        }

    def _get_sender_image_url(self, obj):
        user = obj.sender
        if not user: return None
        serializer = UserSerializer(user, context=self.context)
        # usa el mismo campo "image" del serializer
        return serializer.data.get("image")

    def get_sender_image(self, obj):
        return self._get_sender_image_url(obj)

    def get_user_image(self, obj):
        return self._get_sender_image_url(obj)


class GroupSerializer(serializers.ModelSerializer):
    members = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ["id", "name", "created_at", "created_by", "members"]

    def get_members(self, obj):
        memberships = getattr(obj, "prefetched_memberships", None)
        if memberships is None:
            memberships = (
                GroupMembership.objects.filter(group=obj)
                .select_related("user")
                .order_by("joined_at", "id")
            )
        data = []
        for m in memberships:
            user_data = UserSerializer(m.user, context=self.context).data
            user_data['is_admin'] = m.is_admin
            data.append(user_data)
        return data


class GroupCreateSerializer(serializers.ModelSerializer):
    members = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = Group
        fields = ["name", "members"]


class GroupMembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = GroupMembership
        fields = ["id", "user", "group", "is_admin", "joined_at", "last_read_at"]


class GroupMessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    group = serializers.PrimaryKeyRelatedField(read_only=True)
    attachments = GroupMessageAttachmentSerializer(many=True, read_only=True)

    replied_to = serializers.SerializerMethodField()
    sender_image = serializers.SerializerMethodField()
    user_image = serializers.SerializerMethodField()

    class Meta:
        model = GroupMessage
        fields = [
            "id",
            "group",
            "sender",
            "content",
            "image",
            "video",
            "timestamp",
            "replied_to",
            "attachments",
            "sender_image",
            "user_image",
        ]

    def get_replied_to(self, obj):
        if not obj.replied_to:
            return None
        rep = obj.replied_to
        
        sender_id = rep.sender.id if rep.sender else None
        sender_username = getattr(rep.sender, "username", None) if rep.sender else None
        
        return {
            "id": rep.id,
            "content": rep.content,
            "sender": {
                "id": sender_id,
                "username": sender_username,
            },
            "timestamp": rep.timestamp,
        }

    def _get_sender_image_url(self, obj):
        user = obj.sender
        if not user: return None
        serializer = UserSerializer(user, context=self.context)
        return serializer.data.get("image")

    def get_sender_image(self, obj):
        return self._get_sender_image_url(obj)

    def get_user_image(self, obj):
        return self._get_sender_image_url(obj)
