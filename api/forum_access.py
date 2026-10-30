"""Quién puede ver un post del foro (y sus respuestas, que heredan lo del post).

- Foro de un grupo (`Postt.group`): si el grupo es privado, solo sus integrantes.
- Visibilidad del post (`Postt.visibility`):
  - public: todos (los que pueden ver ese foro).
  - followers: quienes siguen al autor.
  - subscribers: quienes tienen una suscripción de pago activa al autor.
  - invited: solo las personas invitadas (`invited_users`).
El autor y el staff siempre lo ven.
"""
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from . import models as ms


def _is_staff(user):
    return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))


def visible_forum_posts(queryset, user):
    """Filtra posts del foro (raíz) a los que `user` tiene acceso."""
    if _is_staff(user):
        return queryset
    if not getattr(user, "is_authenticated", False):
        return queryset.filter(visibility=ms.Postt.VISIBILITY_PUBLIC).filter(
            Q(group__isnull=True) | Q(group__is_private=False)
        )
    author = OuterRef("user")
    follows = Exists(ms.Follow.objects.filter(follower=user, following=author))
    subscribed = Exists(ms.Subscription.objects.filter(
        subscriber=user, recipient=author,
        status__in=ms.Subscription.ACTIVE_STATUSES, current_period_end__gt=timezone.now(),
    ))
    invited = Exists(ms.Postt.invited_users.through.objects.filter(postt=OuterRef("pk"), user=user))
    member = Exists(ms.CommunityGroupMember.objects.filter(
        group=OuterRef("group"), user=user, status=ms.CommunityGroupMember.STATUS_ACTIVE,
    ))
    by_visibility = (
        Q(visibility=ms.Postt.VISIBILITY_PUBLIC)
        | (Q(visibility=ms.Postt.VISIBILITY_FOLLOWERS) & Q(follows))
        | (Q(visibility=ms.Postt.VISIBILITY_SUBSCRIBERS) & Q(subscribed))
        | (Q(visibility=ms.Postt.VISIBILITY_INVITED) & Q(invited))
    )
    by_group = Q(group__isnull=True) | Q(group__is_private=False) | Q(member)
    return queryset.filter(Q(user=user) | (by_visibility & by_group))


def forum_root(post):
    while post.parent_id:
        post = post.parent
    return post


def can_view_post(post, user):
    """¿`user` puede ver este post o respuesta? Se decide por el post raíz."""
    root = forum_root(post)
    return visible_forum_posts(ms.Postt.objects.filter(pk=root.pk), user).exists()
