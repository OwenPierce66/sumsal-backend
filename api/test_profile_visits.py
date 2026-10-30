from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class ProfileVisitTests(TestCase):
    """Visitas al perfil: el contador es libre; quién visitó, solo con suscripción en la app."""

    def setUp(self):
        self.users = {
            name: User.objects.create_user(email=f"{name}@example.com", password="x", username=name)
            for name in ("ana", "luis", "eva")
        }
        self.clients = {}
        for name, user in self.users.items():
            client = APIClient()
            client.force_authenticate(user)
            self.clients[name] = client

    def visit(self, who, owner):
        response = self.clients[who].post(reverse("profile-visit-record", kwargs={"user_id": self.users[owner].pk}))
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def visits(self, who="ana", owner="ana"):
        return self.clients[who].get(reverse("profile-visits", kwargs={"user_id": self.users[owner].pk}))

    def test_counts_one_per_visitor_and_day_and_not_your_own(self):
        self.visit("luis", "ana")
        self.visit("luis", "ana")
        self.visit("eva", "ana")
        self.assertFalse(self.visit("ana", "ana")["recorded"])
        row = ms.ProfileVisit.objects.get(owner=self.users["ana"], visitor=self.users["luis"])
        self.assertEqual(row.visits, 2)
        # Una visita de hace 10 días cuenta en 30 días pero no en 7.
        ms.ProfileVisit.objects.create(
            owner=self.users["ana"], visitor=self.users["eva"], day=timezone.localdate() - timedelta(days=10),
            last_visited_at=timezone.now() - timedelta(days=10),
        )
        data = self.visits().data
        self.assertEqual((data["visits_7d"], data["visits_30d"]), (2, 3))
        stats = self.clients["ana"].get(reverse("user-social-stats", kwargs={"user_id": self.users["ana"].pk})).data
        self.assertEqual(stats["visits_30d"], 3)
        other = self.clients["luis"].get(reverse("user-social-stats", kwargs={"user_id": self.users["ana"].pk})).data
        self.assertIsNone(other["visits_30d"])

    def test_who_visited_needs_an_app_subscription(self):
        self.visit("luis", "ana")
        data = self.visits().data
        self.assertFalse(data["can_see_visitors"])
        self.assertEqual(data["visitors"], [])
        self.assertEqual(data["visits_30d"], 1)

        ms.Profile.objects.update_or_create(user=self.users["ana"], defaults={"subscriptionActive": True})
        data = self.visits().data
        self.assertTrue(data["can_see_visitors"])
        self.assertEqual([(item["user"]["username"], item["visits"]) for item in data["visitors"]], [("luis", 1)])

    def test_anonymous_visits_count_but_do_not_say_who(self):
        ms.Profile.objects.update_or_create(user=self.users["ana"], defaults={"subscriptionActive": True})
        response = self.clients["eva"].patch(
            reverse("profile-visits", kwargs={"user_id": self.users["eva"].pk}), {"anonymous_visits": True}, format="json",
        )
        self.assertTrue(response.data["anonymous_visits"])
        self.visit("eva", "ana")
        self.visit("luis", "ana")
        visitors = self.visits().data["visitors"]
        self.assertEqual(len(visitors), 2)
        anonymous = next(item for item in visitors if item["anonymous"])
        self.assertIsNone(anonymous["user"])
        self.assertNotIn(str(self.users["eva"].pk), str(anonymous))

    def test_only_the_owner_sees_their_visits(self):
        self.assertEqual(self.visits(who="luis", owner="ana").status_code, 403)
        bad = self.clients["ana"].patch(
            reverse("profile-visits", kwargs={"user_id": self.users["ana"].pk}), {"anonymous_visits": "sí"}, format="json",
        )
        self.assertEqual(bad.status_code, 400)
