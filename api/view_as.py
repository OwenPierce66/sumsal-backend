"""Ver como otra persona: su feed, si lo permite.

Su feed es lo que publican (o comparten) las personas que sigue; sus perfiles favoritos ya
están ahí porque favoritar a alguien también lo sigue. Siempre con los permisos de quien
mira: nunca aparece algo que a él no le dejarían ver. Cada quien lo permite con
`Profile.feed_public` (apagado al inicio).
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound, PermissionDenied

from . import models as ms

User = get_user_model()

AS_USER_PARAM = "as_user"


def can_view_feed_of(viewer, owner):
    if viewer is not None and viewer.is_authenticated and viewer.pk == owner.pk:
        return True
    profile = ms.Profile.objects.filter(user=owner).only("feed_public").first()
    return bool(profile and profile.feed_public)


def feed_owner(params, viewer):
    """La persona como la que se ve el feed (?as_user=), o None. Error si no lo permite."""
    raw = str(params.get(AS_USER_PARAM) or "").strip()
    if not raw:
        return None
    if viewer is None or not viewer.is_authenticated:
        raise PermissionDenied("Inicia sesión para ver el feed de otra persona.")
    try:
        owner = User.objects.filter(pk=raw).first()
    except (ValueError, ValidationError):
        owner = None
    if owner is None:
        raise NotFound("Ese perfil no existe.")
    if not can_view_feed_of(viewer, owner):
        raise PermissionDenied("Esta persona no permite ver su feed.")
    return owner


def followed_ids(owner):
    return ms.Follow.objects.filter(follower=owner).values("following_id")
