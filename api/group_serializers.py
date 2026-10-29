from rest_framework import serializers

from .models import CommunityGroup, CommunityGroupMember as Member
from .serializers import file_to_abs_url
from .upload_validation import validate_image_upload


def _user_info(user, request):
    images = list(user.fixed_images.all()) if hasattr(user, "fixed_images") else []
    latest = max(images, key=lambda img: img.id).image if images else None
    return {
        "id": str(user.id),
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "user_image": file_to_abs_url(latest, request),
    }


class CommunityGroupSerializer(serializers.ModelSerializer):
    """Datos de un grupo. `members_count`, `my_role` y `my_status` vienen anotados
    por la vista (ver group_views._groups_for)."""
    image = serializers.ImageField(required=False, allow_null=True, write_only=True)
    image_url = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    members_count = serializers.IntegerField(read_only=True, default=0)
    my_role = serializers.CharField(read_only=True, allow_null=True, default=None)
    my_status = serializers.CharField(read_only=True, allow_null=True, default=None)
    is_admin = serializers.SerializerMethodField()

    class Meta:
        model = CommunityGroup
        fields = [
            "id", "name", "description", "rules", "image", "image_url", "is_private",
            "created_by", "created_at", "members_count", "my_role", "my_status", "is_admin",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_name(self, value):
        value = " ".join(str(value).split())
        if not value:
            raise serializers.ValidationError("El grupo necesita un nombre.")
        return value

    def validate_image(self, value):
        return validate_image_upload(value) if value else value

    def get_image_url(self, obj):
        return file_to_abs_url(obj.image, self.context.get("request"))

    def get_created_by(self, obj):
        user = obj.created_by
        return {"id": str(user.id), "username": user.username} if user else None

    def get_is_admin(self, obj):
        return getattr(obj, "my_status", None) == Member.STATUS_ACTIVE and getattr(obj, "my_role", None) in Member.ADMIN_ROLES


class CommunityGroupMemberSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = ["id", "user", "role", "status", "created_at"]
        read_only_fields = fields

    def get_user(self, obj):
        return _user_info(obj.user, self.context.get("request"))
