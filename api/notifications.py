from django.db import IntegrityError, transaction

from .models import Notification


def build_dedupe_key(
    notification_type,
    actor,
    target_type,
    target_id,
    secondary_target_type="",
    secondary_target_id="",
):
    actor_id = getattr(actor, "pk", actor) or "system"
    return ":".join(
        str(value)
        for value in (
            notification_type,
            actor_id,
            target_type,
            target_id,
            secondary_target_type,
            secondary_target_id,
        )
    )[:255]


def create_notification(
    *,
    recipient,
    actor,
    notification_type,
    target_type,
    target_id,
    secondary_target_type="",
    secondary_target_id="",
    data=None,
    dedupe_key="",
):
    if not recipient or (actor and recipient.pk == actor.pk):
        return None

    dedupe_key = dedupe_key or build_dedupe_key(
        notification_type,
        actor,
        target_type,
        target_id,
        secondary_target_type,
        secondary_target_id,
    )
    values = {
        "actor": actor,
        "notification_type": notification_type,
        "target_type": target_type,
        "target_id": str(target_id),
        "secondary_target_type": secondary_target_type or "",
        "secondary_target_id": (
            str(secondary_target_id) if secondary_target_id is not None else ""
        ),
        "data": data or {},
    }
    try:
        with transaction.atomic():
            notification, _ = Notification.objects.get_or_create(
                recipient=recipient,
                dedupe_key=dedupe_key,
                defaults=values,
            )
    except IntegrityError:
        notification = Notification.objects.filter(
            recipient=recipient,
            dedupe_key=dedupe_key,
        ).first()
    return notification


def retire_notification(*, dedupe_key, recipient=None):
    notifications = Notification.objects.filter(dedupe_key=dedupe_key)
    if recipient is not None:
        notifications = notifications.filter(recipient=recipient)
    return notifications.delete()[0]
