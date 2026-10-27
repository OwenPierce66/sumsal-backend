from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


@override_settings(APP_ACCOUNT_EMAIL="owen@gmail.com")
class UserBadgesTests(TestCase):
    """Insignias junto al nombre: App, admin, recomendado, verificado y suscripción."""

    def setUp(self):
        self.viewer = User.objects.create_user(email="viewer@example.com", password="x", username="viewer")
        self.client = APIClient()
        self.client.force_authenticate(self.viewer)

    def make_user(self, name, **profile):
        user = User.objects.create_user(email=f"{name}@example.com", password="x", username=name)
        ms.Profile.objects.filter(user=user).update(**profile)
        return user

    def badges(self, *users):
        ids = ",".join(str(u.pk) for u in users)
        response = self.client.get(reverse("user-badges"), {"ids": ids})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_each_category_has_its_badge(self):
        app = User.objects.create_user(email="Owen@gmail.com", password="x", username="owen")
        admin = User.objects.create_user(email="admin@example.com", password="x", username="admin", is_staff=True)
        plus = self.make_user("plus", subscriptionActive=True, subscription_amount=Decimal("8.00"))
        basic = self.make_user("basic", subscriptionActive=True, subscription_amount=Decimal("0.63"))
        both = self.make_user("both", is_verified=True, is_recommended=True,
                              subscriptionActive=True, subscription_amount=Decimal("2"))
        expired = self.make_user("expired", subscriptionActive=False, subscription_amount=Decimal("20"))

        data = self.badges(app, admin, plus, basic, both, expired, self.viewer)
        self.assertEqual(data[str(app.pk)], ["app"])
        self.assertEqual(data[str(admin.pk)], ["admin"])
        self.assertEqual(data[str(plus.pk)], ["sub_red"])
        self.assertEqual(data[str(basic.pk)], ["sub_green"])
        self.assertEqual(data[str(both.pk)], ["recommended", "verified", "sub_green"])
        self.assertEqual(data[str(expired.pk)], [])
        self.assertEqual(data[str(self.viewer.pk)], [])

    def test_unknown_ids_are_left_out_and_bad_ids_rejected(self):
        self.assertEqual(self.badges(), {})
        response = self.client.get(reverse("user-badges"), {"ids": f"{uuid4()},{self.viewer.pk}"})
        self.assertEqual(list(response.data), [str(self.viewer.pk)])
        self.assertEqual(self.client.get(reverse("user-badges"), {"ids": "1;drop"}).status_code, 400)

    def test_batch_is_capped_and_needs_login(self):
        too_many = ",".join(str(uuid4()) for _ in range(101))
        self.assertEqual(self.client.get(reverse("user-badges"), {"ids": too_many}).status_code, 400)
        self.assertEqual(APIClient().get(reverse("user-badges"), {"ids": str(self.viewer.pk)}).status_code, 401)

    def test_one_query_for_any_number_of_users(self):
        users = [self.make_user(f"u{i}", is_verified=True) for i in range(30)]
        ids = ",".join(str(u.pk) for u in users)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("user-badges"), {"ids": ids})
        self.assertEqual(len(response.data), 30)
        user_queries = [q for q in ctx.captured_queries if "api_profile" in q["sql"]]
        self.assertEqual(len(user_queries), 1)
