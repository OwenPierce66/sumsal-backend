"""Visitas al perfil.

- Cada vez que alguien abre un perfil ajeno se registra (una fila por visitante y día).
- Su dueño ve gratis cuántas visitas tuvo (últimos 7 y 30 días); quién lo visitó, solo con
  suscripción en la app (`Profile.subscriptionActive`).
- Quien visita en modo anónimo (`Profile.anonymous_visits`) cuenta, pero no aparece.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import models as ms

User = get_user_model()

WINDOW_DAYS = 30
VISITORS_LIMIT = 50


def _recent(owner, days):
    return ms.ProfileVisit.objects.filter(owner=owner, day__gt=timezone.localdate() - timedelta(days=days))


def visit_counts(owner):
    """Visitas (una por visitante y día) en los últimos 7 y 30 días."""
    return {"visits_7d": _recent(owner, 7).count(), "visits_30d": _recent(owner, WINDOW_DAYS).count()}


def _visitors(owner, request):
    from .serializers import SimpleUserSerializer

    visitors = {}
    for row in _recent(owner, WINDOW_DAYS).select_related("visitor").order_by("-last_visited_at")[:500]:
        # Cada visita anónima va aparte y sin decir quién fue.
        key = f"anonymous-{row.pk}" if row.anonymous else str(row.visitor_id)
        if key in visitors:
            visitors[key]["visits"] += row.visits
            continue
        visitors[key] = {
            "id": key,
            "anonymous": row.anonymous,
            "user": None if row.anonymous else SimpleUserSerializer(row.visitor, context={"request": request}).data,
            "last_visited_at": row.last_visited_at,
            "visits": row.visits,
        }
    return list(visitors.values())[:VISITORS_LIMIT]


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def record_profile_visit(request, user_id):
    """Quien consulta abrió el perfil de `user_id` (el propio no cuenta)."""
    owner = get_object_or_404(User, pk=user_id)
    if owner.pk == request.user.pk:
        return Response({"recorded": False})
    anonymous = ms.Profile.objects.filter(user=request.user, anonymous_visits=True).exists()
    now = timezone.now()
    visit, created = ms.ProfileVisit.objects.get_or_create(
        owner=owner, visitor=request.user, day=timezone.localdate(),
        defaults={"last_visited_at": now, "anonymous": anonymous},
    )
    if not created:
        ms.ProfileVisit.objects.filter(pk=visit.pk).update(
            visits=F("visits") + 1, last_visited_at=now, anonymous=anonymous,
        )
    return Response({"recorded": True})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def profile_visits(request, user_id):
    """GET: las visitas de tu perfil. PATCH {anonymous_visits}: visitar en modo anónimo."""
    owner = get_object_or_404(User, pk=user_id)
    if owner.pk != request.user.pk:
        return Response({"detail": "Solo puedes ver las visitas de tu perfil."}, status=status.HTTP_403_FORBIDDEN)
    profile, _ = ms.Profile.objects.get_or_create(user=owner)
    if request.method == "PATCH":
        value = request.data.get("anonymous_visits")
        if not isinstance(value, bool):
            return Response({"anonymous_visits": ["Debe ser verdadero o falso."]}, status=status.HTTP_400_BAD_REQUEST)
        profile.anonymous_visits = value
        profile.save(update_fields=["anonymous_visits", "updated_at"])

    can_see_visitors = bool(profile.subscriptionActive)
    return Response({
        **visit_counts(owner),
        "anonymous_visits": profile.anonymous_visits,
        "can_see_visitors": can_see_visitors,
        "visitors": _visitors(owner, request) if can_see_visitors else [],
    })
