from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class SharedTasksByTaskTests(TestCase):
    """El modal del menú de 3 puntos lista TODAS las compartidas de una publicación."""

    def setUp(self):
        cache.clear()
        self.reader = User.objects.create_user(
            username="shares-reader", email="shares-reader@example.com", password="test-password"
        )
        self.owner = User.objects.create_user(
            username="shares-owner", email="shares-owner@example.com", password="test-password"
        )
        self.sharer = User.objects.create_user(
            username="shares-sharer", email="shares-sharer@example.com", password="test-password"
        )
        self.other_sharer = User.objects.create_user(
            username="shares-other", email="shares-other@example.com", password="test-password"
        )
        self.task = ms.Task.objects.create(user=self.owner, title="Publicación compartida")
        self.other_task = ms.Task.objects.create(user=self.owner, title="Otra publicación")
        self.client = APIClient()
        self.client.force_authenticate(self.reader)
        self.url = reverse("shared-task-list-create")

    def _ids(self, params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        results = response.data["results"] if isinstance(response.data, dict) else response.data
        return {str(item["id"]) for item in results}

    def test_same_user_can_share_same_task_many_times_with_own_descriptions(self):
        first = ms.SharedTask.objects.create(task=self.task, shared_by=self.sharer, description="Primera")
        second = ms.SharedTask.objects.create(task=self.task, shared_by=self.sharer, description="Segunda")
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(
            ms.SharedTask.objects.filter(task=self.task, shared_by=self.sharer).count(), 2
        )

    def test_task_id_lists_every_share_of_that_task(self):
        a = ms.SharedTask.objects.create(task=self.task, shared_by=self.sharer, description="A")
        b = ms.SharedTask.objects.create(task=self.task, shared_by=self.sharer, description="B")
        c = ms.SharedTask.objects.create(task=self.task, shared_by=self.other_sharer, description="C")
        elsewhere = ms.SharedTask.objects.create(
            task=self.other_task, shared_by=self.sharer, description="Otra"
        )

        ids = self._ids({"task_id": str(self.task.id)})

        self.assertEqual(ids, {str(a.id), str(b.id), str(c.id)})
        self.assertNotIn(str(elsewhere.id), ids)

    def test_invalid_task_id_returns_empty_list(self):
        ms.SharedTask.objects.create(task=self.task, shared_by=self.sharer, description="A")
        self.assertEqual(self._ids({"task_id": "no-es-un-uuid"}), set())

    def test_without_task_id_lists_all_shares(self):
        a = ms.SharedTask.objects.create(task=self.task, shared_by=self.sharer, description="A")
        b = ms.SharedTask.objects.create(task=self.other_task, shared_by=self.other_sharer, description="B")
        self.assertEqual(self._ids({}), {str(a.id), str(b.id)})
