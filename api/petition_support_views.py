import logging
from collections import defaultdict
from decimal import Decimal

import stripe
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PetitionSupport
from .petition_supports import is_petition, start_support_checkout, support_summary, sync_support, to_mxn_cents
from .serializers import ProfileSerializer, file_to_abs_url
from .subscription_serializers import PetitionSupportRequestSerializer, PetitionSupportSerializer
from .subscription_views import _DONE_PAGE, _STRIPE_FAILED, _UNAVAILABLE
from .subscriptions import SubscriptionsUnavailable, stripe_configured
from .views import visible_tasks_for

logger = logging.getLogger(__name__)
User = get_user_model()

_NOT_PETITION = {"detail": "Solo las peticiones se pueden apoyar monetariamente."}


def _petition_for(request, task_id):
    task = get_object_or_404(visible_tasks_for(request.user).select_related("user"), id=task_id)
    return task if is_petition(task) else None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def petition_support_checkout(request, task_id):
    task = _petition_for(request, task_id)
    if task is None:
        return Response(_NOT_PETITION, status=status.HTTP_400_BAD_REQUEST)
    if not stripe_configured():
        return Response(_UNAVAILABLE, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    serializer = PetitionSupportRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    done_url = request.build_absolute_uri(reverse("petition-support-checkout-done"))
    try:
        local, checkout_url = start_support_checkout(
            supporter=request.user,
            task=task,
            amount_cents=data["amount_cents"],
            currency=data["currency"],
            success_url=f"{done_url}?result=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{done_url}?result=cancel",
        )
    except stripe.StripeError:
        logger.exception("Stripe rechazó la sesión de Checkout del apoyo")
        return Response(_STRIPE_FAILED, status=status.HTTP_502_BAD_GATEWAY)

    return Response(
        {"support": PetitionSupportSerializer(local).data, "checkout_url": checkout_url},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def petition_support_sync(request, pk):
    local = get_object_or_404(PetitionSupport, pk=pk, supporter=request.user)
    try:
        local = sync_support(local)
    except SubscriptionsUnavailable:
        return Response(_UNAVAILABLE, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except stripe.StripeError:
        logger.exception("No se pudo sincronizar el apoyo %s con Stripe", local.pk)
        return Response(_STRIPE_FAILED, status=status.HTTP_502_BAD_GATEWAY)
    return Response({
        "support": PetitionSupportSerializer(local).data,
        "support_total": support_summary(local.task.petition_supports.all()),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def petition_supporters(request, task_id):
    """Quién apoyó la petición y cuánto (en MXN), de mayor a menor."""
    task = _petition_for(request, task_id)
    if task is None:
        return Response(_NOT_PETITION, status=status.HTTP_400_BAD_REQUEST)
    supports = list(
        task.petition_supports.filter(status=PetitionSupport.STATUS_PAID)
        .select_related("supporter__profile")
        .prefetch_related("supporter__fixed_images")
    )
    totals = defaultdict(int)
    users = {}
    for support in supports:
        totals[support.supporter_id] += to_mxn_cents(support.amount_cents, support.currency)
        users[support.supporter_id] = support.supporter

    out = []
    for user_id, cents in sorted(totals.items(), key=lambda item: -item[1]):
        user = users[user_id]
        images = list(user.fixed_images.all())
        latest = max(images, key=lambda img: img.id).image if images else None
        profile = getattr(user, "profile", None)
        out.append({
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "amount_mxn": f"{Decimal(cents) / 100:.2f}",
            "user_image": file_to_abs_url(latest, request),
            "profile": ProfileSerializer(profile).data if profile else None,
        })
    return Response({"supporters": out, "support_total": support_summary(supports)})


@require_GET
def petition_support_checkout_done(request):
    """A donde regresa Stripe Checkout. Confirma el pago sin esperar al webhook."""
    if request.GET.get("result") != "success":
        return HttpResponse(_DONE_PAGE.format(
            title="Pago cancelado",
            message="No se hizo ningún cargo. Puedes cerrar esta ventana y volver a la app.",
        ))
    session_id = request.GET.get("session_id", "")
    local = PetitionSupport.objects.filter(stripe_checkout_session_id=session_id).first() if session_id else None
    if local and stripe_configured():
        try:
            sync_support(local)
        except stripe.StripeError:
            logger.exception("No se pudo confirmar el apoyo %s", local.pk)
    return HttpResponse(_DONE_PAGE.format(
        title="¡Gracias por tu apoyo!",
        message="Tu aportación a la petición quedó registrada. Ya puedes cerrar esta ventana y volver a la app.",
    ))


def _task_info(task):
    return {
        "id": str(task.id),
        "title": task.title,
        "is_hidden": task.is_hidden,
        "user": {"id": str(task.user_id), "username": task.user.username},
    }


def _supports_of(user, viewer):
    """Las peticiones que `user` apoyó y lo que recibieron las suyas, en MXN, por petición.

    `viewer` no ve las peticiones ocultas de otras personas (las suyas sí).
    """
    paid = (
        PetitionSupport.objects.filter(status=PetitionSupport.STATUS_PAID)
        .filter(Q(task__is_hidden=False) | Q(task__user=viewer))
        .select_related("task__user")
    )

    given = {}
    for support in paid.filter(supporter=user).order_by("-paid_at", "-created_at"):
        row = given.setdefault(support.task_id, {
            "task": _task_info(support.task), "cents": 0, "times": 0,
            "last_paid_at": support.paid_at or support.created_at,
        })
        row["cents"] += to_mxn_cents(support.amount_cents, support.currency)
        row["times"] += 1

    received = {}
    for support in paid.filter(task__user=user).order_by("-paid_at", "-created_at"):
        row = received.setdefault(support.task_id, {
            "task": _task_info(support.task), "cents": 0, "supporters": set(),
            "last_paid_at": support.paid_at or support.created_at,
        })
        row["cents"] += to_mxn_cents(support.amount_cents, support.currency)
        row["supporters"].add(support.supporter_id)

    def money(cents):
        return f"{Decimal(cents) / 100:.2f}"

    return {
        "given": [
            {"task": r["task"], "amount_mxn": money(r["cents"]), "times": r["times"], "last_paid_at": r["last_paid_at"]}
            for r in given.values()
        ],
        "received": [
            {"task": r["task"], "amount_mxn": money(r["cents"]), "supporters_count": len(r["supporters"]),
             "last_paid_at": r["last_paid_at"]}
            for r in received.values()
        ],
        "summary": {
            "given_mxn": money(sum(r["cents"] for r in given.values())),
            "received_mxn": money(sum(r["cents"] for r in received.values())),
        },
        "stripe_enabled": stripe_configured(),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_petition_supports(request):
    """Mis apoyos: las peticiones que apoyé y lo que recibieron las mías."""
    return Response(_supports_of(request.user, request.user))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_petition_supports(request, user_id):
    """Apoyos de otro perfil. Es público: cada petición ya muestra quién la apoyó y cuánto."""
    user = get_object_or_404(User, pk=user_id, is_active=True)
    return Response({"user": {"id": str(user.pk), "username": user.username}, **_supports_of(user, request.user)})
