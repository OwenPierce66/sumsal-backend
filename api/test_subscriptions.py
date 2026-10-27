import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()

WEBHOOK_SECRET = "whsec_test_secret"


def stripe_sub(sub_id="sub_1", status="active", days=30, cancel_at_period_end=False, metadata=None):
    """Suscripción de Stripe con la forma de la API 2026 (periodo dentro de cada item)."""
    period_end = int((timezone.now() + timedelta(days=days)).timestamp())
    return {
        "id": sub_id,
        "object": "subscription",
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "cancel_at": None,
        "metadata": metadata or {},
        "items": {"object": "list", "data": [{"id": "si_1", "current_period_end": period_end}]},
    }


def signed_webhook(client, event):
    payload = json.dumps(event)
    timestamp = int(time.time())
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256,
    ).hexdigest()
    return client.post(
        reverse("subscription-webhook"),
        data=payload,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=f"t={timestamp},v1={signature}",
    )


@override_settings(
    STRIPE_SECRET_KEY="sk_test_x",
    STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    SUBSCRIPTION_MXN_PER_USD="16",
)
class SubscriptionTests(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x", username="ana")
        self.luis = User.objects.create_user(email="luis@example.com", password="x", username="luis")
        self.client = APIClient()
        self.client.force_authenticate(self.ana)

        patcher = mock.patch("api.subscriptions.stripe")
        self.stripe = patcher.start()
        self.addCleanup(patcher.stop)
        self.stripe.Customer.create.return_value = {"id": "cus_ana"}
        self.stripe.checkout.Session.create.return_value = {"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"}

    def checkout(self, **body):
        body.setdefault("amount", "16")
        body.setdefault("currency", "mxn")
        return self.client.post(reverse("subscription-checkout"), body, format="json")

    def active_subscription(self, subscriber, recipient, cents, currency, days=30, sub_id="sub_x"):
        return ms.Subscription.objects.create(
            subscriber=subscriber, recipient=recipient, amount_cents=cents, currency=currency,
            status="active", current_period_end=timezone.now() + timedelta(days=days),
            stripe_subscription_id=sub_id,
        )

    # ── Checkout ──────────────────────────────────────────────────────────

    def test_amount_is_free_but_respects_the_minimum_of_each_currency(self):
        for amount, currency in [("9.99", "mxn"), ("1", "mxn"), ("0.99", "usd"), ("0", "usd")]:
            response = self.checkout(amount=amount, currency=currency)
            self.assertEqual(response.status_code, 400, (amount, currency))
            self.assertIn("mínimo", response.data["amount"][0])
        self.assertEqual(self.checkout(amount="1.005", currency="usd").status_code, 400)
        self.assertIn("$10.00 MXN", self.checkout(amount="5", currency="mxn").data["amount"][0])
        self.assertEqual(self.checkout(amount="mucho").status_code, 400)
        self.assertEqual(self.checkout(currency="eur").status_code, 400)
        self.stripe.checkout.Session.create.assert_not_called()

    def test_checkout_charges_the_chosen_amount_every_month(self):
        response = self.checkout(amount="37,50", currency="mxn")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["checkout_url"], "https://checkout.stripe.com/c/cs_1")

        local = ms.Subscription.objects.get()
        self.assertEqual((local.subscriber, local.recipient), (self.ana, self.ana))
        self.assertEqual((local.amount_cents, local.currency, local.status), (3750, "mxn", "pending"))
        self.assertEqual(local.stripe_checkout_session_id, "cs_1")

        params = self.stripe.checkout.Session.create.call_args.kwargs
        self.assertEqual(params["mode"], "subscription")
        self.assertEqual(params["customer"], "cus_ana")
        price = params["line_items"][0]["price_data"]
        self.assertEqual(price["unit_amount"], 3750)
        self.assertEqual(price["currency"], "mxn")
        self.assertEqual(price["recurring"], {"interval": "month"})
        self.assertEqual(params["subscription_data"]["metadata"], {"subscription_id": str(local.pk)})
        self.assertIn("{CHECKOUT_SESSION_ID}", params["success_url"])

    def test_stripe_customer_is_created_once(self):
        self.checkout()
        self.checkout(recipient_id=str(self.luis.pk))
        self.stripe.Customer.create.assert_called_once()
        self.assertEqual(ms.Profile.objects.get(user=self.ana).stripe_customer_id, "cus_ana")

    def test_can_subscribe_another_profile(self):
        response = self.checkout(amount="2", currency="usd", recipient_id=str(self.luis.pk), auto_renew=False)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["subscription"]["is_gift"])
        self.assertFalse(response.data["subscription"]["auto_renew"])
        product = self.stripe.checkout.Session.create.call_args.kwargs["line_items"][0]["price_data"]["product_data"]
        self.assertEqual(product["name"], "Suscripción para @luis")

    def test_cannot_pay_twice_for_the_same_profile_while_active(self):
        self.active_subscription(self.ana, self.luis, 1600, "mxn")
        response = self.checkout(recipient_id=str(self.luis.pk))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.checkout().status_code, 201)

    def test_stripe_failure_leaves_no_pending_subscription(self):
        import stripe as real_stripe
        self.stripe.checkout.Session.create.side_effect = real_stripe.APIConnectionError("sin red")
        response = self.checkout()
        self.assertEqual(response.status_code, 502)
        self.assertFalse(ms.Subscription.objects.exists())

    @override_settings(STRIPE_SECRET_KEY="")
    def test_without_stripe_keys_subscriptions_are_unavailable(self):
        self.assertEqual(self.checkout().status_code, 503)

    # ── Webhook ───────────────────────────────────────────────────────────

    def test_paid_gift_activates_the_recipient_and_respects_no_auto_renew(self):
        self.checkout(amount="5", currency="usd", recipient_id=str(self.luis.pk), auto_renew=False)
        local = ms.Subscription.objects.get()
        self.stripe.Subscription.retrieve.return_value = stripe_sub()
        self.stripe.Subscription.modify.return_value = stripe_sub(cancel_at_period_end=True)

        event = {
            "id": "evt_1", "object": "event", "type": "checkout.session.completed",
            "data": {"object": {
                "id": "cs_1", "object": "checkout.session", "mode": "subscription",
                "subscription": "sub_1", "metadata": {"subscription_id": str(local.pk)},
            }},
        }
        self.assertEqual(signed_webhook(self.client, event).status_code, 200)
        # Stripe reenvía eventos: el segundo no debe duplicar nada. Para entonces
        # Stripe ya devuelve la suscripción con la renovación apagada.
        self.stripe.Subscription.retrieve.return_value = stripe_sub(cancel_at_period_end=True)
        self.assertEqual(signed_webhook(self.client, event).status_code, 200)

        local.refresh_from_db()
        self.assertTrue(local.is_active)
        self.assertFalse(local.auto_renew)
        self.assertEqual(local.stripe_subscription_id, "sub_1")
        self.stripe.Subscription.modify.assert_called_once_with("sub_1", api_key="sk_test_x", cancel_at_period_end=True)

        profile = ms.Profile.objects.get(user=self.luis)
        self.assertTrue(profile.subscriptionActive)
        self.assertEqual(profile.subscription_amount, Decimal("5.00"))
        self.assertFalse(ms.Profile.objects.get(user=self.ana).subscriptionActive)

        notifications = ms.Notification.objects.filter(recipient=self.luis, notification_type="subscription_gift")
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.get().actor, self.ana)

    def test_cancellation_at_period_end_turns_the_badge_off(self):
        local = self.active_subscription(self.ana, self.ana, 10000, "usd", sub_id="sub_9")
        self.stripe.Subscription.retrieve.return_value = stripe_sub("sub_9", status="canceled")
        event = {
            "id": "evt_2", "object": "event", "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_9", "object": "subscription", "metadata": {}}},
        }
        self.assertEqual(signed_webhook(self.client, event).status_code, 200)

        local.refresh_from_db()
        self.assertEqual(local.status, "canceled")
        profile = ms.Profile.objects.get(user=self.ana)
        self.assertFalse(profile.subscriptionActive)
        self.assertEqual(profile.subscription_amount, Decimal("0.00"))

    def test_webhook_rejects_bad_signatures(self):
        response = self.client.post(
            reverse("subscription-webhook"), data="{}", content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=nope",
        )
        self.assertEqual(response.status_code, 400)
        self.stripe.Subscription.retrieve.assert_not_called()

    # ── Perfil ────────────────────────────────────────────────────────────

    def test_profile_adds_up_every_subscription_it_receives(self):
        self.active_subscription(self.luis, self.luis, 500, "usd", sub_id="sub_a")     # 5 USD
        self.active_subscription(self.ana, self.luis, 4800, "mxn", sub_id="sub_b")     # 48 MXN = 3 USD
        self.active_subscription(self.ana, self.ana, 100, "usd", days=-1, sub_id="sub_c")  # vencida

        response = self.client.get(reverse("subscription-status", kwargs={"user_id": self.luis.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["amount_usd"], "8.00")
        self.assertEqual(response.data["tier"], "sub_red")
        self.assertEqual(response.data["subscribers_count"], 2)
        self.assertEqual(response.data["my_subscription"]["amount"], "48.00")

        profile = ms.Profile.objects.get(user=self.luis)
        self.assertTrue(profile.subscriptionActive)
        self.assertEqual(profile.subscription_amount, Decimal("8.00"))

    def test_expired_subscription_without_webhook_is_corrected_on_read(self):
        self.active_subscription(self.ana, self.ana, 100, "usd", days=-1)
        ms.Profile.objects.filter(user=self.ana).update(subscriptionActive=True, subscription_amount=1)

        response = self.client.get(reverse("subscription-status", kwargs={"user_id": self.ana.pk}))
        self.assertFalse(response.data["active"])
        self.assertIsNone(response.data["tier"])
        self.assertFalse(ms.Profile.objects.get(user=self.ana).subscriptionActive)

    def test_my_subscriptions_lists_paid_and_received_without_abandoned_checkouts(self):
        self.checkout()  # pendiente: nunca se pagó
        self.active_subscription(self.ana, self.luis, 1600, "mxn", sub_id="sub_l")
        self.active_subscription(self.luis, self.ana, 300, "usd", sub_id="sub_r")

        data = self.client.get(reverse("subscription-list")).data
        self.assertEqual([s["recipient"]["username"] for s in data["paid"]], ["luis"])
        self.assertEqual([s["subscriber"]["username"] for s in data["received"]], ["luis"])
        self.assertEqual(data["summary"]["amount_usd"], "3.00")
        self.assertEqual(data["summary"]["tier"], "sub_green")

    # ── Renovación ────────────────────────────────────────────────────────

    def test_payer_turns_auto_renew_off_and_on(self):
        local = self.active_subscription(self.ana, self.luis, 1600, "mxn", sub_id="sub_r")
        url = reverse("subscription-detail", kwargs={"pk": local.pk})

        self.stripe.Subscription.modify.return_value = stripe_sub("sub_r", cancel_at_period_end=True)
        response = self.client.patch(url, {"auto_renew": False}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["auto_renew"])
        self.assertTrue(response.data["is_active"])  # sigue activa hasta fin de mes
        self.stripe.Subscription.modify.assert_called_with("sub_r", api_key="sk_test_x", cancel_at_period_end=True)

        self.stripe.Subscription.modify.return_value = stripe_sub("sub_r")
        response = self.client.patch(url, {"auto_renew": True}, format="json")
        self.assertTrue(response.data["auto_renew"])
        self.stripe.Subscription.modify.assert_called_with(
            "sub_r", api_key="sk_test_x", cancel_at_period_end=False, cancel_at="",
        )

    def test_only_the_payer_can_change_the_renewal(self):
        local = self.active_subscription(self.ana, self.luis, 1600, "mxn")
        url = reverse("subscription-detail", kwargs={"pk": local.pk})
        other = APIClient()
        other.force_authenticate(self.luis)
        self.assertEqual(other.patch(url, {"auto_renew": False}, format="json").status_code, 404)
        self.assertEqual(self.client.patch(url, {"auto_renew": "no"}, format="json").status_code, 400)
        self.stripe.Subscription.modify.assert_not_called()

    def test_return_page_confirms_the_payment_without_waiting_for_the_webhook(self):
        self.checkout(amount="2", currency="usd")
        self.stripe.checkout.Session.retrieve.return_value = {"id": "cs_1", "subscription": "sub_1"}
        self.stripe.Subscription.retrieve.return_value = stripe_sub()

        response = self.client.get(reverse("subscription-checkout-done"), {"result": "success", "session_id": "cs_1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Suscripción lista")
        self.assertTrue(ms.Subscription.objects.get().is_active)
        self.assertEqual(ms.Profile.objects.get(user=self.ana).subscription_amount, Decimal("2.00"))

    def test_sync_endpoint_activates_a_paid_checkout(self):
        self.checkout()
        local = ms.Subscription.objects.get()
        self.stripe.checkout.Session.retrieve.return_value = {"id": "cs_1", "subscription": "sub_1"}
        self.stripe.Subscription.retrieve.return_value = stripe_sub()

        response = self.client.post(reverse("subscription-sync", kwargs={"pk": local.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_active"])
        self.assertEqual(response.data["status"], "active")
