"""Suscripciones mensuales con Stripe Checkout.

Quien paga elige el monto (mínimo 10 MXN o 1 USD), si es para sí o para otro
perfil y si se renueva sola. Stripe es la fuente de verdad: los webhooks y
`sync_from_stripe` vuelven a leer la suscripción de Stripe y la copian aquí.
"""
import logging
from datetime import datetime, timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Profile, Subscription
from .notifications import create_notification

logger = logging.getLogger(__name__)

# 10 MXN es el cobro mínimo que Stripe acepta en pesos.
MIN_AMOUNT_CENTS = {Subscription.CURRENCY_MXN: 1000, Subscription.CURRENCY_USD: 100}
# Tope para atrapar errores de dedo (un cero de más), no un límite de negocio.
MAX_AMOUNT_CENTS = {Subscription.CURRENCY_MXN: 2_000_000, Subscription.CURRENCY_USD: 100_000}
# Mismo umbral que la web antigua para la insignia "Suscripción +".
SUB_PLUS_THRESHOLD_USD = Decimal("8")
GIFT_NOTIFICATION = "subscription_gift"


class SubscriptionsUnavailable(Exception):
    """Stripe no está configurado en este backend."""


def stripe_configured():
    return bool(settings.STRIPE_SECRET_KEY)


def _api_key():
    if not stripe_configured():
        raise SubscriptionsUnavailable()
    return settings.STRIPE_SECRET_KEY


def _field(obj, key):
    """Lee una clave de un objeto de Stripe (o de un dict) sin romper si falta."""
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        return None


def to_usd(amount_cents, currency):
    amount = Decimal(amount_cents) / 100
    if currency == Subscription.CURRENCY_MXN:
        amount /= Decimal(settings.SUBSCRIPTION_MXN_PER_USD)
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def tier_for(active, amount_usd):
    if not active:
        return None
    return "sub_red" if amount_usd >= SUB_PLUS_THRESHOLD_USD else "sub_green"


def active_received(user_id):
    return Subscription.objects.filter(
        recipient_id=user_id,
        status__in=Subscription.ACTIVE_STATUSES,
        current_period_end__gt=timezone.now(),
    )


def refresh_profile_subscription(user_id):
    """Recalcula la insignia del perfil: suma, en USD, lo que recibe al mes."""
    subs = list(active_received(user_id).only("amount_cents", "currency"))
    total = sum((to_usd(s.amount_cents, s.currency) for s in subs), Decimal("0.00"))
    Profile.objects.filter(user_id=user_id).update(
        subscriptionActive=bool(subs), subscription_amount=total,
    )
    return bool(subs), total


def get_or_create_customer(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    if profile.stripe_customer_id:
        return profile.stripe_customer_id
    customer = stripe.Customer.create(
        api_key=_api_key(),
        email=user.email,
        name=user.username or user.email,
        metadata={"user_id": str(user.pk)},
    )
    profile.stripe_customer_id = customer["id"]
    profile.save(update_fields=["stripe_customer_id"])
    return profile.stripe_customer_id


def start_checkout(*, subscriber, recipient, amount_cents, currency, auto_renew, success_url, cancel_url):
    """Crea la suscripción pendiente y la sesión de Checkout donde se paga."""
    api_key = _api_key()
    customer_id = get_or_create_customer(subscriber)
    local = Subscription.objects.create(
        subscriber=subscriber,
        recipient=recipient,
        amount_cents=amount_cents,
        currency=currency,
        auto_renew=auto_renew,
    )
    metadata = {"subscription_id": str(local.pk)}
    name = (
        "Tu suscripción mensual"
        if subscriber.pk == recipient.pk
        else f"Suscripción para @{recipient.username or recipient.email}"
    )
    try:
        session = stripe.checkout.Session.create(
            api_key=api_key,
            mode="subscription",
            customer=customer_id,
            client_reference_id=str(local.pk),
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": currency,
                    "unit_amount": amount_cents,
                    "recurring": {"interval": "month"},
                    "product_data": {"name": name},
                },
            }],
            metadata=metadata,
            subscription_data={"metadata": metadata},
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except Exception:
        local.delete()
        raise
    local.stripe_checkout_session_id = session["id"]
    local.save(update_fields=["stripe_checkout_session_id", "updated_at"])
    return local, session["url"]


def _period_end(stripe_sub):
    # Desde la API 2025-03-31 el periodo vive en cada item, no en la suscripción.
    items = _field(_field(stripe_sub, "items"), "data") or []
    ts = _field(items[0], "current_period_end") if items else None
    ts = ts or _field(stripe_sub, "current_period_end")
    return datetime.fromtimestamp(ts, tz=dt_timezone.utc) if ts else None


def _renews(stripe_sub):
    return not (_field(stripe_sub, "cancel_at_period_end") or _field(stripe_sub, "cancel_at"))


def apply_stripe_subscription(local, stripe_sub):
    """Copia a `local` el estado de la suscripción de Stripe."""
    with transaction.atomic():
        local = Subscription.objects.select_for_update().get(pk=local.pk)
        was_active = local.is_active
        first_link = not local.stripe_subscription_id
        local.stripe_subscription_id = stripe_sub["id"]

        # Checkout no deja crear la suscripción sin renovación: se ajusta al enlazarla.
        if first_link and not local.auto_renew and _renews(stripe_sub):
            stripe_sub = stripe.Subscription.modify(
                stripe_sub["id"], api_key=_api_key(), cancel_at_period_end=True,
            )

        local.status = _field(stripe_sub, "status") or local.status
        local.current_period_end = _period_end(stripe_sub) or local.current_period_end
        local.auto_renew = _renews(stripe_sub)
        local.save()

    refresh_profile_subscription(local.recipient_id)
    if local.is_active and not was_active and local.subscriber_id != local.recipient_id:
        create_notification(
            recipient=local.recipient,
            actor=local.subscriber,
            notification_type=GIFT_NOTIFICATION,
            target_type="profile",
            target_id=local.subscriber_id,
            data={"amount": str(Decimal(local.amount_cents) / 100), "currency": local.currency},
            dedupe_key=f"{GIFT_NOTIFICATION}:{local.pk}",
        )
    return local


def _retrieve_subscription(stripe_subscription_id):
    return stripe.Subscription.retrieve(stripe_subscription_id, api_key=_api_key())


def sync_from_stripe(local):
    """Lee de Stripe el estado actual, por si el webhook no ha llegado (o no hay)."""
    stripe_subscription_id = local.stripe_subscription_id
    if not stripe_subscription_id and local.stripe_checkout_session_id:
        session = stripe.checkout.Session.retrieve(local.stripe_checkout_session_id, api_key=_api_key())
        stripe_subscription_id = _field(session, "subscription")
        if not isinstance(stripe_subscription_id, (str, type(None))):
            stripe_subscription_id = stripe_subscription_id["id"]
    if not stripe_subscription_id:
        return local
    return apply_stripe_subscription(local, _retrieve_subscription(stripe_subscription_id))


def set_auto_renew(local, auto_renew):
    if not local.stripe_subscription_id:
        raise ValueError("La suscripción todavía no está pagada.")
    stripe_sub = stripe.Subscription.modify(
        local.stripe_subscription_id,
        api_key=_api_key(),
        cancel_at_period_end=not auto_renew,
        # Si se había programado una fecha de cancelación desde Stripe, se quita al renovar.
        **({"cancel_at": ""} if auto_renew else {}),
    )
    return apply_stripe_subscription(local, stripe_sub)


def _local_for(stripe_obj, stripe_subscription_id=None):
    metadata = _field(stripe_obj, "metadata") or {}
    local_id = _field(metadata, "subscription_id") or _field(stripe_obj, "client_reference_id")
    if local_id:
        local = Subscription.objects.filter(pk=local_id).first()
        if local:
            return local
    if stripe_subscription_id:
        return Subscription.objects.filter(stripe_subscription_id=stripe_subscription_id).first()
    return None


def handle_webhook_event(event):
    """Procesa un evento ya verificado. Devuelve la suscripción local tocada, si hay."""
    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        if _field(obj, "mode") != "subscription":
            return None
        stripe_subscription_id = _field(obj, "subscription")
    elif event_type.startswith("customer.subscription."):
        stripe_subscription_id = obj["id"]
    else:
        return None

    local = _local_for(obj, stripe_subscription_id)
    if not local or not stripe_subscription_id:
        logger.info("Evento %s sin suscripción local (%s)", event_type, stripe_subscription_id)
        return None
    # Se relee de Stripe: los eventos pueden llegar desordenados.
    return apply_stripe_subscription(local, _retrieve_subscription(stripe_subscription_id))
