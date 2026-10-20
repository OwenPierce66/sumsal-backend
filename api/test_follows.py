from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import pFavorito

User = get_user_model()


class FavoriteProfileSocialStatsTests(TestCase):
    """"Seguir" es la función de perfiles favoritos (pFavorito)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="viewer", email="viewer@example.com", password="test-password"
        )
        self.target = User.objects.create_user(
            username="target", email="target@example.com", password="test-password"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.stats_url = reverse("user-social-stats", kwargs={"user_id": self.target.id})

    def test_toggle_favorite_updates_stats(self):
        response = self.client.get(self.stats_url)
        self.assertEqual(response.data["favorited_by_count"], 0)
        self.assertFalse(response.data["is_favorited"])

        self.assertEqual(
            self.client.post(reverse("pfavorito-add"), {"perfil_id": str(self.target.id)}).status_code,
            201,
        )
        response = self.client.get(self.stats_url)
        self.assertEqual(response.data["favorited_by_count"], 1)
        self.assertTrue(response.data["is_favorited"])

        self.assertEqual(
            self.client.post(reverse("pfavorito-add"), {"perfil_id": str(self.target.id)}).status_code,
            204,
        )
        response = self.client.get(self.stats_url)
        self.assertEqual(response.data["favorited_by_count"], 0)
        self.assertFalse(response.data["is_favorited"])

    def test_given_count_is_hidden_unless_public_or_owner(self):
        pFavorito.objects.create(user=self.target, perfil=self.user)
        profile = self.target.profile
        profile.favorite_profiles_public = False
        profile.save()

        response = self.client.get(self.stats_url)
        self.assertIsNone(response.data["favorites_count"])

        profile.favorite_profiles_public = True
        profile.save()
        response = self.client.get(self.stats_url)
        self.assertEqual(response.data["favorites_count"], 1)

    def test_owner_sees_own_given_count_and_is_not_favorited(self):
        other = User.objects.create_user(
            username="other", email="other@example.com", password="test-password"
        )
        pFavorito.objects.create(user=self.user, perfil=other)
        profile = self.user.profile
        profile.favorite_profiles_public = False
        profile.save()

        response = self.client.get(reverse("user-social-stats", kwargs={"user_id": self.user.id}))
        self.assertEqual(response.data["favorites_count"], 1)
        self.assertFalse(response.data["is_favorited"])

    def test_follow_endpoint_no_longer_exists(self):
        response = self.client.post(f"/api/users/{self.target.id}/follow/")
        self.assertEqual(response.status_code, 404)

    def test_admin_state_only_for_superuser(self):
        response = self.client.get(self.stats_url)
        self.assertNotIn("admin_state", response.data)

        staff = User.objects.create_user(
            username="staffer", email="staffer@example.com", password="test-password", is_staff=True
        )
        self.client.force_authenticate(staff)
        self.assertNotIn("admin_state", self.client.get(self.stats_url).data)

        admin = User.objects.create_superuser(
            username="boss", email="boss@example.com", password="test-password"
        )
        self.client.force_authenticate(admin)
        self.target.is_active = False
        self.target.save()
        response = self.client.get(self.stats_url)
        self.assertEqual(
            response.data["admin_state"],
            {
                "is_active": False,
                "is_staff": False,
                "is_superuser": False,
                "is_verified": False,
                "is_recommended": False,
            },
        )


class PinImpliesFavoriteTests(TestCase):
    """Anclar sin tenerlo en favoritos lo agrega primero."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="pinner", email="pinner@example.com", password="test-password"
        )
        self.target = User.objects.create_user(
            username="pinned", email="pinned@example.com", password="test-password"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_pin_profile_not_in_favorites_adds_it(self):
        self.assertFalse(pFavorito.objects.filter(user=self.user, perfil=self.target).exists())
        response = self.client.post(
            reverse("favorite-pin"),
            {"type": "profile", "target_id": str(self.target.id), "is_pinned": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        favorite = pFavorito.objects.get(user=self.user, perfil=self.target)
        self.assertTrue(favorite.is_pinned)

    def test_pin_task_not_in_favorites_adds_it(self):
        from api.models import Favorito, Task

        task = Task.objects.create(user=self.target, title="x", pch="peticiones")
        response = self.client.post(
            reverse("favorite-pin"),
            {"type": "task", "target_id": str(task.id), "is_pinned": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Favorito.objects.get(user=self.user, task=task).is_pinned)

    def test_unpin_unknown_favorite_is_still_404(self):
        response = self.client.post(
            reverse("favorite-pin"),
            {"type": "profile", "target_id": str(self.target.id), "is_pinned": False},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
