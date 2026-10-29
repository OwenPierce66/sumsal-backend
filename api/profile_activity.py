"""Actividad que cada persona decide si se ve en su perfil.

- likes: publicaciones a las que les dio me gusta.
- comments: dónde comentó (aportaciones y respuestas del foro).
- verifications: a quién verificó y quién lo verificó.

Cada tipo tiene su interruptor en Profile (`likes_public`, `comments_public`,
`verifications_public`). El dueño siempre ve todo; los demás, solo lo público.
"""
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import models as ms

User = get_user_model()

ACTIVITY_LIMIT = 30
VISIBILITY_FIELDS = {
    "likes": "likes_public",
    "comments": "comments_public",
    "verifications": "verifications_public",
}


def _user_data(user, request):
    from .serializers import SimpleUserSerializer

    return SimpleUserSerializer(user, context={"request": request}).data


def _task_data(task):
    return {
        "id": str(task.pk),
        "title": task.title,
        "pch": task.pch,
        "user": {"id": str(task.user_id), "username": task.user.username if task.user else ""},
    }


def _visible_tasks(viewer):
    from .views import exclude_hidden_tasks, exclude_unsaved_stories

    return exclude_hidden_tasks(exclude_unsaved_stories(ms.Task.objects.all()), viewer=viewer)


def _likes(owner, request):
    likes = ms.Like.objects.filter(
        user=owner, is_hidden=False, task__in=_visible_tasks(request.user),
    ).select_related("task__user").order_by("-created_at")
    return likes.count(), [
        {"id": str(like.pk), "created_at": like.created_at, "task": _task_data(like.task)}
        for like in likes[:ACTIVITY_LIMIT]
    ]


def _forum_root(post):
    while post.parent_id:
        post = post.parent
    return post


def _comments(owner, request):
    task_comments = ms.NewPeticionCommentPost.objects.filter(
        created_by=owner, post__in=_visible_tasks(request.user),
    ).select_related("post__user").order_by("-created_at")
    forum_replies = ms.Postt.objects.filter(
        user=owner, parent__isnull=False,
    ).select_related("parent__parent__parent").order_by("-created_at")

    rows = [
        (comment.created_at, {
            "id": f"comment-{comment.pk}",
            "kind": "task",
            "created_at": comment.created_at,
            "text": comment.text,
            "task": _task_data(comment.post),
        })
        for comment in task_comments[:ACTIVITY_LIMIT]
    ]
    for reply in forum_replies[:ACTIVITY_LIMIT]:
        root = _forum_root(reply)
        rows.append((reply.created_at, {
            "id": f"forum-{reply.pk}",
            "kind": "forum",
            "created_at": reply.created_at,
            "text": reply.content,
            "forum_post": {"id": root.pk, "title": root.title},
        }))
    rows.sort(key=lambda row: row[0], reverse=True)
    return task_comments.count() + forum_replies.count(), [data for _, data in rows[:ACTIVITY_LIMIT]]


def _verifications(owner, request):
    given = ms.UserVerification.objects.filter(verifier=owner).select_related("verified")
    received = ms.UserVerification.objects.filter(verified=owner).select_related("verifier")
    return given.count() + received.count(), {
        "given": [
            {"id": str(item.pk), "created_at": item.created_at, "user": _user_data(item.verified, request)}
            for item in given[:ACTIVITY_LIMIT]
        ],
        "received": [
            {"id": str(item.pk), "created_at": item.created_at, "user": _user_data(item.verifier, request)}
            for item in received[:ACTIVITY_LIMIT]
        ],
    }


LOADERS = {"likes": _likes, "comments": _comments, "verifications": _verifications}


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def user_activity(request, user_id):
    """GET ?kind=likes|comments|verifications: esa actividad (si su dueño la muestra).
    PATCH {kind, public}: el dueño decide si se ve en su perfil."""
    owner = get_object_or_404(User, pk=user_id)
    profile, _ = ms.Profile.objects.get_or_create(user=owner)
    is_owner = owner.pk == request.user.pk
    kind = request.data.get("kind") if request.method == "PATCH" else request.query_params.get("kind")
    if kind not in VISIBILITY_FIELDS:
        return Response(
            {"kind": [f"Debe ser uno de: {', '.join(VISIBILITY_FIELDS)}."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    field = VISIBILITY_FIELDS[kind]

    if request.method == "PATCH":
        if not is_owner:
            return Response({"detail": "Solo puedes cambiar tu propia actividad."}, status=status.HTTP_403_FORBIDDEN)
        value = request.data.get("public")
        if not isinstance(value, bool):
            return Response({"public": ["Debe ser verdadero o falso."]}, status=status.HTTP_400_BAD_REQUEST)
        setattr(profile, field, value)
        profile.save(update_fields=[field, "updated_at"])

    public = getattr(profile, field)
    data = {"kind": kind, "public": public, "is_owner": is_owner, "hidden": False, "count": 0, "items": []}
    if is_owner:
        # Para que el dueño vea juntos sus tres interruptores.
        data["visibility"] = {name: getattr(profile, attr) for name, attr in VISIBILITY_FIELDS.items()}
    if not is_owner and not public:
        data["hidden"] = True
        return Response(data)
    data["count"], data["items"] = LOADERS[kind](owner, request)
    return Response(data)
