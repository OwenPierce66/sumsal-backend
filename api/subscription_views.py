import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Profile, Subscription
from .petition_supports import handle_support_event
from .subscription_serializers import CheckoutRequestSerializer, SubscriptionSerializer
from .subscriptions import (
    SubscriptionsUnavailable,
    active_received,
    handle_webhook_event,
    refresh_profile_subscription,
    set_auto_renew,
    start_checkout,
    stripe_configured,
    sync_from_stripe,
    tier_for,
    to_usd,
)

logger = logging.getLogger(__name__)
User = get_user_model()

_UNAVAILABLE = {"detail": "Las suscripciones no están disponibles por ahora."}
_STRIPE_FAILED = {"detail": "No pudimos comunicarnos con Stripe. Intenta de nuevo en un momento."}


def _summary(user_id):
    subs = list(active_received(user_id))
    total = sum((to_usd(s.amount_cents, s.currency) for s in subs), Decimal("0.00"))
    # Si una suscripción venció sin que llegara el webhook, la insignia se corrige aquí.
    profile = Profile.objects.filter(user_id=user_id).only("subscriptionActive", "subscription_amount").first()
    if profile and (profile.subscriptionActive != bool(subs) or profile.subscription_amount != total):
        refresh_profile_subscription(user_id)
    return {
        "active": bool(subs),
        "amount_usd": f"{total:.2f}",
        "tier": tier_for(bool(subs), total),
        "subscribers_count": len({s.subscriber_id for s in subs}),
    }


def _own_subscription(request, pk):
    return get_object_or_404(
        Subscription.objects.select_related("subscriber", "recipient"),
        pk=pk,
        subscriber=request.user,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def subscription_checkout(request):
    if not stripe_configured():
        return Response(_UNAVAILABLE, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    serializer = CheckoutRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    recipient = get_object_or_404(User, pk=data.get("recipient_id") or request.user.pk, is_active=True)

    already = Subscription.objects.filter(
        subscriber=request.user,
        recipient=recipient,
        status__in=Subscription.ACTIVE_STATUSES,
        current_period_end__gt=timezone.now(),
    ).exists()
    if already:
        return Response(
            {"detail": "Ya pagas una suscripción activa para este perfil. Puedes manejarla en Mis suscripciones."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    done_url = request.build_absolute_uri(reverse("subscription-checkout-done"))
    try:
        local, checkout_url = start_checkout(
            subscriber=request.user,
            recipient=recipient,
            amount_cents=data["amount_cents"],
            currency=data["currency"],
            auto_renew=data["auto_renew"],
            success_url=f"{done_url}?result=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{done_url}?result=cancel",
        )
    except stripe.StripeError:
        logger.exception("Stripe rechazó la sesión de Checkout")
        return Response(_STRIPE_FAILED, status=status.HTTP_502_BAD_GATEWAY)

    return Response(
        {"subscription": SubscriptionSerializer(local).data, "checkout_url": checkout_url},
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_subscriptions(request):
    subs = Subscription.objects.select_related("subscriber", "recipient").exclude(
        status=Subscription.STATUS_PENDING,
    )
    paid = subs.filter(subscriber=request.user)[:50]
    received = subs.filter(
        recipient=request.user,
        status__in=Subscription.ACTIVE_STATUSES,
        current_period_end__gt=timezone.now(),
    )
    return Response({
        "paid": SubscriptionSerializer(paid, many=True).data,
        "received": SubscriptionSerializer(received, many=True).data,
        "summary": _summary(request.user.pk),
        "stripe_enabled": stripe_configured(),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_subscriptions(request, user_id):
    """Suscripciones de otro perfil, solo lectura: las activas que recibe (lo que ya suma
    su insignia) y las que regala a otros perfiles (que se ven en el perfil de quien las recibe)."""
    user = get_object_or_404(User, pk=user_id, is_active=True)
    active = Subscription.objects.select_related("subscriber", "recipient").filter(
        status__in=Subscription.ACTIVE_STATUSES,
        current_period_end__gt=timezone.now(),
    )
    return Response({
        "user": {"id": str(user.pk), "username": user.username},
        "paid": SubscriptionSerializer(active.filter(subscriber=user).exclude(recipient=user), many=True).data,
        "received": SubscriptionSerializer(active.filter(recipient=user), many=True).data,
        "summary": _summary(user.pk),
        "stripe_enabled": stripe_configured(),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def subscription_status(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    mine = (
        Subscription.objects.select_related("subscriber", "recipient")
        .filter(
            subscriber=request.user,
            recipient=user,
            status__in=Subscription.ACTIVE_STATUSES,
            current_period_end__gt=timezone.now(),
        )
        .first()
    )
    return Response({
        "user_id": str(user.pk),
        **_summary(user.pk),
        "my_subscription": SubscriptionSerializer(mine).data if mine else None,
        "stripe_enabled": stripe_configured(),
    })


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def subscription_detail(request, pk):
    local = _own_subscription(request, pk)
    auto_renew = request.data.get("auto_renew")
    if not isinstance(auto_renew, bool):
        return Response({"auto_renew": ["Debe ser true o false."]}, status=status.HTTP_400_BAD_REQUEST)
    if not local.is_active:
        return Response({"detail": "Esta suscripción ya terminó."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        local = set_auto_renew(local, auto_renew)
    except SubscriptionsUnavailable:
        return Response(_UNAVAILABLE, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except stripe.StripeError:
        logger.exception("Stripe rechazó el cambio de renovación de %s", local.pk)
        return Response(_STRIPE_FAILED, status=status.HTTP_502_BAD_GATEWAY)
    return Response(SubscriptionSerializer(local).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def subscription_sync(request, pk):
    local = _own_subscription(request, pk)
    try:
        local = sync_from_stripe(local)
    except SubscriptionsUnavailable:
        return Response(_UNAVAILABLE, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except stripe.StripeError:
        logger.exception("No se pudo sincronizar %s con Stripe", local.pk)
        return Response(_STRIPE_FAILED, status=status.HTTP_502_BAD_GATEWAY)
    return Response(SubscriptionSerializer(local).data)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    if not settings.STRIPE_WEBHOOK_SECRET or not stripe_configured():
        return HttpResponse(status=503)
    try:
        event = stripe.Webhook.construct_event(
            request.body, request.headers.get("Stripe-Signature", ""), settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)
    try:
        # Las suscripciones y los apoyos a peticiones comparten el endpoint.
        handle_webhook_event(event)
        handle_support_event(event)
    except stripe.StripeError:
        # Stripe reintenta los webhooks que no responden 2xx.
        logger.exception("Falló el webhook %s", event["type"])
        return HttpResponse(status=500)
    return HttpResponse(status=200)


_DONE_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;min-height:100vh;display:flex;align-items:center;
justify-content:center;background:#f8f9fa;color:#212529;text-align:center;padding:24px}}
h1{{font-size:22px}}p{{color:#495057}}</style></head>
<body><main><h1>{title}</h1><p>{message}</p></main></body></html>"""


@require_GET
def subscription_checkout_done(request):
    """A donde regresa Stripe Checkout. Confirma el pago sin esperar al webhook."""
    if request.GET.get("result") != "success":
        return HttpResponse(_DONE_PAGE.format(
            title="Pago cancelado",
            message="No se hizo ningún cargo. Puedes cerrar esta ventana y volver a la app.",
        ))

    session_id = request.GET.get("session_id", "")
    local = Subscription.objects.filter(stripe_checkout_session_id=session_id).first() if session_id else None
    if local and stripe_configured():
        try:
            sync_from_stripe(local)
        except stripe.StripeError:
            logger.exception("No se pudo confirmar el pago de %s", local.pk)
    return HttpResponse(_DONE_PAGE.format(
        title="¡Suscripción lista!",
        message="Gracias por tu apoyo. Ya puedes cerrar esta ventana y volver a la app.",
    ))
