"""Etiquetas en comentarios y testimonios en el perfil.

Quien comenta puede etiquetar a otras personas. Cada etiquetada recibe una
notificación y decide si ese comentario aparece en su perfil como testimonio.
Los testimonios aprobados los ve todo el mundo.
"""
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import CommentTag
from .notifications import create_notification, retire_notification

User = get_user_model()

MAX_TAGS_PER_COMMENT = 10
MAX_TESTIMONIALS = 100
TAG_NOTIFICATION = "comment_tag"


def _dedupe_key(tag):
    return f"{TAG_NOTIFICATION}:{tag.pk}"


def _notify_tag(tag):
    comment = tag.comment
    task = comment.post
    if task.is_hidden:
        # Nadie más que el dueño puede abrir una tarea oculta.
        return
    author = comment.created_by
    create_notification(
        recipient=tag.user,
        actor=author,
        notification_type=TAG_NOTIFICATION,
        target_type="task",
        target_id=comment.post_id,
        secondary_target_type="comment",
        secondary_target_id=comment.pk,
        data={
            "text": f"{author.username or 'Alguien'} te etiquetó en un comentario. ¿Lo muestras en tu perfil como testimonio?",
            "testimonial_id": str(tag.pk),
            "title": task.title,
            "excerpt": (comment.text or "")[:140],
        },
        dedupe_key=_dedupe_key(tag),
    )


def retire_tag_notification(tag):
    retire_notification(dedupe_key=_dedupe_key(tag))


def sync_comment_tags(comment, user_ids):
    """Deja etiquetadas exactamente a `user_ids` (sin el autor), avisando a las nuevas."""
    wanted = {
        pk for pk in User.objects.filter(pk__in=list(user_ids), is_active=True)
        .exclude(pk=comment.created_by_id).values_list("pk", flat=True)
    }
    existing = {tag.user_id: tag for tag in comment.tags.all()}

    for user_id, tag in existing.items():
        if user_id not in wanted:
            tag.delete()
    for user_id in wanted - set(existing):
        tag = CommentTag.objects.create(comment=comment, user_id=user_id)
        _notify_tag(tag)


def _testimonial_data(tag, request):
    from .serializers import SimpleUserSerializer

    comment = tag.comment
    task = comment.post
    return {
        "id": str(tag.pk),
        "status": tag.status,
        "created_at": comment.created_at,
        "comment": {"id": comment.pk, "text": comment.text},
        "author": SimpleUserSerializer(comment.created_by, context={"request": request}).data,
        "task": {"id": str(task.pk), "title": task.title},
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_testimonials(request, user_id):
    """Testimonios aprobados de un perfil; a su dueño también le llegan los pendientes."""
    from .views import exclude_hidden_tasks

    owner = get_object_or_404(User, pk=user_id)
    tags = exclude_hidden_tasks(
        CommentTag.objects.filter(user=owner), request.user, prefix="comment__post__",
    ).select_related(
        "comment__created_by", "comment__post",
    ).prefetch_related("comment__created_by__fixed_images").order_by("-created_at")

    is_owner = owner.pk == request.user.pk
    approved = tags.filter(status=CommentTag.STATUS_APPROVED)[:MAX_TESTIMONIALS]
    response = {
        "testimonials": [_testimonial_data(tag, request) for tag in approved],
        "is_owner": is_owner,
    }
    if is_owner:
        pending = tags.filter(status=CommentTag.STATUS_PENDING)[:MAX_TESTIMONIALS]
        response["pending"] = [_testimonial_data(tag, request) for tag in pending]
    return Response(response)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def testimonial_detail(request, pk):
    """La persona etiquetada aprueba (lo muestra) o rechaza (lo oculta) el testimonio."""
    tag = get_object_or_404(CommentTag.objects.select_related("comment__created_by", "comment__post"), pk=pk, user=request.user)
    new_status = request.data.get("status")
    if new_status not in {CommentTag.STATUS_APPROVED, CommentTag.STATUS_REJECTED}:
        return Response(
            {"status": ["Debe ser approved o rejected."]}, status=status.HTTP_400_BAD_REQUEST,
        )
    tag.status = new_status
    tag.save(update_fields=["status", "updated_at"])
    return Response(_testimonial_data(tag, request))
