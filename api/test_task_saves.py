from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import Favorito, Notification, Profile, TaskCategoryPin, TaskSave, Task, pFavorito

User = get_user_model()


class TaskSaveHierarchyTests(TestCase):
    """Guardar -> Favorito -> Top 5 (general y por categoría), con "solo para mí"."""

    def setUp(self):
        self.user = User.objects.create_user(email="saver@example.com", password="pass", username="saver")
        self.author = User.objects.create_user(email="author@example.com", password="pass", username="author")
        self.visitor = User.objects.create_user(email="visitor@example.com", password="pass", username="visitor")
        self.task = Task.objects.create(user=self.author, title="Huerto", categories="Salud, Procesando, Ejercicio")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def save_url(self, task=None):
        return reverse("task-save", kwargs={"task_id": (task or self.task).id})

    def favorite(self, task=None):
        return self.client.post(reverse("favorito-add"), {"task_id": str((task or self.task).id)}, format="json")

    def category_pin(self, task, category, pinned=True):
        return self.client.post(
            reverse("favorite-category-pin"),
            {"task_id": str(task.id), "category": category, "is_pinned": pinned},
            format="json",
        )

    def test_save_private_then_favorite_keeps_it_private(self):
        response = self.client.post(self.save_url(), {"is_private": True}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["saved"])
        self.assertTrue(response.data["is_private"])
        self.assertFalse(response.data["favorite"])
        self.assertEqual(response.data["categories"], ["Salud", "Ejercicio"])

        self.favorite()
        state = self.client.get(self.save_url()).data
        self.assertTrue(state["favorite"])
        self.assertTrue(state["is_private"])

        # Quitar de favoritos la deja guardada.
        self.favorite()
        state = self.client.get(self.save_url()).data
        self.assertFalse(state["favorite"])
        self.assertTrue(state["saved"])

    def test_favoriting_or_pinning_saves_and_unsaving_removes_everything(self):
        self.client.post(reverse("favorite-pin"), {"type": "task", "target_id": str(self.task.id)}, format="json")
        self.assertTrue(TaskSave.objects.filter(user=self.user, task=self.task).exists())
        self.assertEqual(self.category_pin(self.task, "salud").status_code, 200)
        state = self.client.get(self.save_url()).data
        self.assertTrue(state["pinned"])
        self.assertEqual(state["pinned_categories"], ["Salud"])

        response = self.client.delete(self.save_url())
        self.assertFalse(response.data["saved"])
        self.assertFalse(Favorito.objects.filter(user=self.user, task=self.task).exists())
        self.assertFalse(TaskCategoryPin.objects.exists())

    def test_one_notification_per_step(self):
        self.favorite()
        types = list(Notification.objects.filter(recipient=self.author).values_list("notification_type", flat=True))
        self.assertEqual(types, ["task_favorite"])

        other = Task.objects.create(user=self.author, title="Otra")
        self.client.post(self.save_url(other))
        self.assertTrue(Notification.objects.filter(recipient=self.author, notification_type="task_save").exists())

    def test_category_top_five(self):
        self.assertEqual(self.category_pin(self.task, "Procesando").status_code, 400)
        self.assertEqual(self.category_pin(self.task, "Cocina").status_code, 400)

        tasks = [Task.objects.create(user=self.author, title=f"T{i}", categories="Salud") for i in range(6)]
        for task in tasks:
            self.assertEqual(self.category_pin(task, "SALUD").status_code, 200)
        pinned = list(
            TaskCategoryPin.objects.filter(favorite__user=self.user, category="Salud")
            .order_by("position").values_list("favorite__task__title", flat=True)
        )
        # Ya había 5: el quinto sale para hacerle lugar al nuevo, como en el top 5 general.
        self.assertEqual(pinned, ["T0", "T1", "T2", "T3", "T5"])
        self.assertTrue(Favorito.objects.filter(user=self.user, task=tasks[5]).exists())

        order = [str(tasks[i].id) for i in (5, 3, 2, 1, 0)]
        response = self.client.patch(reverse("favorite-category-pin"), {"category": "salud", "order": order}, format="json")
        self.assertEqual(response.status_code, 200)
        pinned = list(
            TaskCategoryPin.objects.filter(category="Salud").order_by("position").values_list("favorite__task__title", flat=True)
        )
        self.assertEqual(pinned, ["T5", "T3", "T2", "T1", "T0"])

        self.category_pin(tasks[3], "Salud", pinned=False)
        positions = list(TaskCategoryPin.objects.filter(category="Salud").order_by("position").values_list("position", flat=True))
        self.assertEqual(positions, [0, 1, 2, 3])

    def test_relations_include_tasks(self):
        self.client.post(self.save_url(), {"is_private": True}, format="json")
        self.client.post(reverse("favorite-pin"), {"type": "task", "target_id": str(self.task.id)}, format="json")
        self.category_pin(self.task, "Ejercicio")
        data = self.client.get(reverse("user-my-relations")).data
        task_id = str(self.task.id)
        self.assertIn(task_id, data["saved_tasks"])
        self.assertIn(task_id, data["private_tasks"])
        self.assertIn(task_id, data["favorite_tasks"])
        self.assertIn(task_id, data["pinned_tasks"])
        self.assertEqual(data["task_category_pins"][task_id], ["Ejercicio"])

    def test_collection_shows_levels_and_hides_private_from_others(self):
        saved_only = Task.objects.create(user=self.author, title="Solo guardada")
        secret = Task.objects.create(user=self.author, title="Secreta", categories="Salud")
        self.client.post(self.save_url(saved_only))
        self.favorite()
        self.client.post(self.save_url(secret), {"is_private": True}, format="json")
        self.favorite(secret)
        self.category_pin(self.task, "Salud")
        self.category_pin(secret, "Salud")

        own = self.client.get(reverse("favorite-collection")).data
        self.assertEqual({item["task"]["title"] for item in own["tasks"]}, {"Huerto", "Secreta"})
        self.assertEqual([item["task"]["title"] for item in own["saved"]], ["Solo guardada"])
        secret_item = next(item for item in own["tasks"] if item["task"]["title"] == "Secreta")
        self.assertTrue(secret_item["is_private"])
        self.assertEqual(secret_item["pinned_categories"], ["Salud"])
        self.assertEqual(len(own["category_pins"]["Salud"]), 2)

        visitor = APIClient()
        visitor.force_authenticate(self.visitor)
        url = reverse("favorite-collection-user", kwargs={"user_id": self.user.id})
        hidden = visitor.get(url).data
        self.assertEqual(hidden["tasks"], [])

        Profile.objects.update_or_create(user=self.user, defaults={"favorite_tasks_public": True})
        public = visitor.get(url).data
        self.assertEqual([item["task"]["title"] for item in public["tasks"]], ["Huerto"])
        self.assertEqual([item["task"]["title"] for item in public["saved"]], ["Solo guardada"])
        self.assertEqual(len(public["category_pins"]["Salud"]), 1)

    def test_top_for_the_profile(self):
        secret = Task.objects.create(user=self.author, title="Secreta", categories="Salud")
        self.client.post(reverse("favorite-pin"), {"type": "task", "target_id": str(self.task.id)}, format="json")
        self.client.post(self.save_url(secret), {"is_private": True}, format="json")
        self.client.post(reverse("favorite-pin"), {"type": "task", "target_id": str(secret.id)}, format="json")
        self.category_pin(self.task, "Salud")
        self.client.post(reverse("favorite-pin"), {"type": "profile", "target_id": str(self.author.id)}, format="json")

        own = self.client.get(reverse("favorites-top")).data
        self.assertTrue(own["is_owner"])
        self.assertEqual([profile["username"] for profile in own["profiles"]], ["author"])
        self.assertEqual([task["title"] for task in own["tasks"]], ["Huerto", "Secreta"])
        self.assertEqual(own["categories"][0]["name"], "Salud")
        self.assertEqual(own["categories"][0]["tasks"][0]["username"], "author")

        visitor = APIClient()
        visitor.force_authenticate(self.visitor)
        url = reverse("favorites-top-user", kwargs={"user_id": self.user.id})
        closed = visitor.get(url).data
        self.assertEqual((closed["profiles"], closed["tasks"], closed["categories"]), ([], [], []))

        Profile.objects.update_or_create(
            user=self.user, defaults={"favorite_tasks_public": True, "favorite_profiles_public": True},
        )
        opened = visitor.get(url).data
        self.assertEqual([profile["username"] for profile in opened["profiles"]], ["author"])
        self.assertEqual([task["title"] for task in opened["tasks"]], ["Huerto"])

    def test_saved_task_can_be_attached_to_a_comment(self):
        post = Task.objects.create(user=self.author, title="Post")
        self.client.post(self.save_url())
        response = self.client.post(
            reverse("task-comments", kwargs={"task_id": post.id}),
            {"text": "mira esta", "aportacion": str(self.task.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
