from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()
Member = ms.CommunityGroupMember


class CommunityGroupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.users = {}
        self.clients = {}
        for name in ("ana", "beto", "caro", "dani"):
            user = User.objects.create_user(email=f"{name}@example.com", password="x", username=name)
            client = APIClient()
            client.force_authenticate(user)
            self.users[name], self.clients[name] = user, client

    # ── Helpers ──────────────────────────────────────────────────────────

    def create_group(self, by="ana", **body):
        body.setdefault("name", "Huertos urbanos")
        body.setdefault("description", "Cultivar en la ciudad")
        body.setdefault("rules", "1. Respeto")
        response = self.clients[by].post(reverse("group-list"), body, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def join(self, group, who):
        return self.clients[who].post(reverse("group-join", kwargs={"group_id": group["id"]})).data

    def post_task(self, group, who, **extra):
        body = {"title": f"Publicación de {who}", "pch": "consejos", "group": group["id"], **extra}
        return self.clients[who].post(reverse("task-list-create"), body, format="multipart")

    def member(self, group, who):
        return Member.objects.get(group_id=group["id"], user=self.users[who])

    @staticmethod
    def ids(response):
        data = response.data
        items = data.get("results", data) if isinstance(data, dict) else data
        return {str(item.get("id")) for item in items}

    def feed_ids(self, who):
        cache.clear()
        return self.ids(self.clients[who].get(reverse("feed")))

    def group_task_ids(self, group, who):
        return self.ids(self.clients[who].get(reverse("group-tasks", kwargs={"group_id": group["id"]})))

    def notified(self, who, kind):
        return ms.Notification.objects.filter(recipient=self.users[who], notification_type=kind).count()

    # ── Grupo y membresía ────────────────────────────────────────────────

    def test_anyone_creates_a_group_and_becomes_its_known_admin(self):
        group = self.create_group(name="  Huertos   urbanos ")
        self.assertEqual(group["name"], "Huertos urbanos")
        self.assertEqual((group["my_role"], group["is_admin"], group["members_count"]), ("owner", True, 1))
        self.assertEqual([a["user"]["username"] for a in group["admins"]], ["ana"])

        seen_by_beto = self.clients["beto"].get(reverse("group-detail", kwargs={"group_id": group["id"]})).data
        self.assertEqual(seen_by_beto["rules"], "1. Respeto")
        self.assertEqual([a["user"]["username"] for a in seen_by_beto["admins"]], ["ana"])
        self.assertFalse(seen_by_beto["is_admin"])

    def test_public_group_is_joined_at_once_private_needs_an_admin(self):
        public = self.create_group()
        self.assertEqual(self.join(public, "beto")["my_status"], "active")

        private = self.create_group(name="Club privado", is_private=True)
        self.assertEqual(self.join(private, "beto")["my_status"], "pending")
        self.assertEqual(self.notified("ana", "group_join_request"), 1)
        requests = self.clients["ana"].get(
            reverse("group-members", kwargs={"group_id": private["id"]}), {"status": "pending"},
        ).data
        self.assertEqual([r["user"]["username"] for r in requests], ["beto"])
        # Quien no es admin no ve las solicitudes.
        self.assertEqual(self.clients["caro"].get(
            reverse("group-members", kwargs={"group_id": private["id"]}), {"status": "pending"},
        ).status_code, 403)

        url = reverse("group-member-detail", kwargs={"group_id": private["id"], "user_id": self.users["beto"].id})
        self.assertEqual(self.clients["ana"].patch(url, {"status": "active"}, format="json").status_code, 200)
        self.assertEqual(self.member(private, "beto").status, "active")
        self.assertEqual(self.notified("beto", "group_join_approved"), 1)

    def test_my_groups_and_search(self):
        huertos = self.create_group()
        self.create_group(by="caro", name="Ajedrez", description="Partidas")
        self.join(huertos, "beto")
        mine = self.clients["beto"].get(reverse("group-list"), {"mine": "1"}).data
        self.assertEqual([g["name"] for g in mine], ["Huertos urbanos"])
        found = self.clients["beto"].get(reverse("group-list"), {"q": "partida"}).data
        self.assertEqual([g["name"] for g in found], ["Ajedrez"])

    # ── Publicaciones con revisión ───────────────────────────────────────

    def test_member_post_waits_for_an_admin_and_then_is_published(self):
        group = self.create_group()
        self.join(group, "beto")
        response = self.post_task(group, "beto")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["group_status"], "pending")
        self.assertEqual(response.data["group_info"]["name"], "Huertos urbanos")
        task_id = str(response.data["id"])
        self.assertEqual(self.notified("ana", "group_post_pending"), 1)

        # Pendiente: no se ve en el grupo, ni en el feed, ni en el detalle para otros.
        self.assertNotIn(task_id, self.group_task_ids(group, "caro"))
        self.assertNotIn(task_id, self.feed_ids("caro"))
        self.assertNotIn(task_id, self.feed_ids("beto"))
        detail = reverse("task-detail", kwargs={"id": task_id})
        self.assertEqual(self.clients["caro"].get(detail).status_code, 404)
        # Su autor sí la ve (detalle y su perfil) y el admin la revisa.
        self.assertEqual(self.clients["beto"].get(detail).status_code, 200)
        own_profile = self.clients["beto"].get(reverse("user-my-tasks"))
        self.assertIn(task_id, self.ids(own_profile))
        self.assertEqual(self.clients["ana"].get(detail).status_code, 200)
        pending = self.clients["ana"].get(reverse("group-pending-tasks", kwargs={"group_id": group["id"]}))
        self.assertEqual(self.ids(pending), {task_id})

        review = reverse("group-task-review", kwargs={"group_id": group["id"], "task_id": task_id})
        self.assertEqual(self.clients["beto"].post(review, {"approve": True}, format="json").status_code, 403)
        self.assertEqual(self.clients["ana"].post(review, {"approve": True}, format="json").status_code, 200)

        self.assertIn(task_id, self.group_task_ids(group, "caro"))
        self.assertIn(task_id, self.feed_ids("caro"))
        self.assertEqual(self.clients["caro"].get(detail).status_code, 200)
        self.assertEqual(self.notified("beto", "group_post_approved"), 1)
        # La revisión ya no espera en las notificaciones del admin.
        self.assertEqual(self.notified("ana", "group_post_pending"), 0)

    def test_rejected_post_stays_out_and_its_author_knows(self):
        group = self.create_group()
        self.join(group, "beto")
        task_id = str(self.post_task(group, "beto").data["id"])
        review = reverse("group-task-review", kwargs={"group_id": group["id"], "task_id": task_id})
        self.clients["ana"].post(review, {"approve": False}, format="json")

        self.assertNotIn(task_id, self.group_task_ids(group, "caro"))
        self.assertNotIn(task_id, self.feed_ids("caro"))
        self.assertEqual(self.notified("beto", "group_post_rejected"), 1)
        mine = self.clients["beto"].get(reverse("group-pending-tasks", kwargs={"group_id": group["id"]})).data
        self.assertEqual([(str(t["id"]), t["group_status"]) for t in mine["results"]], [(task_id, "rejected")])
        self.assertEqual(self.clients["ana"].post(review, {"approve": True}, format="json").status_code, 403)

    def test_admin_posts_are_approved_without_review(self):
        group = self.create_group()
        response = self.post_task(group, "ana")
        self.assertEqual(response.data["group_status"], "approved")
        self.assertIn(str(response.data["id"]), self.group_task_ids(group, "beto"))

    def test_only_members_post_and_group_posts_are_never_hidden(self):
        group = self.create_group()
        self.assertEqual(self.post_task(group, "beto").status_code, 400)
        self.join(group, "beto")
        self.assertEqual(self.post_task(group, "beto", is_hidden="true").status_code, 400)
        self.assertFalse(ms.Task.objects.filter(user=self.users["beto"]).exists())

    def test_private_group_posts_are_only_for_its_members(self):
        group = self.create_group(is_private=True)
        task_id = str(self.post_task(group, "ana").data["id"])
        self.join(group, "beto")
        url = reverse("group-member-detail", kwargs={"group_id": group["id"], "user_id": self.users["beto"].id})
        self.clients["ana"].patch(url, {"status": "active"}, format="json")

        self.assertIn(task_id, self.feed_ids("beto"))
        self.assertIn(task_id, self.group_task_ids(group, "beto"))
        self.assertNotIn(task_id, self.feed_ids("caro"))
        self.assertEqual(
            self.clients["caro"].get(reverse("group-tasks", kwargs={"group_id": group["id"]})).status_code, 403,
        )
        self.assertEqual(self.clients["caro"].get(reverse("task-detail", kwargs={"id": task_id})).status_code, 404)

    # ── Admins ───────────────────────────────────────────────────────────

    def test_any_admin_names_and_removes_admins_but_not_the_creator(self):
        group = self.create_group()
        for who in ("beto", "caro", "dani"):
            self.join(group, who)

        def role(actor, who, value):
            url = reverse("group-member-detail", kwargs={"group_id": group["id"], "user_id": self.users[who].id})
            return self.clients[actor].patch(url, {"role": value}, format="json")

        self.assertEqual(role("caro", "dani", "admin").status_code, 403)
        self.assertEqual(role("ana", "beto", "admin").status_code, 200)
        self.assertEqual(self.notified("beto", "group_admin"), 1)
        # Beto, que no es el creador, también nombra y quita admins.
        self.assertEqual(role("beto", "caro", "admin").status_code, 200)
        self.assertEqual(role("caro", "beto", "member").status_code, 200)
        self.assertEqual(self.member(group, "beto").role, "member")
        self.assertEqual(role("caro", "ana", "member").status_code, 403)
        self.assertEqual(self.member(group, "ana").role, "owner")

        # Para expulsar a un admin primero se le quita el rol; al creador, nunca.
        def remove(actor, who):
            url = reverse("group-member-detail", kwargs={"group_id": group["id"], "user_id": self.users[who].id})
            return self.clients[actor].delete(url)

        self.assertEqual(remove("ana", "caro").status_code, 403)
        self.assertEqual(remove("caro", "dani").status_code, 204)
        self.assertEqual(remove("caro", "ana").status_code, 403)

    def test_creator_cannot_leave_but_can_delete_the_group(self):
        group = self.create_group()
        self.join(group, "beto")
        leave = reverse("group-leave", kwargs={"group_id": group["id"]})
        self.assertEqual(self.clients["ana"].post(leave).status_code, 400)
        self.assertEqual(self.clients["beto"].post(leave).data["my_status"], None)

        detail = reverse("group-detail", kwargs={"group_id": group["id"]})
        self.assertEqual(self.clients["beto"].delete(detail).status_code, 403)
        self.assertEqual(self.clients["ana"].patch(detail, {"rules": "Nuevas"}, format="json").data["rules"], "Nuevas")
        self.assertEqual(self.clients["ana"].delete(detail).status_code, 204)
        self.assertFalse(ms.CommunityGroup.objects.exists())
