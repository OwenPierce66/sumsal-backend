from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Like, Notification, Task

User = get_user_model()


def ids(response):
    data = response.data
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    return {str(item["id"]) for item in items}


class StorySavedTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner", email="owner@example.com", password="test-password"
        )
        self.fan = User.objects.create_user(
            username="fan", email="fan@example.com", password="test-password"
        )
        self.other = User.objects.create_user(
            username="other", email="other@example.com", password="test-password"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def make_story(self, hours_old=30, **extra):
        story = Task.objects.create(
            user=self.owner,
            title="Historia",
            pch="historias",
            is_story=True,
            **extra,
        )
        Task.objects.filter(pk=story.pk).update(
            created_at=timezone.now() - timedelta(hours=hours_old)
        )
        story.refresh_from_db()
        return story

    def save_url(self, story):
        return reverse("story-save", kwargs={"story_id": story.id})

    def test_story_created_through_api_is_marked_and_not_saved(self):
        response = self.client.post(
            reverse("story-list-create"), {"title": "Mi historia", "description": "x"}
        )
        self.assertEqual(response.status_code, 201)
        story = Task.objects.get(pk=response.data["id"])
        self.assertTrue(story.is_story)
        self.assertFalse(story.story_saved)

    def test_client_cannot_force_story_flags(self):
        response = self.client.post(
            reverse("task-list-create"),
            {"title": "x", "description": "y", "pch": "peticiones",
             "is_story": "true", "story_saved": "false"},
        )
        self.assertEqual(response.status_code, 201)
        task = Task.objects.get(pk=response.data["id"])
        self.assertFalse(task.is_story)

    def test_unsaved_story_is_hidden_from_public_listings(self):
        story = self.make_story()
        normal = Task.objects.create(user=self.owner, title="Normal", pch="peticiones")
        legacy = Task.objects.create(user=self.owner, title="Vieja", pch="historias")

        viewer = APIClient()
        viewer.force_authenticate(self.other)
        listing = ids(viewer.get(reverse("task-list-create")))
        self.assertNotIn(str(story.id), listing)
        self.assertIn(str(normal.id), listing)
        # Las historias viejas (sin is_story) no cambian.
        self.assertIn(str(legacy.id), listing)

        self.assertNotIn(str(story.id), ids(self.client.get(reverse("user-my-tasks"))))
        self.assertNotIn(str(story.id), ids(viewer.get(reverse("feed"))))
        search = viewer.get(reverse("directory-search"), {"q": "Historia", "scope": "tasks"})
        self.assertNotIn(str(story.id), {str(t["id"]) for t in search.data["tasks"]})

    def test_saved_story_appears_in_listings(self):
        story = self.make_story()
        response = self.client.post(self.save_url(story))
        self.assertEqual(response.status_code, 200)
        story.refresh_from_db()
        self.assertTrue(story.story_saved)
        self.assertIn(str(story.id), ids(self.client.get(reverse("user-my-tasks"))))
        self.assertIn(str(story.id), ids(self.client.get(reverse("task-list-create"))))

    def test_only_owner_can_save_and_only_after_24h(self):
        story = self.make_story()
        stranger = APIClient()
        stranger.force_authenticate(self.other)
        self.assertEqual(stranger.post(self.save_url(story)).status_code, 403)

        active = self.make_story(hours_old=1)
        self.assertEqual(self.client.post(self.save_url(active)).status_code, 400)
        active.refresh_from_db()
        self.assertFalse(active.story_saved)

    def test_saving_hides_like_names_but_keeps_count(self):
        story = self.make_story()
        Like.objects.create(user=self.fan, task=story)
        Like.objects.create(user=self.other, task=story)
        likers_url = reverse("task-likers", kwargs={"task_id": story.id})
        self.assertEqual(len(self.client.get(likers_url).data), 2)

        self.client.post(self.save_url(story))
        # Guardar dos veces no rompe nada.
        self.assertEqual(self.client.post(self.save_url(story)).status_code, 200)

        self.assertEqual(story.likes.count(), 2)
        self.assertEqual(len(self.client.get(likers_url).data), 0)

        fan_client = APIClient()
        fan_client.force_authenticate(self.fan)
        detail = fan_client.get(reverse("task-detail", kwargs={"id": story.id}))
        self.assertEqual(detail.data["likes_count"], 2)
        self.assertFalse(detail.data["user_has_liked"])

    def test_like_again_reveals_name_without_changing_count(self):
        story = self.make_story()
        Like.objects.create(user=self.fan, task=story)
        self.client.post(self.save_url(story))

        fan_client = APIClient()
        fan_client.force_authenticate(self.fan)
        like_url = reverse("task-like", kwargs={"task_id": story.id})
        response = fan_client.post(like_url)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["liked"])
        self.assertEqual(response.data["likes_count"], 1)

        likers_url = reverse("task-likers", kwargs={"task_id": story.id})
        self.assertEqual(len(self.client.get(likers_url).data), 1)
        detail = fan_client.get(reverse("task-detail", kwargs={"id": story.id}))
        self.assertTrue(detail.data["user_has_liked"])

        # Un tercer toque lo quita como cualquier like normal.
        response = fan_client.post(like_url)
        self.assertFalse(response.data["liked"])
        self.assertEqual(response.data["likes_count"], 0)

    def test_expiry_notification_is_created_once_and_serialized(self):
        story = self.make_story(hours_old=30)
        self.make_story(hours_old=2)  # sigue activa: no pregunta todavia

        response = self.client.get(reverse("notification-list"))
        results = response.data["results"] if "results" in response.data else response.data
        expired = [n for n in results if n["type"] == "story_expired"]
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["data"]["story_id"], str(story.id))
        self.assertFalse(expired[0]["data"]["story_saved"])

        # Segunda consulta y conteo no duplican.
        self.client.get(reverse("notification-list"))
        self.client.get(reverse("notification-unread-count"))
        self.assertEqual(
            Notification.objects.filter(notification_type="story_expired").count(), 1
        )

        # Si la descarta, no vuelve a aparecer.
        Notification.objects.filter(notification_type="story_expired").delete()
        self.client.get(reverse("notification-list"))
        self.assertFalse(
            Notification.objects.filter(notification_type="story_expired").exists()
        )

    def test_shared_story_and_saved_story_do_not_prompt(self):
        Task.objects.create(
            user=self.owner, title="Compartida", pch="historias", story_is_shared=True
        )
        self.make_story(hours_old=30, story_saved=True)
        self.client.get(reverse("notification-list"))
        self.assertFalse(
            Notification.objects.filter(notification_type="story_expired").exists()
        )
