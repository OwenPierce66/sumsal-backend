from rest_framework import serializers

from .models import ImagenFija, Notification
from .serializers import file_to_abs_url


class NotificationSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()
    type = serializers.CharField(source="notification_type", read_only=True)
    text = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "actor",
            "type",
            "notification_type",
            "text",
            "data",
            "target_type",
            "target_id",
            "secondary_target_type",
            "secondary_target_id",
            "is_read",
            "read_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_actor(self, obj):
        if not obj.actor:
            return None
        image = ImagenFija.objects.filter(user=obj.actor).order_by("-id").first()
        full_name = " ".join(
            part for part in (obj.actor.first_name, obj.actor.last_name) if part
        )
        return {
            "id": str(obj.actor_id),
            "username": obj.actor.username,
            "name": full_name or obj.actor.username or obj.actor.email,
            "image": file_to_abs_url(
                image.image if image else None,
                self.context.get("request"),
            ),
        }

    def get_text(self, obj):
        return obj.data.get("text", "")
