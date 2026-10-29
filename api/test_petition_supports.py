from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms
from api.test_subscriptions import WEBHOOK_SECRET, signed_webhook

User = get_user_model()


def session(session_id="cs_1", support_id=None, payment_status="paid", status="complete"):
    return {
        "id": session_id,
        "object": "checkout.session",
        "mode": "payment",
        "status": status,
        "payment_status": payment_status,
        "client_reference_id": str(support_id) if support_id else None,
        "metadata": {"petition_support_id": str(support_id)} if support_id else {},
    }


@override_settings(
    STRIPE_SECRET_KEY="sk_test_x",
    STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    SUBSCRIPTION_MXN_PER_USD="16",
)
class PetitionSupportTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="x", username="owner")
        self.fan = User.objects.create_user(email="fan@example.com", password="x", username="fan")
        self.petition = ms.Task.objects.create(user=self.owner, title="Más parques", pch="peticiones")
        self.tip = ms.Task.objects.create(user=self.owner, title="Un consejo", pch="consejos")
        self.owner_client = APIClient()
        self.owner_client.force_authenticate(self.owner)
        self.fan_client = APIClient()
        self.fan_client.force_authenticate(self.fan)

        for target in ("api.subscriptions.stripe", "api.petition_supports.stripe"):
            patcher = mock.patch(target)
            stripe = patcher.start()
            self.addCleanup(patcher.stop)
            stripe.Customer.create.return_value = {"id": "cus_1"}
            stripe.checkout.Session.create.return_value = {"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"}
        self.stripe = stripe

    def support(self, client, task=None, **body):
        body.setdefault("amount", "50")
        body.setdefault("currency", "mxn")
        task = task or self.petition
        return client.post(reverse("petition-support-checkout", kwargs={"task_id": task.id}), body, format="json")

    def paid(self, supporter, cents, currency="mxn", task=None):
        return ms.PetitionSupport.objects.create(
            task=task or self.petition, supporter=supporter, amount_cents=cents, currency=currency,
            status=ms.PetitionSupport.STATUS_PAID,
        )

    def detail(self, client, task=None):
        return client.get(reverse("task-detail", kwargs={"id": (task or self.petition).id})).data

    def test_creator_and_others_can_pay_a_one_time_support(self):
        for client in (self.fan_client, self.owner_client):
            response = self.support(client, amount="50")
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["checkout_url"], "https://checkout.stripe.com/c/cs_1")
        kwargs = self.stripe.checkout.Session.create.call_args.kwargs
        self.assertEqual(kwargs["mode"], "payment")
        self.assertEqual(kwargs["line_items"][0]["price_data"]["unit_amount"], 5000)
        self.assertNotIn("recurring", kwargs["line_items"][0]["price_data"])
        self.assertEqual(ms.PetitionSupport.objects.filter(status="pending").count(), 2)

    def test_only_petitions_accept_support_and_amount_has_the_stripe_minimum(self):
        self.assertEqual(self.support(self.fan_client, task=self.tip).status_code, 400)
        self.assertEqual(self.support(self.fan_client, amount="5").status_code, 400)
        self.assertEqual(self.support(self.fan_client, amount="0.5", currency="usd").status_code, 400)
        self.assertFalse(ms.PetitionSupport.objects.exists())

    def test_hidden_petition_can_only_be_supported_by_its_creator(self):
        self.petition.is_hidden = True
        self.petition.save(update_fields=["is_hidden"])
        self.assertEqual(self.support(self.fan_client).status_code, 404)
        self.assertEqual(self.support(self.owner_client).status_code, 201)

    def test_total_counts_only_paid_supports_converted_to_pesos(self):
        self.paid(self.fan, 5000)
        self.paid(self.fan, 200, currency="usd")
        self.paid(self.owner, 1000)
        ms.PetitionSupport.objects.create(task=self.petition, supporter=self.owner, amount_cents=99900, currency="mxn")
        self.assertEqual(
            self.detail(self.fan_client)["support_total"],
            {"amount_mxn": "92.00", "supporters_count": 2},
        )
        self.assertIsNone(self.detail(self.fan_client, task=self.tip)["support_total"])

    def test_webhook_marks_the_support_paid_and_notifies_the_creator_once(self):
        self.support(self.fan_client, amount="20")
        local = ms.PetitionSupport.objects.get()
        event = {"id": "evt_1", "type": "checkout.session.completed",
                 "data": {"object": session(support_id=local.pk)}}
        self.assertEqual(signed_webhook(self.fan_client, event).status_code, 200)
        self.assertEqual(signed_webhook(self.fan_client, event).status_code, 200)
        local.refresh_from_db()
        self.assertEqual(local.status, "paid")
        self.assertEqual(
            ms.Notification.objects.filter(recipient=self.owner, notification_type="petition_support").count(), 1,
        )
        self.assertEqual(self.detail(self.owner_client)["support_total"]["amount_mxn"], "20.00")

    def test_expired_checkout_does_not_count(self):
        self.support(self.fan_client)
        local = ms.PetitionSupport.objects.get()
        event = {"id": "evt_2", "type": "checkout.session.expired",
                 "data": {"object": session(support_id=local.pk, payment_status="unpaid", status="expired")}}
        self.assertEqual(signed_webhook(self.fan_client, event).status_code, 200)
        local.refresh_from_db()
        self.assertEqual(local.status, "expired")

    def test_sync_confirms_the_payment_without_waiting_for_the_webhook(self):
        self.support(self.fan_client, amount="30")
        local = ms.PetitionSupport.objects.get()
        self.stripe.checkout.Session.retrieve.return_value = session(support_id=local.pk)
        response = self.fan_client.post(reverse("petition-support-sync", kwargs={"pk": local.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["support"]["status"], "paid")
        self.assertEqual(response.data["support_total"], {"amount_mxn": "30.00", "supporters_count": 1})
        # Solo quien pagó puede sincronizar su apoyo.
        self.assertEqual(
            self.owner_client.post(reverse("petition-support-sync", kwargs={"pk": local.pk})).status_code, 404,
        )

    def test_supporters_list_adds_up_each_person_from_highest_to_lowest(self):
        self.paid(self.fan, 1000)
        self.paid(self.fan, 100, currency="usd")
        self.paid(self.owner, 2000)
        response = self.fan_client.get(reverse("petition-supporters", kwargs={"task_id": self.petition.id}))
        self.assertEqual(response.status_code, 200)
        rows = [(row["username"], row["amount_mxn"]) for row in response.data["supporters"]]
        self.assertEqual(rows, [("fan", "26.00"), ("owner", "20.00")])
        self.assertEqual(response.data["support_total"], {"amount_mxn": "46.00", "supporters_count": 2})

    @override_settings(STRIPE_SECRET_KEY="")
    def test_without_stripe_keys_support_is_unavailable(self):
        self.assertEqual(self.support(self.fan_client).status_code, 503)

    def test_my_supports_groups_given_and_received_by_petition(self):
        other_petition = ms.Task.objects.create(user=self.fan, title="Ciclovías", pch="peticiones")
        self.paid(self.fan, 1000)
        self.paid(self.fan, 100, currency="usd")
        self.paid(self.owner, 2000)
        self.paid(self.owner, 5000, task=other_petition)
        ms.PetitionSupport.objects.create(task=self.petition, supporter=self.owner, amount_cents=99900, currency="mxn")

        data = self.owner_client.get(reverse("petition-support-list")).data
        given = {row["task"]["title"]: (row["amount_mxn"], row["times"]) for row in data["given"]}
        self.assertEqual(given, {"Más parques": ("20.00", 1), "Ciclovías": ("50.00", 1)})
        received = {row["task"]["title"]: (row["amount_mxn"], row["supporters_count"]) for row in data["received"]}
        self.assertEqual(received, {"Más parques": ("46.00", 2)})
        self.assertEqual(data["summary"], {"given_mxn": "70.00", "received_mxn": "46.00"})

        fan = self.fan_client.get(reverse("petition-support-list")).data
        self.assertEqual([(r["amount_mxn"], r["times"]) for r in fan["given"]], [("26.00", 2)])
        self.assertEqual(fan["received"][0]["task"]["title"], "Ciclovías")

    def test_other_profiles_supports_are_public_but_hide_hidden_petitions(self):
        secret = ms.Task.objects.create(user=self.owner, title="Borrador", pch="peticiones", is_hidden=True)
        self.paid(self.owner, 3000, task=secret)
        self.paid(self.fan, 1000)
        url = reverse("petition-support-user-list", kwargs={"user_id": self.owner.id})

        seen_by_fan = self.fan_client.get(url).data
        self.assertEqual(seen_by_fan["user"]["username"], "owner")
        self.assertEqual([r["task"]["title"] for r in seen_by_fan["given"]], [])
        self.assertEqual([(r["task"]["title"], r["amount_mxn"]) for r in seen_by_fan["received"]], [("Más parques", "10.00")])

        seen_by_owner = self.owner_client.get(url).data
        self.assertEqual([r["task"]["title"] for r in seen_by_owner["given"]], ["Borrador"])
