from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import CategoryP, CommunityGroup, Postt, Task

User = get_user_model()


class ForumCategoryTests(TestCase):
    """El foro trae sus categorías (de la app o propias) y se filtra por niveles como las tareas."""

    def setUp(self):
        self.user = User.objects.create_user(username="writer", email="w@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_post_keeps_its_categories_without_repeats_or_status_tags(self):
        response = self.client.post(reverse("post-list-create"), {
            "title": "Hooks", "content": "duda",
            "categories": " Programación ,React,react, aprobada,Procesando,,Mi tema propio",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["categories"], "Programación,React,Mi tema propio")

        post = Postt.objects.get(pk=response.data["id"])
        response = self.client.patch(reverse("post-detail", kwargs={"id": post.id}), {"categories": "Salud"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["categories"], "Salud")

    def test_filter_by_category_path_puts_the_exact_path_first(self):
        exact = Postt.objects.create(user=self.user, title="exacta", content="x", categories="Programación,React")
        deeper = Postt.objects.create(user=self.user, title="más honda", content="x", categories="Salud,Programación,React")
        Postt.objects.create(user=self.user, title="otra", content="x", categories="Programación")
        Postt.objects.create(user=self.user, title="artificial", content="x", categories="Arte artificial")
        reply = Postt.objects.create(user=self.user, content="resp", parent=exact, categories="Programación,React")

        response = self.client.get(reverse("post-list-create"), {"category": "programación, react"})
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data["results"]]
        self.assertEqual(ids, [exact.id, deeper.id])
        self.assertNotIn(reply.id, ids)

        titles = [item["title"] for item in self.client.get(reverse("post-list-create"), {"category": "Arte"}).data["results"]]
        self.assertEqual(titles, [])

    def test_forum_of_one_user_and_category_together(self):
        other = User.objects.create_user(username="other", email="o@example.com", password="pass")
        mine = Postt.objects.create(user=self.user, title="mío", content="x", categories="Salud")
        Postt.objects.create(user=other, title="ajeno", content="x", categories="Salud")
        Postt.objects.create(user=self.user, title="otro tema", content="x", categories="Arte")
        response = self.client.get(reverse("post-list-create"), {"user": str(self.user.id), "category": "Salud"})
        self.assertEqual([item["id"] for item in response.data["results"]], [mine.id])


class GroupTasksCategoryTests(TestCase):
    def test_group_tasks_filter_by_category(self):
        user = User.objects.create_user(username="member", email="g@example.com", password="pass")
        group = CommunityGroup.objects.create(name="Huertos", created_by=user)
        salud = Task.objects.create(user=user, title="a", categories="Salud,Nutrición", group=group, group_status="approved")
        Task.objects.create(user=user, title="b", categories="Arte", group=group, group_status="approved")
        client = APIClient()
        client.force_authenticate(user)
        response = client.get(reverse("group-tasks", kwargs={"group_id": group.id}), {"category": "Salud"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([item["id"] for item in response.data["results"]], [str(salud.id)])


class UsersInCategoryTests(TestCase):
    """Las categorías de un perfil son las de sus tareas (y su filtro personal)."""

    def setUp(self):
        self.viewer = User.objects.create_user(username="viewer", email="v@example.com", password="pass")
        self.coder = User.objects.create_user(username="coder", email="c@example.com", password="pass")
        self.cook = User.objects.create_user(username="cook", email="k@example.com", password="pass")
        self.hidden = User.objects.create_user(username="hidden", email="h@example.com", password="pass")
        self.manual = User.objects.create_user(username="manual", email="m@example.com", password="pass")
        Task.objects.create(user=self.coder, title="t", categories="Programación,React")
        Task.objects.create(user=self.cook, title="t", categories="Cocina")
        Task.objects.create(user=self.hidden, title="t", categories="Programación,React", is_hidden=True)
        CategoryP.objects.create(user=self.manual, name="Programación")
        self.client = APIClient()
        self.client.force_authenticate(self.viewer)
        self.everyone = [str(u.id) for u in (self.coder, self.cook, self.hidden, self.manual)]

    def matching(self, category, ids=None):
        response = self.client.post(reverse("users-in-category"), {
            "category": category, "user_ids": self.everyone if ids is None else ids,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return set(response.data["user_ids"])

    def test_matches_by_tasks_and_personal_filter(self):
        # La tarea oculta no cuenta, pero su categoría principal ya quedó en el filtro
        # personal del autor (que se ve en su perfil); el subtema React no.
        self.assertEqual(
            self.matching("Programación"),
            {str(self.coder.id), str(self.manual.id), str(self.hidden.id)},
        )
        self.assertEqual(self.matching("programación,React"), {str(self.coder.id)})
        self.assertEqual(self.matching("Cocina"), {str(self.cook.id)})
        self.assertEqual(self.matching(""), set(self.everyone))

    def test_only_checks_the_ids_sent_and_ignores_bad_ones(self):
        self.assertEqual(self.matching("Programación", [str(self.cook.id), "no-es-uuid"]), set())
        response = self.client.post(reverse("users-in-category"), {"category": "x", "user_ids": "nope"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_directory_search_respects_the_category(self):
        response = self.client.get(reverse("directory-search"), {"q": "co", "scope": "profiles", "category": "Cocina"})
        self.assertEqual([item["username"] for item in response.data["profiles"]], ["cook"])
