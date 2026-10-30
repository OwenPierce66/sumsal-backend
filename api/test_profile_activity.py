from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class ProfileActivityTests(TestCase):
    """Tu actividad: todo lo que haces; cada tipo es solo tuyo, de tus suscriptores o de todos."""

    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x", username="ana")
        self.luis = User.objects.create_user(email="luis@example.com", password="x", username="luis")
        self.eva = User.objects.create_user(email="eva@example.com", password="x", username="eva")
        self.admin = User.objects.create_user(email="admin@example.com", password="x", username="admin", is_superuser=True, is_staff=True)
        self.task = ms.Task.objects.create(user=self.luis, title="Guía de becas", pch="consejos")
        self.hidden = ms.Task.objects.create(user=self.luis, title="Borrador", pch="consejos", is_hidden=True)
        self.clients = {}
        for user in (self.ana, self.luis, self.eva, self.admin):
            client = APIClient()
            client.force_authenticate(user)
            self.clients[user.username] = client

    def activity(self, who, owner, kind="all"):
        response = self.clients[who].get(reverse("user-activity", kwargs={"user_id": owner.pk}), {"kind": kind})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def set_level(self, who, kind, level):
        return self.clients[who].patch(
            reverse("user-activity", kwargs={"user_id": getattr(self, who).pk}),
            {"kind": kind, "level": level}, format="json",
        )

    def subscribe(self, subscriber, recipient):
        ms.Subscription.objects.create(
            subscriber=subscriber, recipient=recipient, amount_cents=1000, currency="mxn",
            status="active", current_period_end=timezone.now() + timedelta(days=20),
        )

    def test_likes_are_private_until_the_owner_shows_them(self):
        ms.Like.objects.create(user=self.ana, task=self.task)
        ms.Like.objects.create(user=self.ana, task=self.hidden)  # ajena y oculta: nadie más la ve
        mine = self.activity("ana", self.ana, "likes")
        self.assertEqual(mine["level"], "private")
        self.assertEqual(mine["levels"]["likes"], "private")
        self.assertEqual(mine["levels"]["verifications"], "public")
        self.assertFalse(mine["feed_public"])
        self.assertEqual([item["task"]["title"] for item in mine["items"]], ["Guía de becas"])

        other = self.activity("luis", self.ana, "likes")
        self.assertTrue(other["hidden"])
        self.assertNotIn("levels", other)
        self.assertEqual(other["items"], [])

        self.assertEqual(self.set_level("ana", "likes", "public").status_code, 200)
        self.assertEqual([item["task"]["title"] for item in self.activity("luis", self.ana, "likes")["items"]], ["Guía de becas"])
        # Solo el dueño cambia su privacidad.
        forbidden = self.clients["luis"].patch(
            reverse("user-activity", kwargs={"user_id": self.ana.pk}), {"kind": "likes", "level": "private"}, format="json",
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_subscribers_level_and_app_subscription_for_likes(self):
        ms.Like.objects.create(user=self.ana, task=self.task)
        ms.TaskSave.objects.create(user=self.ana, task=self.task)
        self.set_level("ana", "likes", "subscribers")
        self.set_level("ana", "saves", "subscribers")
        locked = self.activity("luis", self.ana, "likes")
        self.assertTrue(locked["hidden"])
        self.assertEqual(locked["level"], "subscribers")
        self.assertEqual(locked["paid_kinds"], ["likes", "saves"])

        # Sus suscriptores ven lo que está en modo de paga.
        self.subscribe(self.luis, self.ana)
        self.assertEqual(self.activity("luis", self.ana, "likes")["count"], 1)
        self.assertEqual(self.activity("luis", self.ana, "saves")["count"], 1)

        # Con suscripción en la app (sin pagarle a ella) solo se ven los me gusta.
        ms.Profile.objects.update_or_create(user=self.eva, defaults={"subscriptionActive": True})
        self.assertEqual(self.activity("eva", self.ana, "likes")["count"], 1)
        self.assertTrue(self.activity("eva", self.ana, "saves")["hidden"])

        # Una suscripción vencida ya no cuenta.
        ms.Subscription.objects.update(current_period_end=timezone.now() - timedelta(days=1))
        self.assertTrue(self.activity("luis", self.ana, "saves")["hidden"])

    def test_everything_together_in_order(self):
        ms.Like.objects.create(user=self.ana, task=self.task)
        ms.TaskSave.objects.create(user=self.ana, task=self.task)
        ms.TaskSave.objects.create(user=self.ana, task=ms.Task.objects.create(user=self.luis, title="Privada", pch="consejos"), is_private=True)
        ms.Repost.objects.create(user=self.ana, task=self.task)
        ms.SharedTask.objects.create(task=self.task, shared_by=self.ana, description="Léanla")
        ms.Follow.objects.create(follower=self.ana, following=self.luis)
        ms.pFavorito.objects.create(user=self.ana, perfil=self.luis)
        ms.Favorito.objects.create(user=self.ana, task=self.task)
        ms.UserRecommendation.objects.create(recommender=self.ana, recommended=self.luis, comment="Sabe mucho")

        mine = self.activity("ana", self.ana)
        kinds = [item["kind"] for item in mine["items"]]
        self.assertEqual(set(kinds), {"likes", "saves", "reposts", "shares", "follows", "favorites", "recommendations"})
        self.assertEqual(kinds.count("saves"), 2)
        times = [item["created_at"] for item in mine["items"]]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertEqual(mine["kinds"], ["likes", "comments", "saves", "reposts", "shares", "follows", "favorites", "recommendations", "verifications"])

        # Los demás: solo lo que es público (impulsos, compartidos, seguidos y recomendaciones).
        other = self.activity("luis", self.ana)
        self.assertEqual(other["kinds"], ["reposts", "shares", "follows", "recommendations", "verifications"])
        self.assertEqual({item["kind"] for item in other["items"]}, {"reposts", "shares", "follows", "recommendations"})
        share = next(item for item in other["items"] if item["kind"] == "shares")
        self.assertEqual(share["text"], "Léanla")

        # Una guardada privada no la ve nadie más, aunque sus guardados sean públicos.
        self.set_level("ana", "saves", "public")
        saves = self.activity("luis", self.ana, "saves")
        self.assertEqual([item["task"]["title"] for item in saves["items"]], ["Guía de becas"])

    def test_comments_on_posts_and_forum(self):
        ms.NewPeticionCommentPost.objects.create(created_by=self.ana, post=self.task, text="Me sirvió mucho")
        thread = ms.Postt.objects.create(user=self.luis, title="Dudas de becas", content="¿alguien?")
        reply = ms.Postt.objects.create(user=self.ana, content="Yo te ayudo", parent=thread)
        ms.Postt.objects.create(user=self.ana, content="Otra", parent=reply)
        self.set_level("ana", "comments", "public")
        data = self.activity("luis", self.ana, "comments")
        self.assertEqual(data["count"], 3)
        places = {(item["where"], item.get("task", {}).get("title") or item["forum_post"]["title"]) for item in data["items"]}
        self.assertEqual(places, {("task", "Guía de becas"), ("forum", "Dudas de becas")})

    def test_verifications_are_recorded_and_public_by_default(self):
        response = self.clients["admin"].post(reverse("admin-verify-user", kwargs={"user_id": self.ana.pk}), {"is_verified": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        received = self.activity("luis", self.ana, "verifications")
        self.assertEqual(received["level"], "public")
        self.assertEqual(
            [(item["direction"], item["user"]["username"]) for item in received["items"]], [("received", "admin")],
        )
        given = self.activity("luis", self.admin, "verifications")
        self.assertEqual([(item["direction"], item["user"]["username"]) for item in given["items"]], [("given", "ana")])

        self.clients["admin"].post(reverse("admin-verify-user", kwargs={"user_id": self.ana.pk}), {"is_verified": False}, format="json")
        self.assertEqual(self.activity("ana", self.ana, "verifications")["items"], [])

    def test_favorites_and_recommendations_start_like_their_profile_lists(self):
        profile, _ = ms.Profile.objects.get_or_create(user=self.ana)
        profile.recommendations_public = False
        profile.favorite_profiles_public = True
        profile.save()
        levels = self.activity("ana", self.ana)["levels"]
        self.assertEqual((levels["favorites"], levels["recommendations"]), ("public", "private"))

    def test_bad_requests(self):
        url = reverse("user-activity", kwargs={"user_id": self.ana.pk})
        self.assertEqual(self.clients["ana"].get(url, {"kind": "todo"}).status_code, 400)
        self.assertEqual(self.clients["ana"].patch(url, {"kind": "likes", "level": "amigos"}, format="json").status_code, 400)
        # El formato anterior (sí / no) sigue funcionando.
        response = self.clients["ana"].patch(url, {"kind": "likes", "public": True}, format="json")
        self.assertEqual(response.data["levels"]["likes"], "public")
