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


STORY_EXPIRED_NOTIFICATION = "story_expired"


def ensure_story_expiry_notifications(user):
    """Cuando una historia (publicada directamente) cumple 24 h, le pregunta al
    dueño si quiere guardarla en sus aportaciones.

    No hay tarea periodica (celery beat), asi que se genera al consultar las
    notificaciones. `story_prompted` evita volver a crearla si el usuario la
    descarta."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import Task

    cutoff = timezone.now() - timedelta(hours=24)
    pending = list(
        Task.objects.filter(
            user=user,
            is_story=True,
            story_saved=False,
            story_prompted=False,
            created_at__lt=cutoff,
        )[:50]
    )
    for story in pending:
        create_notification(
            recipient=user,
            actor=None,
            notification_type=STORY_EXPIRED_NOTIFICATION,
            target_type="task",
            target_id=story.pk,
            data={
                "text": "Tu historia de 24 horas terminó. ¿Quieres guardarla en tus aportaciones?",
                "story_id": str(story.pk),
            },
            dedupe_key=f"story-expired:{story.pk}",
        )
        Task.objects.filter(pk=story.pk).update(story_prompted=True)
