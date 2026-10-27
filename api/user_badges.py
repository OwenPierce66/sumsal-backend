"""Insignias que la app muestra junto al nombre de cada persona.

Son las mismas categorías de la web antigua (App, recomendado, verificado y
suscripción, con "Suscripción +" desde 8 USD al mes) más la de administración.
La app las pide en lote para todos los nombres que hay en pantalla.
"""
from uuid import UUID

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .app_account import app_account_email
from .subscriptions import tier_for

MAX_IDS = 100


def badges_for(user, app_email=""):
    """Claves de insignia en el orden en que se muestran."""
    badges = []
    if app_email and (user.email or "").lower() == app_email.lower():
        badges.append("app")
    if user.is_staff or user.is_superuser:
        badges.append("admin")
    profile = getattr(user, "profile", None)
    if profile is not None:
        if profile.is_recommended:
            badges.append("recommended")
        if profile.is_verified:
            badges.append("verified")
        tier = tier_for(profile.subscriptionActive, profile.subscription_amount)
        if tier:
            badges.append(tier)
    return badges


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_badges(request):
    """GET users/badges/?ids=<uuid>,<uuid>... → {"<uuid>": ["verified", "sub_red"], ...}"""
    ids = []
    for raw in request.query_params.get("ids", "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ids.append(UUID(raw))
        except ValueError:
            return Response({"ids": [f"Id inválido: {raw[:40]}"]}, status=status.HTTP_400_BAD_REQUEST)
    if len(ids) > MAX_IDS:
        return Response({"ids": [f"Máximo {MAX_IDS} ids por petición."]}, status=status.HTTP_400_BAD_REQUEST)

    users = (
        get_user_model().objects.filter(pk__in=ids)
        .select_related("profile")
        .only(
            "id", "email", "is_staff", "is_superuser",
            "profile__is_recommended", "profile__is_verified",
            "profile__subscriptionActive", "profile__subscription_amount",
        )
    )
    app_email = app_account_email()
    return Response({str(user.pk): badges_for(user, app_email) for user in users})
