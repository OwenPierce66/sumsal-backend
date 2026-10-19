from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import Follow

User = get_user_model()


class UserFollowTests(TestCase):
    def setUp(self):
        self.follower = User.objects.create_user(
            username="follower",
            email="follower@example.com",
            password="test-password",
        )
        self.target = User.objects.create_user(
            username="target",
            email="target@example.com",
            password="test-password",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.follower)
        self.follow_url = reverse("user-follow-toggle", kwargs={"user_id": self.target.id})
        self.stats_url = reverse("user-social-stats", kwargs={"user_id": self.target.id})

    def test_follow_and_unfollow_are_idempotent_and_update_stats(self):
        response = self.client.post(self.follow_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            "followers_count": 1,
            "following_count": 0,
            "is_following": True,
        })
        self.client.post(self.follow_url)
        self.assertEqual(Follow.objects.filter(follower=self.follower, following=self.target).count(), 1)

        response = self.client.get(self.stats_url)
        self.assertEqual(response.data["followers_count"], 1)
        self.assertTrue(response.data["is_following"])

        response = self.client.delete(self.follow_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_following"])
        self.assertEqual(response.data["followers_count"], 0)

        self.client.delete(self.follow_url)
        self.assertFalse(Follow.objects.filter(follower=self.follower, following=self.target).exists())

    def test_cannot_follow_self(self):
        response = self.client.post(
            reverse("user-follow-toggle", kwargs={"user_id": self.follower.id})
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Follow.objects.exists())
