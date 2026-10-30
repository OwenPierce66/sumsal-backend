from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class SaveCollectionTests(TestCase):
    """Colecciones (álbumes) dentro de guardados."""

    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x", username="ana")
        self.luis = User.objects.create_user(email="luis@example.com", password="x", username="luis")
        self.becas = ms.Task.objects.create(user=self.luis, title="Guía de becas", pch="consejos")
        self.huerto = ms.Task.objects.create(user=self.luis, title="Huerto", pch="consejos")
        self.ana_client = APIClient()
        self.ana_client.force_authenticate(self.ana)
        self.luis_client = APIClient()
        self.luis_client.force_authenticate(self.luis)

    def create(self, name="Estudios", **extra):
        return self.ana_client.post(reverse("collections"), {"name": name, **extra}, format="json")

    def add(self, collection_id, task):
        return self.ana_client.post(
            reverse("collection-items", kwargs={"collection_id": collection_id}), {"task_id": str(task.id)}, format="json",
        )

    def test_create_add_and_list(self):
        response = self.create("  Estudios  ")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["name"], response.data["is_private"]), ("Estudios", True))
        collection_id = response.data["id"]
        self.assertEqual(self.create("Estudios").status_code, 400)  # nombre repetido

        # Agregar la guarda si faltaba.
        self.assertEqual(self.add(collection_id, self.becas).status_code, 201)
        self.assertTrue(ms.TaskSave.objects.filter(user=self.ana, task=self.becas).exists())
        self.add(collection_id, self.becas)  # no se duplica
        detail = self.ana_client.get(reverse("collection-detail", kwargs={"collection_id": collection_id})).data
        self.assertEqual([item["task"]["title"] for item in detail["items"]], ["Guía de becas"])

        marks = self.ana_client.get(reverse("task-collections", kwargs={"task_id": self.becas.id})).data
        self.assertEqual([(item["name"], item["contains"]) for item in marks], [("Estudios", True)])

        self.ana_client.delete(reverse("collection-item", kwargs={"collection_id": collection_id, "task_id": self.becas.id}))
        self.assertEqual(self.ana_client.get(reverse("collections")).data[0]["count"], 0)

    def test_privacy_for_others(self):
        collection_id = self.create("Para todos", is_private=False).data["id"]
        private_id = self.create("Mía").data["id"]
        self.add(collection_id, self.becas)
        self.add(collection_id, self.huerto)
        ms.TaskSave.objects.filter(user=self.ana, task=self.huerto).update(is_private=True)

        visible = self.luis_client.get(reverse("collections-user", kwargs={"user_id": self.ana.pk})).data
        self.assertEqual([(item["name"], item["count"]) for item in visible], [("Para todos", 1)])
        detail = self.luis_client.get(reverse("collection-detail", kwargs={"collection_id": collection_id})).data
        self.assertEqual([item["task"]["title"] for item in detail["items"]], ["Guía de becas"])
        self.assertEqual(self.luis_client.get(reverse("collection-detail", kwargs={"collection_id": private_id})).status_code, 404)
        # Nadie más la cambia ni la borra.
        self.assertEqual(self.luis_client.delete(reverse("collection-detail", kwargs={"collection_id": collection_id})).status_code, 404)

    def test_rename_and_unsave_removes_it_from_collections(self):
        collection_id = self.create().data["id"]
        self.add(collection_id, self.becas)
        renamed = self.ana_client.patch(
            reverse("collection-detail", kwargs={"collection_id": collection_id}), {"name": "Becas", "is_private": False}, format="json",
        )
        self.assertEqual((renamed.data["name"], renamed.data["is_private"]), ("Becas", False))
        self.ana_client.delete(reverse("task-save", kwargs={"task_id": self.becas.id}))
        self.assertFalse(ms.SaveCollectionItem.objects.exists())
