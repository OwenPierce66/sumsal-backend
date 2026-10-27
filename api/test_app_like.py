from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


@override_settings(APP_ACCOUNT_EMAIL="owen@gmail.com")
class AppLikeTests(TestCase):
    """El "like de la App" del superadmin (como en peticiones.js de la web) sale a nombre de owen@gmail.com."""

    def setUp(self):
        self.app_account = User.objects.create_user(
            email="owen@gmail.com", password="test-password", username="owen"
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com", password="test-password", username="admin"
        )
        self.author = User.objects.create_user(
            email="autor@example.com", password="test-password", username="autor"
        )
        self.task = ms.Task.objects.create(user=self.author, title="Aportación")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = reverse("admin-task-like", kwargs={"task_id": self.task.id})

    def test_like_is_given_by_the_app_account(self):
        response = self.client.post(self.url, {"liked": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["liked"])
        self.assertEqual(response.data["likes_count"], 1)
        self.assertEqual(str(response.data["app_account_id"]), str(self.app_account.id))
        self.assertTrue(ms.Like.objects.filter(user=self.app_account, task=self.task).exists())
        self.assertFalse(ms.Like.objects.filter(user=self.admin, task=self.task).exists())

    def test_liking_twice_keeps_one_like_and_false_removes_it(self):
        self.client.post(self.url, {}, format="json")
        self.client.post(self.url, {"liked": True}, format="json")
        self.assertEqual(ms.Like.objects.filter(task=self.task).count(), 1)

        response = self.client.post(self.url, {"liked": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["liked"])
        self.assertEqual(response.data["likes_count"], 0)

    def test_email_match_ignores_case(self):
        with override_settings(APP_ACCOUNT_EMAIL="Owen@Gmail.com"):
            response = self.client.post(self.url, {"liked": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ms.Like.objects.filter(user=self.app_account, task=self.task).exists())

    def test_only_superusers(self):
        staff = User.objects.create_user(
            email="staff@example.com", password="test-password", username="staff", is_staff=True
        )
        self.client.force_authenticate(staff)
        response = self.client.post(self.url, {"liked": True}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ms.Like.objects.exists())

    def test_missing_app_account_is_reported(self):
        self.app_account.delete()
        response = self.client.post(self.url, {"liked": True}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertIn("owen@gmail.com", response.data["detail"])

    def test_app_has_liked_only_for_superusers(self):
        detail = reverse("task-detail", kwargs={"id": self.task.id})
        self.assertIs(self.client.get(detail).data["app_has_liked"], False)

        ms.Like.objects.create(user=self.app_account, task=self.task)
        self.assertIs(self.client.get(detail).data["app_has_liked"], True)

        self.client.force_authenticate(self.author)
        self.assertIsNone(self.client.get(detail).data["app_has_liked"])

    def test_profile_like_is_given_by_the_app_account(self):
        url = reverse("admin-profile-like", kwargs={"profile_id": self.author.id})
        response = self.client.post(url, {"liked": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(ms.LikeP.objects.filter(user=self.app_account, profile=self.author).exists())
        self.assertFalse(ms.LikeP.objects.filter(user=self.admin, profile=self.author).exists())

        response = self.client.post(url, {"liked": False}, format="json")
        self.assertFalse(response.data["liked"])
        self.assertFalse(ms.LikeP.objects.filter(user=self.app_account, profile=self.author).exists())

    def test_task_list_for_superuser_does_not_grow_with_tasks(self):
        url = reverse("task-list-create")

        def add_tasks(start, end):
            for i in range(start, end):
                task = ms.Task.objects.create(user=self.author, title=f"t{i}")
                ms.Like.objects.create(user=self.app_account, task=task)

        def count_queries():
            cache.clear()  # el listado usa caché por usuario
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            return len(ctx)

        add_tasks(0, 2)
        small = count_queries()
        add_tasks(2, 8)
        large = count_queries()
        self.assertLessEqual(large, small, f"{small} consultas con 2 tareas -> {large} con 8")
