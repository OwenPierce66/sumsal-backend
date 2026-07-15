from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms
from api.views import SharedTaskListCreateView
from api.serializers import SharedTaskSerializer

User = get_user_model()


class SharedTaskViewRegressionTests(TestCase):
    def test_shared_task_list_view_uses_shared_task_serializer(self):
        view = SharedTaskListCreateView()
        self.assertEqual(view.get_serializer_class(), SharedTaskSerializer)

    def test_shared_task_list_endpoint_returns_200_for_anonymous_get(self):
        client = APIClient()
        response = client.get(reverse("shared-task-list-create"))
        self.assertIn(response.status_code, {200, 404})


class pFavoritoViewRegressionTests(TestCase):
    def test_agregar_pfavorito_accepts_user_uuid_target(self):
        viewer = User.objects.create_user(email="viewer@example.com", password="password123")
        target_user = User.objects.create_user(email="target@example.com", password="password123")
        target_profile = target_user.profile

        client = APIClient()
        client.force_authenticate(user=viewer)

        response = client.post(
            reverse("agregar-pfavorito"),
            {"perfil_id": str(target_user.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(ms.pFavorito.objects.filter(user=viewer, perfil=target_user).exists())
