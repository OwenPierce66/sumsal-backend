"""Tu actividad: todo lo que haces, y quién ve cada tipo en tu perfil.

Tipos (KINDS): me gusta, comentarios, guardados, impulsos, compartidos, seguidos,
favoritos, recomendaciones y verificaciones.

Cada tipo tiene un nivel en `Profile.activity_levels` (si no está, su valor inicial):
- private: solo su dueño.
- subscribers (modo de paga): quienes le pagan una suscripción activa. Los me gusta
  también los ven quienes tienen una suscripción en la app (`subscriptionActive`).
- public: todos.
El dueño siempre ve todo. `kind=all` junta, por fecha, los tipos que quien mira puede ver.
"Ver como yo" (`feed`) es un interruptor aparte: no es una lista (ver view_as.py).
"""
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import models as ms
from .forum_access import can_view_post

User = get_user_model()

ACTIVITY_LIMIT = 30
ALL = "all"
PRIVATE, SUBSCRIBERS, PUBLIC = "private", "subscribers", "public"
LEVELS = (PRIVATE, SUBSCRIBERS, PUBLIC)
KINDS = (
    "likes", "comments", "saves", "reposts", "shares",
    "follows", "favorites", "recommendations", "verifications",
)
# Tipos que en modo de paga también ve quien tiene una suscripción en la app.
APP_SUBSCRIPTION_KINDS = {"likes"}
DEFAULT_LEVELS = {
    "likes": PRIVATE,
    "comments": PRIVATE,
    "saves": PRIVATE,
    "reposts": PUBLIC,
    "shares": PUBLIC,
    "follows": PUBLIC,
    "verifications": PUBLIC,
}


def level_of(profile, kind):
    level = (profile.activity_levels or {}).get(kind)
    if level in LEVELS:
        return level
    # Favoritos y recomendaciones empiezan como su lista en el perfil.
    if kind == "favorites":
        return PUBLIC if profile.favorite_profiles_public else PRIVATE
    if kind == "recommendations":
        return PUBLIC if profile.recommendations_public else PRIVATE
    return DEFAULT_LEVELS[kind]


class _Access:
    """Qué tipos de la actividad de `owner` puede ver `viewer`."""

    def __init__(self, viewer, owner, profile):
        self.viewer = viewer
        self.owner = owner
        self.profile = profile
        self.is_owner = viewer.pk == owner.pk
        self._subscriber = None
        self._app_subscription = None

    def is_subscriber(self):
        if self._subscriber is None:
            self._subscriber = ms.Subscription.objects.filter(
                subscriber=self.viewer, recipient=self.owner,
                status__in=ms.Subscription.ACTIVE_STATUSES, current_period_end__gt=timezone.now(),
            ).exists()
        return self._subscriber

    def has_app_subscription(self):
        if self._app_subscription is None:
            self._app_subscription = ms.Profile.objects.filter(user=self.viewer, subscriptionActive=True).exists()
        return self._app_subscription

    def can_see(self, kind):
        if self.is_owner:
            return True
        level = level_of(self.profile, kind)
        if level == PUBLIC:
            return True
        if level == SUBSCRIBERS:
            return self.is_subscriber() or (kind in APP_SUBSCRIPTION_KINDS and self.has_app_subscription())
        return False


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


def _row(kind, key, created_at, **data):
    return created_at, {"id": f"{kind}-{key}", "kind": kind, "created_at": created_at, **data}


def _task_rows(kind, queryset, task_of=lambda item: item.task, **extra):
    return queryset.count(), [
        _row(kind, item.pk, item.created_at, task=_task_data(task_of(item)),
             **{name: getter(item) for name, getter in extra.items()})
        for item in queryset[:ACTIVITY_LIMIT]
    ]


def _likes(owner, request, is_owner):
    likes = ms.Like.objects.filter(
        user=owner, is_hidden=False, task__in=_visible_tasks(request.user),
    ).select_related("task__user").order_by("-created_at")
    return _task_rows("likes", likes)


def _comments(owner, request, is_owner):
    task_comments = ms.NewPeticionCommentPost.objects.filter(
        created_by=owner, post__in=_visible_tasks(request.user),
    ).select_related("post__user").order_by("-created_at")
    forum_replies = ms.Postt.objects.filter(
        user=owner, parent__isnull=False,
    ).select_related("parent__parent__parent").order_by("-created_at")
    # Solo respuestas en posts que quien mira puede ver (foro privado).
    roots_visible = {}
    visible_replies = []
    for reply in forum_replies[: ACTIVITY_LIMIT * 3]:
        root = reply
        while root.parent_id:
            root = root.parent
        if root.pk not in roots_visible:
            roots_visible[root.pk] = can_view_post(root, request.user)
        if roots_visible[root.pk]:
            visible_replies.append((reply, root))

    rows = [
        _row("comments", f"task-{comment.pk}", comment.created_at,
             where="task", text=comment.text, task=_task_data(comment.post))
        for comment in task_comments[:ACTIVITY_LIMIT]
    ]
    rows += [
        _row("comments", f"forum-{reply.pk}", reply.created_at,
             where="forum", text=reply.content, forum_post={"id": root.pk, "title": root.title})
        for reply, root in visible_replies[:ACTIVITY_LIMIT]
    ]
    return task_comments.count() + len(visible_replies), rows


def _saves(owner, request, is_owner):
    saves = ms.TaskSave.objects.filter(
        user=owner, task__in=_visible_tasks(request.user),
    ).select_related("task__user").order_by("-created_at")
    if not is_owner:
        # Una guardada privada solo la ve su dueño.
        saves = saves.filter(is_private=False)
    return _task_rows("saves", saves)


def _reposts(owner, request, is_owner):
    reposts = ms.Repost.objects.filter(
        user=owner, task__in=_visible_tasks(request.user),
    ).select_related("task__user").order_by("-created_at")
    return _task_rows("reposts", reposts)


def _shares(owner, request, is_owner):
    shares = ms.SharedTask.objects.filter(
        shared_by=owner, task__in=_visible_tasks(request.user),
    ).select_related("task__user").order_by("-created_at")
    return _task_rows("shares", shares, text=lambda share: share.description)


def _follows(owner, request, is_owner):
    follows = ms.Follow.objects.filter(follower=owner).select_related("following").order_by("-created_at")
    return follows.count(), [
        _row("follows", item.pk, item.created_at, user=_user_data(item.following, request))
        for item in follows[:ACTIVITY_LIMIT]
    ]


def _favorites(owner, request, is_owner):
    profiles = ms.pFavorito.objects.filter(user=owner).select_related("perfil").order_by("-created_at")
    tasks = ms.Favorito.objects.filter(
        user=owner, task__in=_visible_tasks(request.user),
    ).select_related("task__user").order_by("-created_at")
    rows = [
        _row("favorites", f"profile-{item.pk}", item.created_at, user=_user_data(item.perfil, request))
        for item in profiles[:ACTIVITY_LIMIT]
    ]
    rows += [
        _row("favorites", f"task-{item.pk}", item.created_at, task=_task_data(item.task))
        for item in tasks[:ACTIVITY_LIMIT]
    ]
    return profiles.count() + tasks.count(), rows


def _recommendations(owner, request, is_owner):
    given = ms.UserRecommendation.objects.filter(recommender=owner).select_related("recommended").order_by("-created_at")
    return given.count(), [
        _row("recommendations", item.pk, item.created_at,
             user=_user_data(item.recommended, request), text=item.comment)
        for item in given[:ACTIVITY_LIMIT]
    ]


def _verifications(owner, request, is_owner):
    given = ms.UserVerification.objects.filter(verifier=owner).select_related("verified").order_by("-created_at")
    received = ms.UserVerification.objects.filter(verified=owner).select_related("verifier").order_by("-created_at")
    rows = [
        _row("verifications", f"given-{item.pk}", item.created_at,
             direction="given", user=_user_data(item.verified, request))
        for item in given[:ACTIVITY_LIMIT]
    ]
    rows += [
        _row("verifications", f"received-{item.pk}", item.created_at,
             direction="received", user=_user_data(item.verifier, request))
        for item in received[:ACTIVITY_LIMIT]
    ]
    return given.count() + received.count(), rows


LOADERS = {
    "likes": _likes,
    "comments": _comments,
    "saves": _saves,
    "reposts": _reposts,
    "shares": _shares,
    "follows": _follows,
    "favorites": _favorites,
    "recommendations": _recommendations,
    "verifications": _verifications,
}


def _settings(profile):
    return {
        "levels": {kind: level_of(profile, kind) for kind in KINDS},
        "feed_public": profile.feed_public,
    }


def _update(request, profile, is_owner):
    """PATCH {kind, level} (o {kind: "feed", public}): el dueño decide quién ve cada tipo."""
    if not is_owner:
        return Response({"detail": "Solo puedes cambiar tu propia actividad."}, status=status.HTTP_403_FORBIDDEN)
    kind = request.data.get("kind")
    if kind == "feed":
        value = request.data.get("public")
        if not isinstance(value, bool):
            return Response({"public": ["Debe ser verdadero o falso."]}, status=status.HTTP_400_BAD_REQUEST)
        profile.feed_public = value
        profile.save(update_fields=["feed_public", "updated_at"])
        return Response({"kind": kind, "public": value, **_settings(profile)})
    if kind not in KINDS:
        return Response(
            {"kind": [f"Debe ser uno de: {', '.join(KINDS + ('feed',))}."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    level = request.data.get("level")
    if level is None and isinstance(request.data.get("public"), bool):
        level = PUBLIC if request.data["public"] else PRIVATE
    if level not in LEVELS:
        return Response({"level": [f"Debe ser uno de: {', '.join(LEVELS)}."]}, status=status.HTTP_400_BAD_REQUEST)
    profile.activity_levels = {**(profile.activity_levels or {}), kind: level}
    profile.save(update_fields=["activity_levels", "updated_at"])
    return Response({"kind": kind, "level": level, **_settings(profile)})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def user_activity(request, user_id):
    """GET ?kind=all|likes|...: esa actividad (lo que su dueño deja ver a quien consulta).
    PATCH {kind, level}: el dueño decide quién ve ese tipo."""
    owner = get_object_or_404(User, pk=user_id)
    profile, _ = ms.Profile.objects.get_or_create(user=owner)
    access = _Access(request.user, owner, profile)
    if request.method == "PATCH":
        return _update(request, profile, access.is_owner)

    kind = request.query_params.get("kind") or ALL
    if kind != ALL and kind not in KINDS:
        return Response(
            {"kind": [f"Debe ser uno de: {', '.join((ALL,) + KINDS)}."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    visible = [name for name in KINDS if access.can_see(name)]
    data = {
        "kind": kind, "is_owner": access.is_owner, "kinds": visible,
        # Lo que está en modo de paga y quien mira aún no puede ver (sale con candado).
        "paid_kinds": [
            name for name in KINDS if name not in visible and level_of(profile, name) == SUBSCRIBERS
        ],
        "hidden": False, "count": 0, "items": [],
    }
    if kind != ALL:
        data["level"] = level_of(profile, kind)
    if access.is_owner:
        # Para que el dueño vea juntos todos sus controles.
        data.update(_settings(profile))
    wanted = visible if kind == ALL else [kind] if kind in visible else []
    if not wanted:
        data["hidden"] = True
        return Response(data)
    rows = []
    for name in wanted:
        count, kind_rows = LOADERS[name](owner, request, access.is_owner)
        data["count"] += count
        rows += kind_rows
    rows.sort(key=lambda row: row[0], reverse=True)
    data["items"] = [item for _, item in rows[:ACTIVITY_LIMIT]]
    return Response(data)
