from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class ProfileSocialTests(TestCase):
    """Redes sociales y contadores del perfil."""

    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x", username="ana")
        self.luis = User.objects.create_user(email="luis@example.com", password="x", username="luis")
        self.ana_client = APIClient()
        self.ana_client.force_authenticate(self.ana)
        self.luis_client = APIClient()
        self.luis_client.force_authenticate(self.luis)

    def social(self, client, user):
        return client.get(reverse("user-social-stats", kwargs={"user_id": user.pk})).data

    def test_social_links_are_saved_cleaned_and_shown(self):
        response = self.ana_client.patch(reverse("user-me"), {
            "social_links": {"instagram": " @ana.becas ", "whatsapp": "+52 55 1234 5678", "tiktok": ""},
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["social_links"], {"instagram": "@ana.becas", "whatsapp": "+52 55 1234 5678"})
        self.assertEqual(self.social(self.luis_client, self.ana)["social_links"], {
            "instagram": "@ana.becas", "whatsapp": "+52 55 1234 5678",
        })

        # Desde el formulario (multipart) llegan como texto JSON.
        response = self.ana_client.patch(reverse("user-me"), {
            "first_name": "Ana", "social_links": '{"website": "ana.dev"}',
        }, format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["social_links"], {"website": "ana.dev"})

    def test_unknown_network_or_too_long(self):
        bad = self.ana_client.patch(reverse("user-me"), {"social_links": {"myspace": "ana"}}, format="json")
        self.assertEqual(bad.status_code, 400)
        long = self.ana_client.patch(reverse("user-me"), {"social_links": {"website": "x" * 201}}, format="json")
        self.assertEqual(long.status_code, 400)

    def test_counters(self):
        ms.Task.objects.create(user=self.ana, title="Pública", pch="consejos")
        ms.Task.objects.create(user=self.ana, title="Oculta", pch="consejos", is_hidden=True)
        ms.Task.objects.create(
            user=self.luis, title="Gran maestra", pch="testimonios",
            testimonial_for=self.ana, testimonial_status="approved",
        )
        ms.LikeP.objects.create(user=self.luis, profile=self.ana)
        ms.UserRecommendation.objects.create(recommender=self.luis, recommended=self.ana)

        visitor = self.social(self.luis_client, self.ana)
        self.assertEqual(
            (visitor["posts_count"], visitor["profile_likes_count"], visitor["testimonials_count"], visitor["recommendations_count"]),
            (1, 1, 1, 1),
        )
        self.assertEqual(self.social(self.ana_client, self.ana)["posts_count"], 2)

        profile = ms.Profile.objects.get(user=self.ana)
        profile.recommendations_public = False
        profile.save(update_fields=["recommendations_public"])
        self.assertIsNone(self.social(self.luis_client, self.ana)["recommendations_count"])


class SuggestedProfilesTests(TestCase):
    """Al abrir "Etiquetar personas" ya hay una lista: a quien sigues, quien te sigue y otras cuentas."""

    def test_empty_search_suggests_people(self):
        me = User.objects.create_user(email="me@example.com", password="x", username="yo")
        followed = User.objects.create_user(email="f@example.com", password="x", username="seguido")
        follower = User.objects.create_user(email="s@example.com", password="x", username="seguidor")
        other = User.objects.create_user(email="o@example.com", password="x", username="otra")
        User.objects.create_user(email="i@example.com", password="x", username="inactiva", is_active=False)
        ms.Follow.objects.create(follower=me, following=followed)
        ms.Follow.objects.create(follower=follower, following=me)
        client = APIClient()
        client.force_authenticate(me)
        names = [p["username"] for p in client.get(reverse("directory-search"), {"q": "", "scope": "profiles"}).data["profiles"]]
        self.assertEqual(names[:2], ["seguido", "seguidor"])
        self.assertIn("otra", names)
        self.assertNotIn("yo", names)
        self.assertNotIn("inactiva", names)
        # Sin texto y buscando también tareas: nada (el buscador del feed no cambia).
        both = client.get(reverse("directory-search"), {"q": ""}).data
        self.assertEqual(both, {"profiles": [], "tasks": []})
