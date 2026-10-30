from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class TaskSeriesTests(TestCase):
    """Anterior / siguiente recomendado: el autor elige qué ver después (series, podcasts)."""

    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x", username="ana")
        self.luis = User.objects.create_user(email="luis@example.com", password="x", username="luis")
        self.first = ms.Task.objects.create(user=self.ana, title="Parte 1", pch="consejos")
        self.second = ms.Task.objects.create(user=self.ana, title="Parte 2", pch="consejos")
        self.ana_client = APIClient()
        self.ana_client.force_authenticate(self.ana)
        self.luis_client = APIClient()
        self.luis_client.force_authenticate(self.luis)

    def detail(self, client, task):
        return client.get(reverse("task-detail", kwargs={"id": task.id})).data

    def test_next_and_previous_show_in_the_detail(self):
        response = self.ana_client.patch(
            reverse("task-detail", kwargs={"id": self.first.id}), {"next_task": str(self.second.id)}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        first = self.detail(self.luis_client, self.first)
        self.assertEqual(first["next_task_info"]["title"], "Parte 2")
        self.assertIsNone(first["previous_task_info"])
        second = self.detail(self.luis_client, self.second)
        self.assertEqual(second["previous_task_info"]["title"], "Parte 1")
        # En el feed no se calculan (solo en el detalle).
        feed = self.luis_client.get(reverse("task-list-create")).data["results"]
        self.assertTrue(all(item["next_task_info"] is None for item in feed))

        # Quitarlo.
        self.ana_client.patch(reverse("task-detail", kwargs={"id": self.first.id}), {"next_task": None}, format="json")
        self.assertIsNone(self.detail(self.luis_client, self.first)["next_task_info"])

    def test_author_chooses_the_previous_one_too(self):
        third = ms.Task.objects.create(user=self.ana, title="Parte 3", pch="consejos")
        # Sin elegir: el anterior es el que la recomienda como siguiente.
        self.first.next_task = third
        self.first.save(update_fields=["next_task"])
        derived = self.detail(self.luis_client, third)["previous_task_info"]
        self.assertEqual((derived["title"], derived["chosen"]), ("Parte 1", False))

        # Elegido por su autor: manda ése.
        response = self.ana_client.patch(
            reverse("task-detail", kwargs={"id": third.id}), {"previous_task": str(self.second.id)}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        chosen = self.detail(self.luis_client, third)["previous_task_info"]
        self.assertEqual((chosen["title"], chosen["chosen"]), ("Parte 2", True))

        self.assertEqual(self.ana_client.patch(
            reverse("task-detail", kwargs={"id": third.id}), {"previous_task": str(third.id)}, format="json",
        ).status_code, 400)

    def test_rules_and_hidden_next(self):
        own = self.ana_client.patch(
            reverse("task-detail", kwargs={"id": self.first.id}), {"next_task": str(self.first.id)}, format="json",
        )
        self.assertEqual(own.status_code, 400)
        hidden = ms.Task.objects.create(user=self.luis, title="Oculta", pch="consejos", is_hidden=True)
        response = self.ana_client.patch(
            reverse("task-detail", kwargs={"id": self.first.id}), {"next_task": str(hidden.id)}, format="json",
        )
        self.assertEqual(response.status_code, 400)

        # Si después se oculta, quien no la ve no la recibe como siguiente.
        self.first.next_task = self.second
        self.first.save(update_fields=["next_task"])
        self.second.is_hidden = True
        self.second.save(update_fields=["is_hidden"])
        self.assertIsNone(self.detail(self.luis_client, self.first)["next_task_info"])
        self.assertEqual(self.detail(self.ana_client, self.first)["next_task_info"]["title"], "Parte 2")

    def test_empty_task_search_suggests_my_recent_posts(self):
        ms.Task.objects.create(user=self.luis, title="Ajena", pch="consejos")
        data = self.ana_client.get(reverse("directory-search"), {"q": "", "scope": "tasks"}).data
        self.assertEqual([item["title"] for item in data["tasks"]], ["Parte 2", "Parte 1"])

    def patch(self, client, task, **body):
        response = client.patch(reverse("task-detail", kwargs={"id": task.id}), body, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_links_work_both_ways_and_sync_between_my_posts(self):
        # Elegir el anterior en la Parte 2 hace que la Parte 1 muestre a la 2 como siguiente.
        self.patch(self.ana_client, self.second, previous_task=str(self.first.id))
        self.first.refresh_from_db()
        self.assertEqual(self.first.next_task_id, self.second.id)  # se guardó en las dos (ambas son de Ana)
        first = self.detail(self.luis_client, self.first)
        self.assertEqual((first["next_task_info"]["title"], first["next_task_info"]["chosen"]), ("Parte 2", True))

        # Quitarlo en una lo quita en las dos.
        self.patch(self.ana_client, self.first, next_task=None)
        self.second.refresh_from_db()
        self.assertIsNone(self.second.previous_task_id)
        self.assertIsNone(self.detail(self.luis_client, self.second)["previous_task_info"])

    def test_someone_elses_post_is_linked_without_changing_it(self):
        other = ms.Task.objects.create(user=self.luis, title="De Luis", pch="consejos")
        self.patch(self.ana_client, self.first, previous_task=str(other.id))
        other.refresh_from_db()
        self.assertIsNone(other.next_task_id)  # no se toca la publicación de otra persona
        derived = self.detail(self.ana_client, other)["next_task_info"]
        self.assertEqual((derived["title"], derived["chosen"]), ("Parte 1", False))

    def test_whole_series_in_order(self):
        third = ms.Task.objects.create(user=self.ana, title="Parte 3", pch="consejos")
        self.patch(self.ana_client, self.first, next_task=str(self.second.id))
        self.patch(self.ana_client, third, previous_task=str(self.second.id))
        series = self.detail(self.luis_client, self.second)["series"]
        self.assertEqual([(part["title"], part["current"]) for part in series],
                         [("Parte 1", False), ("Parte 2", True), ("Parte 3", False)])
        lonely = ms.Task.objects.create(user=self.ana, title="Sola", pch="consejos")
        self.assertIsNone(self.detail(self.luis_client, lonely)["series"])
