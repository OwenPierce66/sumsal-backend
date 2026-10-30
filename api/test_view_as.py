from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class ViewAsTests(TestCase):
    """Ver como otra persona: su feed (lo de quienes sigue), si lo permite, con mis permisos."""

    def setUp(self):
        self.users = {
            name: User.objects.create_user(email=f"{name}@example.com", password="x", username=name)
            for name in ("ana", "luis", "eva", "yo")
        }
        ms.Profile.objects.get_or_create(user=self.users["ana"])
        # Ana sigue a Luis (y lo tiene en favoritos); no sigue a Eva.
        ms.Follow.objects.create(follower=self.users["ana"], following=self.users["luis"])
        ms.pFavorito.objects.create(user=self.users["ana"], perfil=self.users["luis"])
        self.luis_post = ms.Task.objects.create(user=self.users["luis"], title="Becas", pch="consejos")
        self.eva_post = ms.Task.objects.create(user=self.users["eva"], title="Recetas", pch="consejos")
        self.clients = {}
        for name, user in self.users.items():
            client = APIClient()
            client.force_authenticate(user)
            self.clients[name] = client

    def allow(self, allowed=True):
        response = self.clients["ana"].patch(
            reverse("user-activity", kwargs={"user_id": self.users["ana"].pk}),
            {"kind": "feed", "public": allowed}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def feed_as(self, who, owner, **params):
        return self.clients[who].get(reverse("task-list-create"), {"as_user": owner.pk, **params})

    def titles(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        return [task["title"] for task in response.data["results"]]

    def test_only_if_the_person_allows_it(self):
        ana = self.users["ana"]
        response = self.feed_as("yo", ana)
        self.assertEqual(response.status_code, 403)
        stats = self.clients["yo"].get(reverse("user-social-stats", kwargs={"user_id": ana.pk})).data
        self.assertFalse(stats["can_view_feed"])
        self.assertIsNone(stats["feed_public"])

        data = self.allow()
        self.assertTrue(data["public"])
        self.assertTrue(data["feed_public"])
        stats = self.clients["yo"].get(reverse("user-social-stats", kwargs={"user_id": ana.pk})).data
        self.assertTrue(stats["can_view_feed"])
        own = self.clients["ana"].get(reverse("user-social-stats", kwargs={"user_id": ana.pk})).data
        self.assertTrue(own["feed_public"])
        self.assertFalse(own["can_view_feed"])

        self.allow(False)
        self.assertEqual(self.feed_as("yo", ana).status_code, 403)

    def test_feed_is_what_the_people_they_follow_post(self):
        self.allow()
        ana = self.users["ana"]
        self.assertEqual(self.titles(self.feed_as("yo", ana)), ["Becas"])
        # Sus filtros de "a quién sigo" y "favoritos" son los de ella, no los míos.
        self.assertEqual(self.titles(self.feed_as("yo", ana, favorite_users_only="true")), ["Becas"])
        self.assertEqual(self.titles(self.feed_as("yo", ana, followed_users_only="true")), ["Becas"])
        self.assertEqual(self.titles(self.feed_as("yo", ana, pch="peticiones")), [])

    def test_never_shows_what_i_cannot_see(self):
        self.allow()
        ana, luis = self.users["ana"], self.users["luis"]
        group = ms.CommunityGroup.objects.create(name="Privado", is_private=True, created_by=luis)
        ms.CommunityGroupMember.objects.create(group=group, user=luis, role="owner", status="active")
        ms.CommunityGroupMember.objects.create(group=group, user=ana, role="member", status="active")
        ms.Task.objects.create(user=luis, title="Solo del grupo", pch="consejos", group=group, group_status="approved")
        ms.Task.objects.create(user=luis, title="Oculta", pch="consejos", is_hidden=True)
        self.assertIn("Solo del grupo", self.titles(self.clients["ana"].get(reverse("task-list-create"))))
        self.assertEqual(self.titles(self.feed_as("yo", ana)), ["Becas"])

    def test_shares_from_the_people_they_follow(self):
        self.allow()
        ana = self.users["ana"]
        ms.SharedTask.objects.create(task=self.eva_post, shared_by=self.users["luis"])
        ms.SharedTask.objects.create(task=self.luis_post, shared_by=self.users["eva"])
        ms.SharedTask.objects.create(task=self.eva_post, shared_by=self.users["yo"])
        response = self.clients["yo"].get(reverse("shared-task-list-create"), {"as_user": ana.pk})
        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data["results"] if isinstance(response.data, dict) else response.data
        self.assertEqual(len(rows), 2)

    def test_unknown_profile(self):
        response = self.clients["yo"].get(reverse("task-list-create"), {"as_user": "no-existe"})
        self.assertEqual(response.status_code, 404)
