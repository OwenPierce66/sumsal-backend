import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


def png_file(name="cover.png"):
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "purple").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


MEDIA_DIR = tempfile.mkdtemp(prefix="test-media-categories-")


@override_settings(MEDIA_ROOT=MEDIA_DIR)
class CategoryMediaTests(TestCase):
    """Categorías con imagen y descripción (las pone un admin)."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_DIR, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.admin = User.objects.create_user(email="admin@example.com", password="x", username="admin", is_staff=True)
        self.user = User.objects.create_user(email="ana@example.com", password="x", username="ana")
        self.category = ms.NewCategory.objects.create(name="Programación", pch="consejos")
        self.url = reverse("new-category-detail", kwargs={"pk": self.category.pk})
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)
        self.user_client = APIClient()
        self.user_client.force_authenticate(self.user)

    def test_admin_adds_description_and_image_without_touching_the_name(self):
        response = self.admin_client.patch(self.url, {"description": "Código, apps y web.", "image": png_file()}, format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["name"], "Programación")
        self.assertEqual(response.data["pch"], "consejos")
        self.assertEqual(response.data["description"], "Código, apps y web.")
        self.assertTrue(response.data["image_url"])

        listed = self.user_client.get(reverse("new-category-list-create"), {"pch": "consejos"}).data
        self.assertEqual(listed[0]["description"], "Código, apps y web.")
        self.assertTrue(listed[0]["image_url"])
        self.assertNotIn("image", listed[0])

    def test_only_admins_edit(self):
        response = self.user_client.patch(self.url, {"description": "x"}, format="json")
        self.assertEqual(response.status_code, 403)
