from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class ProfileActivityTests(TestCase):
    """Me gusta, comentarios y verificaciones: cada quien decide si se ven en su perfil."""

    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x", username="ana")
        self.luis = User.objects.create_user(email="luis@example.com", password="x", username="luis")
        self.admin = User.objects.create_user(email="admin@example.com", password="x", username="admin", is_superuser=True, is_staff=True)
        self.task = ms.Task.objects.create(user=self.luis, title="Guía de becas", pch="consejos")
        self.hidden = ms.Task.objects.create(user=self.luis, title="Borrador", pch="consejos", is_hidden=True)
        self.clients = {}
        for user in (self.ana, self.luis, self.admin):
            client = APIClient()
            client.force_authenticate(user)
            self.clients[user.username] = client

    def activity(self, who, owner, kind):
        response = self.clients[who].get(reverse("user-activity", kwargs={"user_id": owner.pk}), {"kind": kind})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def set_public(self, who, kind, public):
        return self.clients[who].patch(
            reverse("user-activity", kwargs={"user_id": getattr(self, who).pk}),
            {"kind": kind, "public": public}, format="json",
        )

    def test_likes_are_private_until_the_owner_shows_them(self):
        ms.Like.objects.create(user=self.ana, task=self.task)
        ms.Like.objects.create(user=self.ana, task=self.hidden)  # ajena y oculta: nadie más la ve
        mine = self.activity("ana", self.ana, "likes")
        self.assertFalse(mine["public"])
        self.assertEqual(mine["visibility"], {"likes": False, "comments": False, "verifications": True})
        self.assertEqual([item["task"]["title"] for item in mine["items"]], ["Guía de becas"])

        other = self.activity("luis", self.ana, "likes")
        self.assertTrue(other["hidden"])
        self.assertNotIn("visibility", other)
        self.assertEqual(other["items"], [])

        self.assertEqual(self.set_public("ana", "likes", True).status_code, 200)
        self.assertEqual([item["task"]["title"] for item in self.activity("luis", self.ana, "likes")["items"]], ["Guía de becas"])
        # Solo el dueño cambia su privacidad.
        forbidden = self.clients["luis"].patch(
            reverse("user-activity", kwargs={"user_id": self.ana.pk}), {"kind": "likes", "public": False}, format="json",
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_comments_on_posts_and_forum(self):
        ms.NewPeticionCommentPost.objects.create(created_by=self.ana, post=self.task, text="Me sirvió mucho")
        thread = ms.Postt.objects.create(user=self.luis, title="Dudas de becas", content="¿alguien?")
        reply = ms.Postt.objects.create(user=self.ana, content="Yo te ayudo", parent=thread)
        ms.Postt.objects.create(user=self.ana, content="Otra", parent=reply)
        self.set_public("ana", "comments", True)
        data = self.activity("luis", self.ana, "comments")
        self.assertEqual(data["count"], 3)
        kinds = {(item["kind"], item.get("task", {}).get("title") or item["forum_post"]["title"]) for item in data["items"]}
        self.assertEqual(kinds, {("task", "Guía de becas"), ("forum", "Dudas de becas")})

    def test_verifications_are_recorded_and_public_by_default(self):
        response = self.clients["admin"].post(reverse("admin-verify-user", kwargs={"user_id": self.ana.pk}), {"is_verified": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        received = self.activity("luis", self.ana, "verifications")
        self.assertTrue(received["public"])
        self.assertEqual([item["user"]["username"] for item in received["items"]["received"]], ["admin"])
        given = self.activity("luis", self.admin, "verifications")
        self.assertEqual([item["user"]["username"] for item in given["items"]["given"]], ["ana"])

        self.clients["admin"].post(reverse("admin-verify-user", kwargs={"user_id": self.ana.pk}), {"is_verified": False}, format="json")
        self.assertEqual(self.activity("ana", self.ana, "verifications")["items"]["received"], [])

    def test_unknown_kind(self):
        response = self.clients["ana"].get(reverse("user-activity", kwargs={"user_id": self.ana.pk}), {"kind": "todo"})
        self.assertEqual(response.status_code, 400)
