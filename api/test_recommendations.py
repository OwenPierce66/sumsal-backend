from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class UserRecommendationTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", email="alice@example.com", password="pw-test-1")
        self.bob = User.objects.create_user(username="bob", email="bob@example.com", password="pw-test-1")
        self.carol = User.objects.create_user(username="carol", email="carol@example.com", password="pw-test-1")
        self.client = APIClient()
        self.client.force_authenticate(self.alice)

    def url(self, user):
        return reverse("user-recommendations", kwargs={"user_id": user.id})

    def test_recommend_with_comment_shows_on_both_profiles(self):
        response = self.client.post(self.url(self.bob), {"comment": "  Muy   buen aporte "}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["is_recommended_by_me"])
        self.assertEqual(response.data["my_comment"], "Muy buen aporte")
        self.assertEqual(response.data["received_count"], 1)
        self.assertEqual(str(response.data["received"][0]["user"]["id"]), str(self.alice.id))

        # En el perfil de quien recomienda aparece como "dada".
        mine = self.client.get(self.url(self.alice))
        self.assertEqual(mine.data["given_count"], 1)
        self.assertEqual(str(mine.data["given"][0]["user"]["id"]), str(self.bob.id))
        self.assertEqual(mine.data["given"][0]["comment"], "Muy buen aporte")

    def test_one_per_pair_and_comment_is_updated(self):
        self.client.post(self.url(self.bob), {"comment": "uno"}, format="json")
        response = self.client.post(self.url(self.bob), {"comment": "dos"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ms.UserRecommendation.objects.count(), 1)
        self.assertEqual(response.data["received"][0]["comment"], "dos")

    def test_comment_is_optional_and_limited(self):
        self.assertEqual(self.client.post(self.url(self.bob), {}, format="json").status_code, 201)
        too_long = self.client.post(self.url(self.carol), {"comment": "x" * 201}, format="json")
        self.assertEqual(too_long.status_code, 400)
        self.assertFalse(ms.UserRecommendation.objects.filter(recommended=self.carol).exists())

    def test_cannot_recommend_self(self):
        response = self.client.post(self.url(self.alice), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ms.UserRecommendation.objects.exists())

    def test_delete_removes_my_recommendation_only(self):
        ms.UserRecommendation.objects.create(recommender=self.alice, recommended=self.bob)
        ms.UserRecommendation.objects.create(recommender=self.carol, recommended=self.bob)
        response = self.client.delete(self.url(self.bob))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_recommended_by_me"])
        self.assertEqual(response.data["received_count"], 1)

    def test_hidden_profile_hides_lists_but_not_my_own_state(self):
        ms.UserRecommendation.objects.create(recommender=self.alice, recommended=self.bob, comment="hola")
        ms.UserRecommendation.objects.create(recommender=self.bob, recommended=self.carol)
        profile = ms.Profile.objects.get_or_create(user=self.bob)[0]
        profile.recommendations_public = False
        profile.save()

        response = self.client.get(self.url(self.bob))
        self.assertTrue(response.data["hidden"])
        self.assertEqual(response.data["received"], [])
        self.assertEqual(response.data["given"], [])
        self.assertIsNone(response.data["received_count"])
        self.assertIsNone(response.data["given_count"])
        self.assertTrue(response.data["is_recommended_by_me"])
        self.assertEqual(response.data["my_comment"], "hola")

        # El dueño siempre ve las suyas.
        owner = APIClient()
        owner.force_authenticate(self.bob)
        own = owner.get(self.url(self.bob))
        self.assertFalse(own.data["hidden"])
        self.assertEqual(own.data["received_count"], 1)
        self.assertEqual(own.data["given_count"], 1)

    def test_owner_can_toggle_visibility_and_others_cannot(self):
        response = self.client.patch(self.url(self.alice), {"public": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["public"])
        self.assertFalse(ms.Profile.objects.get(user=self.alice).recommendations_public)

        response = self.client.patch(self.url(self.alice), {"public": True}, format="json")
        self.assertTrue(response.data["public"])

        self.assertEqual(self.client.patch(self.url(self.bob), {"public": False}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(self.url(self.alice), {"public": "no"}, format="json").status_code, 400)

    def test_requires_authentication(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get(self.url(self.bob)).status_code, 401)

    def test_independent_from_admin_badge(self):
        self.client.post(self.url(self.bob), {}, format="json")
        profile = ms.Profile.objects.get_or_create(user=self.bob)[0]
        self.assertFalse(profile.is_recommended)

    def test_admin_badge_also_records_who_the_admin_recommends(self):
        admin = User.objects.create_superuser(username="boss", email="boss@example.com", password="pw-test-1")
        admin_client = APIClient()
        admin_client.force_authenticate(admin)
        admin_url = reverse("admin-recommend-user", kwargs={"user_id": self.bob.id})

        response = admin_client.post(admin_url, {"is_recommended": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ms.Profile.objects.get(user=self.bob).is_recommended)
        self.assertTrue(
            ms.UserRecommendation.objects.filter(recommender=admin, recommended=self.bob).exists()
        )

        # Aparece como "dada" en el perfil del admin y como "recibida" en el de Bob.
        given = admin_client.get(self.url(admin))
        self.assertEqual(given.data["given_count"], 1)
        received = self.client.get(self.url(self.bob))
        self.assertEqual(received.data["received_count"], 1)

        # Repetir no duplica; quitar la insignia borra el registro del admin.
        admin_client.post(admin_url, {"is_recommended": True}, format="json")
        self.assertEqual(ms.UserRecommendation.objects.filter(recommended=self.bob).count(), 1)
        admin_client.post(admin_url, {"is_recommended": False}, format="json")
        self.assertFalse(ms.Profile.objects.get(user=self.bob).is_recommended)
        self.assertFalse(ms.UserRecommendation.objects.filter(recommended=self.bob).exists())

    def test_admin_removing_badge_keeps_other_users_recommendations(self):
        admin = User.objects.create_superuser(username="boss", email="boss@example.com", password="pw-test-1")
        ms.UserRecommendation.objects.create(recommender=self.alice, recommended=self.bob)
        admin_client = APIClient()
        admin_client.force_authenticate(admin)
        admin_url = reverse("admin-recommend-user", kwargs={"user_id": self.bob.id})
        admin_client.post(admin_url, {"is_recommended": True}, format="json")
        admin_client.post(admin_url, {"is_recommended": False}, format="json")
        self.assertEqual(ms.UserRecommendation.objects.filter(recommended=self.bob).count(), 1)

    def test_admin_recommending_self_does_not_break(self):
        admin = User.objects.create_superuser(username="boss", email="boss@example.com", password="pw-test-1")
        admin_client = APIClient()
        admin_client.force_authenticate(admin)
        url = reverse("admin-recommend-user", kwargs={"user_id": admin.id})
        self.assertEqual(admin_client.post(url, {"is_recommended": True}, format="json").status_code, 200)
        self.assertFalse(ms.UserRecommendation.objects.exists())
