from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import NewPeticionCommentPost, Notification, Postt, SharedTask, Task, TaskSave

User = get_user_model()


class MessageExtrasTests(TestCase):
    """Foto o video, publicación guardada y etiquetas también en el foro y en los
    comentarios de tareas compartidas."""

    def setUp(self):
        self.user = User.objects.create_user(username="writer", email="w@example.com", password="pass")
        self.friend = User.objects.create_user(username="friend", email="f@example.com", password="pass")
        self.task = Task.objects.create(user=self.friend, title="Guía de becas")
        TaskSave.objects.create(user=self.user, task=self.task)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def photo(self):
        return SimpleUploadedFile("foto.jpg", b"jpeg-bytes", content_type="image/jpeg")

    def test_forum_post_with_photo_saved_publication_and_tags(self):
        response = self.client.post(reverse("post-list-create"), {
            "title": "Becas", "content": "miren", "attachment": self.photo(),
            "aportacion": str(self.task.id), "tagged_user_ids": [str(self.friend.id)],
        }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["attachment_type"], "image")
        self.assertEqual(response.data["aportacion_info"]["title"], "Guía de becas")
        self.assertEqual(response.data["tagged_users"], [{"id": str(self.friend.id), "username": "friend"}])
        note = Notification.objects.get(recipient=self.friend, notification_type="forum_tag")
        self.assertEqual(str(note.target_id), str(response.data["id"]))

    def test_forum_reply_tag_points_to_the_thread(self):
        thread = Postt.objects.create(user=self.friend, title="Hilo", content="hola")
        response = self.client.post(reverse("post-list-create"), {
            "content": "te leo", "parent": thread.id, "tagged_user_ids": [str(self.friend.id)],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        note = Notification.objects.get(recipient=self.friend, notification_type="forum_tag")
        self.assertEqual(str(note.target_id), str(thread.id))

    def test_forum_rejects_empty_posts_and_unsaved_publications(self):
        self.assertEqual(self.client.post(reverse("post-list-create"), {"title": "x", "content": ""}, format="json").status_code, 400)
        other = Task.objects.create(user=self.friend, title="No guardada")
        response = self.client.post(reverse("post-list-create"), {"content": "mira", "aportacion": str(other.id)}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("aportacion", response.data)

    def test_shared_task_comment_with_video_and_tag_is_copied_to_the_original(self):
        shared = SharedTask.objects.create(task=self.task, shared_by=self.friend)
        video = SimpleUploadedFile("clip.mp4", b"mp4-bytes", content_type="video/mp4")
        response = self.client.post(
            reverse("shared-task-comments", kwargs={"shared_task_id": shared.id}),
            {"attachment": video, "aportacion": str(self.task.id), "tagged_user_ids": [str(self.friend.id)]},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["attachment_type"], "video")
        self.assertTrue(Notification.objects.filter(recipient=self.friend, notification_type="shared_comment_tag").exists())
        copy = NewPeticionCommentPost.objects.get(post=self.task)
        self.assertTrue(copy.attachment.name)
        self.assertEqual(copy.aportacion_id, self.task.id)
