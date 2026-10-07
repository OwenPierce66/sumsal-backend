"""
Tests de validacion de subidas (Fase 36).

- Los adjuntos con contenido activo/ejecutable (html, svg, js, exe...) se rechazan:
  se sirven desde /media/ y permitirian XSS almacenado o distribucion de malware.
- Se limita el tamano de videos / imagenes / adjuntos.
- Los errores 500 del chat no deben exponer el traceback al cliente.
"""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from massaging.models import Group, GroupMembership, GroupMessageAttachment, MessageAttachment

User = get_user_model()


def _user(name):
    return User.objects.create_user(username=name, email=f"{name}@example.com", password="pass12345")


class ChatUploadValidationTests(TestCase):
    def setUp(self):
        self.sender = _user("sender")
        self.receiver = _user("receiver")
        self.group = Group.objects.create(name="g", created_by=self.sender)
        GroupMembership.objects.create(user=self.sender, group=self.group)
        self.client = APIClient()
        self.client.force_authenticate(self.sender)

    def _dm(self, **files):
        return self.client.post(
            reverse("message-list"),
            {"receiver": str(self.receiver.id), "content": "hola", **files},
            format="multipart",
        )

    def _group(self, **files):
        return self.client.post(
            reverse("send-group-message", kwargs={"group_id": self.group.id}),
            {"content": "hola", **files},
            format="multipart",
        )

    def test_dm_rejects_active_content_attachment(self):
        for name in ("evil.html", "evil.svg", "run.exe", "x.js", "shell.php"):
            f = SimpleUploadedFile(name, b"<script>alert(1)</script>", content_type="text/html")
            res = self._dm(attachments=f)
            self.assertEqual(res.status_code, 400, name)
        self.assertEqual(MessageAttachment.objects.count(), 0)

    def test_group_rejects_active_content_attachment(self):
        f = SimpleUploadedFile("evil.html", b"<script>alert(1)</script>", content_type="text/html")
        res = self._group(attachments=f)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(GroupMessageAttachment.objects.count(), 0)

    def test_dm_accepts_regular_document(self):
        f = SimpleUploadedFile("nota.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        res = self._dm(attachments=f)
        self.assertEqual(res.status_code, 201, res.content[:300])

    @override_settings(UPLOAD_MAX_ATTACHMENT_BYTES=100)
    def test_dm_rejects_oversized_attachment(self):
        f = SimpleUploadedFile("big.pdf", b"x" * 500, content_type="application/pdf")
        self.assertEqual(self._dm(attachments=f).status_code, 400)

    @override_settings(UPLOAD_MAX_VIDEO_BYTES=100)
    def test_dm_rejects_oversized_video(self):
        f = SimpleUploadedFile("clip.mp4", b"x" * 500, content_type="video/mp4")
        self.assertEqual(self._dm(video=f).status_code, 400)

    def test_dm_rejects_non_video_in_video_field(self):
        f = SimpleUploadedFile("evil.html", b"<script>1</script>", content_type="video/mp4")
        self.assertEqual(self._dm(video=f).status_code, 400)

    def test_group_rejects_non_video_in_video_field(self):
        f = SimpleUploadedFile("evil.html", b"<script>1</script>", content_type="video/mp4")
        self.assertEqual(self._group(video=f).status_code, 400)

    def test_dm_accepts_regular_video(self):
        f = SimpleUploadedFile("clip.mp4", b"\x00\x00\x00\x18ftypmp42", content_type="video/mp4")
        self.assertEqual(self._dm(video=f).status_code, 201)


class TaskUploadValidationTests(TestCase):
    def setUp(self):
        self.user = _user("author")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _create(self, **files):
        return self.client.post(
            reverse("task-list-create"),
            {"title": "t", "description": "d", "pch": "consejos", **files},
            format="multipart",
        )

    def test_task_rejects_non_video_file_in_video_field(self):
        f = SimpleUploadedFile("evil.html", b"<script>1</script>", content_type="video/mp4")
        self.assertEqual(self._create(video=f).status_code, 400)

    @override_settings(UPLOAD_MAX_VIDEO_BYTES=100)
    def test_task_rejects_oversized_video(self):
        f = SimpleUploadedFile("clip.mp4", b"x" * 500, content_type="video/mp4")
        self.assertEqual(self._create(video=f).status_code, 400)

    def test_task_accepts_regular_video(self):
        f = SimpleUploadedFile("clip.mp4", b"\x00\x00\x00\x18ftypmp42", content_type="video/mp4")
        res = self._create(video=f)
        self.assertEqual(res.status_code, 201, res.content[:300])
