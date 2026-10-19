from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class FeedWithoutPchTests(TestCase):
    """Sin PCH seleccionada el feed debe mostrar las tres PCH juntas."""

    PCHS = ("peticiones", "consejos", "historias")

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="feed-reader",
            email="feed-reader@example.com",
            password="test-password",
        )
        self.owner = User.objects.create_user(
            username="feed-author",
            email="feed-author@example.com",
            password="test-password",
        )
        self.tasks_by_pch = {
            pch: ms.Task.objects.create(user=self.owner, title=f"Tarea {pch}", pch=pch)
            for pch in self.PCHS
        }
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("task-list-create")

    def _ids(self, params=None):
        response = self.client.get(self.url, params or {})
        self.assertEqual(response.status_code, 200)
        results = response.data["results"] if isinstance(response.data, dict) else response.data
        return {str(item["id"]) for item in results}

    def test_without_pch_returns_the_three_pch_together(self):
        ids = self._ids()
        for task in self.tasks_by_pch.values():
            self.assertIn(str(task.id), ids)

    def test_empty_pch_param_behaves_like_no_pch(self):
        ids = self._ids({"pch": ""})
        for task in self.tasks_by_pch.values():
            self.assertIn(str(task.id), ids)

    def test_selected_pch_only_returns_that_pch(self):
        ids = self._ids({"pch": "consejos"})
        self.assertEqual(ids, {str(self.tasks_by_pch["consejos"].id)})
