"""Apoyo monetario a peticiones: un pago único con Stripe Checkout.

Cualquiera que pueda ver la petición la apoya (también quien la creó, incluso
mientras está oculta). El total se muestra en pesos: lo pagado en dólares se
convierte con SUBSCRIPTION_MXN_PER_USD.
"""
import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import PetitionSupport, Subscription
from .notifications import create_notification
from .subscriptions import _api_key, _field, get_or_create_customer

logger = logging.getLogger(__name__)

PETITION_PCH = {"peticion", "peticiones"}
SUPPORT_NOTIFICATION = "petition_support"


def is_petition(task):
    return (task.pch or "").strip().casefold() in PETITION_PCH


def to_mxn_cents(amount_cents, currency):
    if currency == Subscription.CURRENCY_USD:
        return int(amount_cents * Decimal(str(settings.SUBSCRIPTION_MXN_PER_USD)))
    return amount_cents


def support_summary(supports):
    """Total en MXN y personas distintas que apoyaron, a partir de los apoyos pagados."""
    paid = [s for s in supports if s.status == PetitionSupport.STATUS_PAID]
    total_cents = sum(to_mxn_cents(s.amount_cents, s.currency) for s in paid)
    return {
        "amount_mxn": f"{Decimal(total_cents) / 100:.2f}",
        "supporters_count": len({s.supporter_id for s in paid}),
    }


def start_support_checkout(*, supporter, task, amount_cents, currency, success_url, cancel_url):
    """Crea el apoyo pendiente y la sesión de Checkout donde se paga."""
    api_key = _api_key()
    customer_id = get_or_create_customer(supporter)
    local = PetitionSupport.objects.create(
        task=task, supporter=supporter, amount_cents=amount_cents, currency=currency,
    )
    metadata = {"petition_support_id": str(local.pk)}
    try:
        session = stripe.checkout.Session.create(
            api_key=api_key,
            mode="payment",
            customer=customer_id,
            client_reference_id=str(local.pk),
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": currency,
                    "unit_amount": amount_cents,
                    "product_data": {"name": f"Apoyo a la petición «{(task.title or 'Petición')[:80]}»"},
                },
            }],
            metadata=metadata,
            payment_intent_data={"metadata": metadata},
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except Exception:
        local.delete()
        raise
    local.stripe_checkout_session_id = session["id"]
    local.save(update_fields=["stripe_checkout_session_id", "updated_at"])
    return local, session["url"]


def apply_checkout_session(local, session):
    """Copia a `local` el estado de su sesión de Checkout."""
    with transaction.atomic():
        local = PetitionSupport.objects.select_for_update().select_related("task", "supporter").get(pk=local.pk)
        if local.status == PetitionSupport.STATUS_PAID:
            return local
        if _field(session, "payment_status") in ("paid", "no_payment_required"):
            local.status = PetitionSupport.STATUS_PAID
            local.paid_at = timezone.now()
        elif _field(session, "status") == "expired":
            local.status = PetitionSupport.STATUS_EXPIRED
        else:
            return local
        local.save(update_fields=["status", "paid_at", "updated_at"])

    if local.status == PetitionSupport.STATUS_PAID:
        create_notification(
            recipient=local.task.user,
            actor=local.supporter,
            notification_type=SUPPORT_NOTIFICATION,
            target_type="task",
            target_id=local.task_id,
            data={"amount": f"{Decimal(local.amount_cents) / 100:.2f}", "currency": local.currency},
            dedupe_key=f"{SUPPORT_NOTIFICATION}:{local.pk}",
        )
    return local


def sync_support(local):
    """Lee la sesión de Stripe, por si el webhook no ha llegado (o no hay)."""
    if local.status != PetitionSupport.STATUS_PENDING or not local.stripe_checkout_session_id:
        return local
    session = stripe.checkout.Session.retrieve(local.stripe_checkout_session_id, api_key=_api_key())
    return apply_checkout_session(local, session)


def handle_support_event(event):
    """Procesa eventos de Checkout de apoyos. Devuelve el apoyo tocado, si hay."""
    if event["type"] not in (
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.expired",
    ):
        return None
    session = event["data"]["object"]
    if _field(session, "mode") != "payment":
        return None
    local_id = _field(_field(session, "metadata") or {}, "petition_support_id") or _field(session, "client_reference_id")
    local = PetitionSupport.objects.filter(pk=local_id).first() if local_id else None
    if not local:
        local = PetitionSupport.objects.filter(stripe_checkout_session_id=_field(session, "id") or "").first()
    if not local:
        logger.info("Evento %s sin apoyo local (%s)", event["type"], _field(session, "id"))
        return None
    return apply_checkout_session(local, session)
