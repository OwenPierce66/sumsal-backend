from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class ForumPrivacyTests(TestCase):
    """Foro privado: por grupo, para seguidores, para suscriptores (de pago) o para invitados."""

    def setUp(self):
        self.users = {}
        self.clients = {}
        for name in ("ana", "luis", "eva", "beto"):
            user = User.objects.create_user(email=f"{name}@example.com", password="x", username=name)
            client = APIClient()
            client.force_authenticate(user)
            self.users[name] = user
            self.clients[name] = client
        self.list_url = reverse("post-list-create")

    def post(self, who="ana", **body):
        return self.clients[who].post(self.list_url, {"title": "Hilo", "content": "hola", **body}, format="json")

    def titles(self, who, **params):
        return [item["title"] for item in self.clients[who].get(self.list_url, params).data["results"]]

    def detail_status(self, who, post_id):
        return self.clients[who].get(reverse("post-detail", kwargs={"id": post_id})).status_code

    def test_followers_and_subscribers_only(self):
        followers = self.post(title="Para seguidores", visibility="followers")
        self.assertEqual(followers.status_code, 201, followers.data)
        subscribers = self.post(title="De pago", visibility="subscribers").data
        self.post(title="Para todos")
        ms.Follow.objects.create(follower=self.users["luis"], following=self.users["ana"])
        ms.Subscription.objects.create(
            subscriber=self.users["eva"], recipient=self.users["ana"], amount_cents=5000, currency="mxn",
            status="active", current_period_end=timezone.now() + timedelta(days=20),
        )

        self.assertEqual(set(self.titles("luis")), {"Para seguidores", "Para todos"})
        self.assertEqual(set(self.titles("eva")), {"De pago", "Para todos"})
        self.assertEqual(self.titles("beto"), ["Para todos"])
        self.assertEqual(set(self.titles("ana")), {"Para seguidores", "De pago", "Para todos"})
        self.assertEqual(self.detail_status("beto", subscribers["id"]), 404)
        self.assertEqual(self.detail_status("eva", subscribers["id"]), 200)

        # Una suscripción vencida ya no da acceso.
        ms.Subscription.objects.filter(subscriber=self.users["eva"]).update(current_period_end=timezone.now() - timedelta(days=1))
        self.assertEqual(self.titles("eva"), ["Para todos"])

    def test_invited_only_with_notification_and_replies_inherit(self):
        self.assertEqual(self.post(visibility="invited").status_code, 400)  # sin invitados
        response = self.post(title="Privado", visibility="invited", invited_user_ids=[str(self.users["luis"].pk)])
        self.assertEqual(response.status_code, 201, response.data)
        post_id = response.data["id"]
        self.assertEqual([u["username"] for u in response.data["invited_users"]], ["luis"])
        self.assertTrue(ms.Notification.objects.filter(recipient=self.users["luis"], notification_type="forum_invite").exists())

        self.assertEqual(self.titles("luis"), ["Privado"])
        self.assertEqual(self.titles("eva"), [])
        luis_view = self.clients["luis"].get(reverse("post-detail", kwargs={"id": post_id})).data
        self.assertEqual(luis_view["invited_users"], [])  # la lista solo la ve el autor

        reply = self.clients["luis"].post(self.list_url, {"content": "gracias", "parent": post_id}, format="json")
        self.assertEqual(reply.status_code, 201, reply.data)
        self.assertEqual(self.detail_status("eva", reply.data["id"]), 404)
        outsider = self.clients["eva"].post(self.list_url, {"content": "hola", "parent": post_id}, format="json")
        self.assertEqual(outsider.status_code, 400)
        self.assertEqual(self.clients["eva"].post(reverse("post-like", kwargs={"post_id": post_id})).status_code, 404)

    def test_group_forum(self):
        group = ms.CommunityGroup.objects.create(name="Huertos", is_private=True, created_by=self.users["ana"])
        ms.CommunityGroupMember.objects.create(group=group, user=self.users["ana"], role="owner", status="active")
        ms.CommunityGroupMember.objects.create(group=group, user=self.users["luis"], role="member", status="active")

        self.assertEqual(self.post(who="eva", title="Intruso", group=str(group.id)).status_code, 400)
        created = self.post(title="Del grupo", group=str(group.id))
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["group_info"]["name"], "Huertos")
        self.post(title="General")

        self.assertEqual(self.titles("luis", group=str(group.id)), ["Del grupo"])
        self.assertEqual(self.titles("eva", group=str(group.id)), [])
        # El foro general no mezcla los posts de grupos.
        self.assertEqual(self.titles("luis"), ["General"])
        reply = self.clients["luis"].post(self.list_url, {"content": "yo voy", "parent": created.data["id"]}, format="json")
        self.assertEqual(str(reply.data["group"]), str(group.id))
