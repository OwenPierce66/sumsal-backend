from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import CommentTag, NewPeticionCommentPost, Task

User = get_user_model()


class CommentAttachmentTests(TestCase):
    """Comentarios con foto o video adjunto (función de la web antigua)."""

    def setUp(self):
        self.user = User.objects.create_user(username="commenter", email="c@example.com", password="pass")
        self.friend = User.objects.create_user(username="friend", email="f@example.com", password="pass")
        self.task = Task.objects.create(user=self.friend, title="Post")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("task-comments", kwargs={"task_id": self.task.id})

    def test_photo_with_text_and_tags_in_the_same_form(self):
        photo = SimpleUploadedFile("foto.jpg", b"jpeg-bytes", content_type="image/jpeg")
        response = self.client.post(
            self.url,
            {"text": "mira", "attachment": photo, "tagged_user_ids": [str(self.friend.id)]},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["attachment_type"], "image")
        self.assertTrue(response.data["attachment_url"])
        self.assertTrue(CommentTag.objects.filter(user=self.friend).exists())

    def test_video_alone_is_a_valid_comment(self):
        video = SimpleUploadedFile("clip.mp4", b"mp4-bytes", content_type="video/mp4")
        response = self.client.post(self.url, {"attachment": video}, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["attachment_type"], "video")
        self.assertEqual(response.data["text"], "")

    def test_empty_comment_and_other_files_are_rejected(self):
        self.assertEqual(self.client.post(self.url, {"text": "  "}, format="json").status_code, 400)
        pdf = SimpleUploadedFile("doc.pdf", b"%PDF", content_type="application/pdf")
        response = self.client.post(self.url, {"text": "hola", "attachment": pdf}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("attachment", response.data)
        self.assertEqual(NewPeticionCommentPost.objects.count(), 0)

    def test_comments_without_attachment_keep_working(self):
        response = self.client.post(self.url, {"text": "solo texto"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["attachment_url"])
        self.assertIsNone(response.data["attachment_type"])
