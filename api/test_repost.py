from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class RepostLikeInteractionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reposter",
            email="reposter@example.com",
            password="test-password",
        )
        self.owner = User.objects.create_user(
            username="author",
            email="author@example.com",
            password="test-password",
        )
        self.task = ms.Task.objects.create(user=self.owner, title="Aportación")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.repost_url = reverse("task-repost", kwargs={"task_id": self.task.id})
        self.like_url = reverse("task-like", kwargs={"task_id": self.task.id})

    def test_impulse_adds_like_and_removing_it_keeps_like(self):
        response = self.client.post(self.repost_url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["user_has_reposted"])
        self.assertTrue(response.data["user_has_liked"])
        self.assertEqual(response.data["likes_count"], 1)
        self.assertEqual(response.data["interaction_score"], 1)

        response = self.client.post(self.repost_url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["user_has_reposted"])
        self.assertTrue(response.data["user_has_liked"])
        self.assertEqual(response.data["likes_count"], 1)
        self.assertEqual(response.data["interaction_score"], 0)
        self.assertTrue(ms.Like.objects.filter(user=self.user, task=self.task).exists())

    def test_reposts_count_counts_only_impulses(self):
        response = self.client.post(self.repost_url, {}, format="json")
        self.assertEqual(response.data["reposts_count"], 1)

        # Compartir sube interaction_score pero no es un impulso.
        sharer = User.objects.create_user(username="sharer", email="sharer@example.com", password="x")
        sharer_client = APIClient()
        sharer_client.force_authenticate(sharer)
        shared = sharer_client.post(reverse("shared-task-list-create"), {"task_id": str(self.task.id)}, format="json")
        self.assertEqual(shared.status_code, 201, shared.data)

        detail = self.client.get(reverse("task-detail", kwargs={"id": self.task.id}))
        self.assertEqual(detail.data["reposts_count"], 1)
        self.assertEqual(detail.data["interaction_score"], 2)

        response = self.client.post(self.repost_url, {}, format="json")
        self.assertEqual(response.data["reposts_count"], 0)

    def test_preexisting_like_is_not_duplicated_or_used_as_repost_state(self):
        ms.Like.objects.create(user=self.user, task=self.task)

        response = self.client.post(self.repost_url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["user_has_reposted"])
        self.assertTrue(response.data["user_has_liked"])
        self.assertEqual(response.data["likes_count"], 1)
        self.assertEqual(ms.Like.objects.filter(user=self.user, task=self.task).count(), 1)

        response = self.client.post(self.repost_url, {}, format="json")

        self.assertFalse(response.data["user_has_reposted"])
        self.assertTrue(response.data["user_has_liked"])
        self.assertEqual(response.data["likes_count"], 1)

    def test_manual_unlike_does_not_turn_off_repost(self):
        self.client.post(self.repost_url, {}, format="json")

        response = self.client.post(self.like_url, {}, format="json")

        self.assertFalse(response.data["liked"])
        self.assertTrue(ms.Repost.objects.filter(user=self.user, task=self.task).exists())
        self.task.refresh_from_db()
        self.assertEqual(self.task.interaction_score, 1)

    def test_feed_and_task_creation_keep_serialized_repost_state_available(self):
        self.client.post(self.repost_url, {}, format="json")

        detail = self.client.get(reverse("task-detail", kwargs={"id": self.task.id}))
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertTrue(detail.data["user_has_reposted"])

        feed = self.client.get(reverse("feed"))
        self.assertEqual(feed.status_code, 200, feed.data)

        created = self.client.post(
            reverse("task-list-create"),
            {"title": "Nueva aportación"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertFalse(created.data["user_has_reposted"])
