from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class HiddenTaskTests(TestCase):
    """Modo oculto: la aportación solo la ve su dueño, en su perfil, hasta publicarla."""

    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="x", username="owner")
        self.other = User.objects.create_user(email="other@example.com", password="x", username="other")
        self.hidden = ms.Task.objects.create(user=self.owner, title="Borrador oculto", pch="consejos", is_hidden=True)
        self.public = ms.Task.objects.create(user=self.owner, title="Publicada", pch="consejos")
        self.owner_client = APIClient()
        self.owner_client.force_authenticate(self.owner)
        self.other_client = APIClient()
        self.other_client.force_authenticate(self.other)

    @staticmethod
    def ids(response):
        data = response.data
        items = data.get("results", data) if isinstance(data, dict) else data
        return {str(item["id"]) for item in items}

    def test_create_hidden_from_the_form(self):
        response = self.owner_client.post(reverse("task-list-create"), {
            "title": "Vista previa", "pch": "consejos", "is_hidden": "true",
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["is_hidden"])
        self.assertTrue(ms.Task.objects.get(id=response.data["id"]).is_hidden)

    def test_only_the_owner_sees_it_and_only_on_their_profile(self):
        hidden, public = str(self.hidden.id), str(self.public.id)

        own_profile = self.ids(self.owner_client.get(reverse("user-my-tasks")))
        self.assertEqual(own_profile, {hidden, public})
        own_public_profile = self.ids(self.owner_client.get(reverse("task-list-create"), {"user_id": self.owner.id}))
        self.assertIn(hidden, own_public_profile)

        # En el feed general ni siquiera el dueño la ve: todavía no está publicada.
        self.assertNotIn(hidden, self.ids(self.owner_client.get(reverse("task-list-create"))))

        for params in ({}, {"user_id": self.owner.id}):
            self.assertEqual(self.ids(self.other_client.get(reverse("task-list-create"), params)), {public})
        self.assertNotIn(hidden, self.ids(self.other_client.get(reverse("feed"))))
        search = self.other_client.get(reverse("directory-search"), {"q": "Borrador"})
        self.assertEqual(search.data["tasks"], [])

    def test_others_cannot_open_or_interact_with_it(self):
        detail = reverse("task-detail", kwargs={"id": self.hidden.id})
        self.assertEqual(self.other_client.get(detail).status_code, 404)
        self.assertEqual(self.owner_client.get(detail).status_code, 200)

        self.assertEqual(self.other_client.post(reverse("task-like", kwargs={"task_id": self.hidden.id})).status_code, 404)
        comment = self.other_client.post(
            reverse("task-comments", kwargs={"task_id": self.hidden.id}), {"text": "hola"}, format="json",
        )
        self.assertEqual(comment.status_code, 404)
        self.assertEqual(self.other_client.post(reverse("favorito-add"), {"task_id": str(self.hidden.id)}).status_code, 404)
        self.assertFalse(ms.Like.objects.exists())
        self.assertFalse(ms.NewPeticionCommentPost.objects.exists())

    def test_cannot_be_shared_until_published(self):
        response = self.owner_client.post(reverse("shared-task-list-create"), {"task_id": str(self.hidden.id)}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Publícala", response.data["detail"])

    def test_publishing_shows_it_and_only_then_notifies_tagged_people(self):
        ms.TaskTag.objects.create(task=self.hidden, user=self.other, tagged_by=self.owner)
        self.assertFalse(ms.Notification.objects.filter(recipient=self.other).exists())

        response = self.owner_client.patch(
            reverse("task-detail", kwargs={"id": self.hidden.id}), {"is_hidden": False}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["is_hidden"])
        self.assertIn(str(self.hidden.id), self.ids(self.other_client.get(reverse("task-list-create"))))
        self.assertTrue(
            ms.Notification.objects.filter(recipient=self.other, notification_type="task_tag").exists()
        )

    def test_others_cannot_change_visibility(self):
        response = self.other_client.patch(
            reverse("task-detail", kwargs={"id": self.public.id}), {"is_hidden": True}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.public.refresh_from_db()
        self.assertFalse(self.public.is_hidden)
