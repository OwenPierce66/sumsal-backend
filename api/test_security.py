"""
Tests de seguridad (Fase 36).

Cubren las vulnerabilidades encontradas en la auditoría del backend:
- IDOR: cualquier usuario autenticado podía EDITAR (PUT/PATCH) posts del foro y
  comentarios ajenos; solo se comprobaba la propiedad al borrar.
- Endpoints "users-who-liked/shared" accesibles sin autenticación y que
  devolvían datos personales (email, flags de staff).
"""
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


def make_user(name, **extra):
    return User.objects.create_user(
        username=name, email=f"{name}@example.com", password="pass12345", **extra
    )


def client_for(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


class ForeignObjectEditTests(TestCase):
    """Solo el autor (o staff) puede modificar su contenido."""

    def setUp(self):
        self.author = make_user("author")
        self.intruder = make_user("intruder")
        self.staff = make_user("staffer", is_staff=True)
        self.task = ms.Task.objects.create(user=self.author, title="Tarea")

    # ── Foro ──────────────────────────────────────────────────────────────
    def test_forum_post_cannot_be_edited_by_other_user(self):
        post = ms.Postt.objects.create(user=self.author, title="Original", content="c")
        url = reverse("post-detail", kwargs={"id": post.id})
        for method in ("patch", "put"):
            res = getattr(client_for(self.intruder), method)(
                url, {"title": "Hackeado", "content": "x"}, format="json"
            )
            self.assertEqual(res.status_code, 403, method)
        post.refresh_from_db()
        self.assertEqual(post.title, "Original")

    def test_forum_post_can_be_edited_by_author_and_staff(self):
        post = ms.Postt.objects.create(user=self.author, title="Original", content="c")
        url = reverse("post-detail", kwargs={"id": post.id})
        res = client_for(self.author).patch(url, {"title": "Mío"}, format="json")
        self.assertEqual(res.status_code, 200)
        res = client_for(self.staff).patch(url, {"title": "Moderado"}, format="json")
        self.assertEqual(res.status_code, 200)
        post.refresh_from_db()
        self.assertEqual(post.title, "Moderado")

    # ── Comentarios de tarea ──────────────────────────────────────────────
    def test_task_comment_cannot_be_edited_by_other_user(self):
        comment = ms.NewPeticionCommentPost.objects.create(
            created_by=self.author, post=self.task, text="original"
        )
        url = reverse("task-comment-detail", kwargs={"comment_id": comment.id})
        for method in ("patch", "put"):
            res = getattr(client_for(self.intruder), method)(
                url, {"text": "hackeado"}, format="json"
            )
            self.assertEqual(res.status_code, 403, method)
        comment.refresh_from_db()
        self.assertEqual(comment.text, "original")

    def test_task_comment_can_be_edited_by_author(self):
        comment = ms.NewPeticionCommentPost.objects.create(
            created_by=self.author, post=self.task, text="original"
        )
        url = reverse("task-comment-detail", kwargs={"comment_id": comment.id})
        res = client_for(self.author).patch(url, {"text": "editado"}, format="json")
        self.assertEqual(res.status_code, 200)
        comment.refresh_from_db()
        self.assertEqual(comment.text, "editado")

    # ── Comentarios de tarea compartida ───────────────────────────────────
    def test_shared_comment_cannot_be_edited_by_other_user(self):
        shared = ms.SharedTask.objects.create(task=self.task, shared_by=self.author)
        comment = ms.SharedTaskComment.objects.create(
            created_by=self.author, shared_task=shared, text="original"
        )
        url = reverse(
            "shared-task-comment-detail",
            kwargs={"shared_task_id": shared.id, "comment_id": comment.id},
        )
        for method in ("patch", "put"):
            res = getattr(client_for(self.intruder), method)(
                url, {"text": "hackeado"}, format="json"
            )
            self.assertEqual(res.status_code, 403, method)
        comment.refresh_from_db()
        self.assertEqual(comment.text, "original")

    def test_shared_comment_can_be_edited_by_author(self):
        shared = ms.SharedTask.objects.create(task=self.task, shared_by=self.author)
        comment = ms.SharedTaskComment.objects.create(
            created_by=self.author, shared_task=shared, text="original"
        )
        url = reverse(
            "shared-task-comment-detail",
            kwargs={"shared_task_id": shared.id, "comment_id": comment.id},
        )
        res = client_for(self.author).patch(url, {"text": "editado"}, format="json")
        self.assertEqual(res.status_code, 200)


class PublicEndpointExposureTests(TestCase):
    """Los listados de usuarios (con email y flags) exigen autenticación."""

    def setUp(self):
        self.user = make_user("viewer")
        self.task_id = uuid.uuid4()

    def _urls(self):
        return [
            reverse("task-likers", kwargs={"task_id": self.task_id}),
            reverse("task-sharers", kwargs={"task_id": self.task_id}),
            reverse("comment-likers", kwargs={"comment_id": 1}),
            reverse("shared-task-likers", kwargs={"shared_task_id": self.task_id}),
            reverse("shared-task-comment-likers", kwargs={"comment_id": 1}),
            reverse("category-p-list-for-user", kwargs={"user_id": self.user.id}),
        ]

    def test_anonymous_requests_are_rejected(self):
        for url in self._urls():
            res = client_for().get(url)
            self.assertEqual(res.status_code, 401, url)

    def test_authenticated_requests_still_work(self):
        for url in self._urls():
            res = client_for(self.user).get(url)
            self.assertEqual(res.status_code, 200, url)
