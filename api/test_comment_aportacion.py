from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import Favorito, NewPeticionCommentPost, SubFactores, SubTask, Task

User = get_user_model()


class CommentWithFavoriteAportacionTests(TestCase):
    """Comentar adjuntando una de tus aportaciones favoritas (función de la web antigua)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="commenter", email="c@example.com", password="test-password"
        )
        self.owner = User.objects.create_user(
            username="owner", email="o@example.com", password="test-password"
        )
        self.post = Task.objects.create(user=self.owner, title="Post principal")
        self.fav_task = Task.objects.create(user=self.owner, title="Mi favorita")
        self.other_task = Task.objects.create(user=self.owner, title="No favorita")
        Favorito.objects.create(user=self.user, task=self.fav_task)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("task-comments", kwargs={"task_id": self.post.id})

    def _post(self, **extra):
        return self.client.post(self.url, {"text": "hola", **extra}, format="json")

    def test_favorite_is_accepted_and_returned_with_info(self):
        response = self._post(aportacion=str(self.fav_task.id))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(str(response.data["aportacion"]), str(self.fav_task.id))
        self.assertEqual(response.data["aportacion_info"]["title"], "Mi favorita")
        self.assertEqual(response.data["aportacion_info"]["username"], "owner")

        listing = self.client.get(self.url)
        results = listing.data["results"] if "results" in listing.data else listing.data
        self.assertEqual(results[0]["aportacion_info"]["id"], str(self.fav_task.id))

    def test_non_favorite_is_rejected(self):
        response = self._post(aportacion=str(self.other_task.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("aportacion", response.data)
        self.assertEqual(NewPeticionCommentPost.objects.count(), 0)

    def test_someone_elses_favorite_is_rejected(self):
        Favorito.objects.create(user=self.owner, task=self.other_task)
        response = self._post(aportacion=str(self.other_task.id))
        self.assertEqual(response.status_code, 400)

    def test_unsaved_story_is_rejected_even_if_favorite(self):
        story = Task.objects.create(user=self.owner, title="Historia", is_story=True)
        Favorito.objects.create(user=self.user, task=story)
        response = self._post(aportacion=str(story.id))
        self.assertEqual(response.status_code, 400)

    def test_comment_without_aportacion_is_unchanged(self):
        response = self._post()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["aportacion"])
        self.assertIsNone(response.data["aportacion_info"])

    def test_replies_can_carry_a_favorite_aportacion(self):
        parent = NewPeticionCommentPost.objects.create(
            post=self.post, created_by=self.owner, text="padre"
        )
        response = self._post(parent=parent.id, aportacion=str(self.fav_task.id))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["aportacion_info"]["title"], "Mi favorita")

        listing = self.client.get(self.url)
        results = listing.data["results"] if "results" in listing.data else listing.data
        reply = results[0]["children"][0]
        self.assertEqual(reply["aportacion_info"]["id"], str(self.fav_task.id))

    def test_replies_only_accept_favorites(self):
        parent = NewPeticionCommentPost.objects.create(
            post=self.post, created_by=self.owner, text="padre"
        )
        response = self._post(parent=parent.id, aportacion=str(self.other_task.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("aportacion", response.data)

    def test_editing_keeps_aportacion_after_unfavoriting(self):
        response = self._post(aportacion=str(self.fav_task.id))
        comment_id = response.data["id"]
        Favorito.objects.filter(user=self.user, task=self.fav_task).delete()

        detail = reverse("task-comment-detail", kwargs={"comment_id": comment_id})
        edited = self.client.patch(detail, {"text": "editado"}, format="json")
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(str(edited.data["aportacion"]), str(self.fav_task.id))

    def test_deleted_aportacion_leaves_comment_without_info(self):
        response = self._post(aportacion=str(self.fav_task.id))
        self.fav_task.delete()
        listing = self.client.get(self.url)
        results = listing.data["results"] if "results" in listing.data else listing.data
        self.assertEqual(results[0]["id"], response.data["id"])
        self.assertIsNone(results[0]["aportacion_info"])

    def test_info_includes_pch(self):
        self.fav_task.pch = "peticiones"
        self.fav_task.save(update_fields=["pch"])
        response = self._post(aportacion=str(self.fav_task.id))
        self.assertEqual(response.data["aportacion_info"]["pch"], "peticiones")

    def test_image_falls_back_to_first_block_with_image(self):
        # Sin imagen propia: la portada sale del primer consejo/factor/fuente con imagen.
        SubTask.objects.create(parent_task=self.fav_task, title="Consejo sin media")
        SubFactores.objects.create(
            parent_task=self.fav_task, title="Factor", image="subfactores/images/portada.png"
        )
        response = self._post(aportacion=str(self.fav_task.id))
        self.assertTrue(
            response.data["aportacion_info"]["image"].endswith("/media/subfactores/images/portada.png"),
            response.data["aportacion_info"],
        )

    def test_task_image_has_priority_over_blocks(self):
        self.fav_task.image = "tasks/propia.png"
        self.fav_task.save(update_fields=["image"])
        SubTask.objects.create(
            parent_task=self.fav_task, title="Consejo", image="subtasks/images/otra.png"
        )
        response = self._post(aportacion=str(self.fav_task.id))
        self.assertTrue(response.data["aportacion_info"]["image"].endswith("/media/tasks/propia.png"))

    def test_without_any_image_info_image_is_none(self):
        SubTask.objects.create(parent_task=self.fav_task, title="Solo texto")
        response = self._post(aportacion=str(self.fav_task.id))
        self.assertIsNone(response.data["aportacion_info"]["image"])


class CommentAportacionQueryScalingTests(TestCase):
    """La portada de la aportación no debe costar consultas por comentario (N+1)."""

    SMALL, LARGE = 2, 8

    def setUp(self):
        self.viewer = User.objects.create_user(
            username="viewer", email="v@example.com", password="test-password"
        )
        self.owner = User.objects.create_user(
            username="owner", email="o@example.com", password="test-password"
        )
        self.post = Task.objects.create(user=self.owner, title="Post principal")
        self.client = APIClient()
        self.client.force_authenticate(self.viewer)

    def _add_comments(self, start, end, post=None):
        for i in range(start, end):
            aportacion = Task.objects.create(user=self.owner, title=f"Aportación {i}")
            SubTask.objects.create(
                parent_task=aportacion, title="Consejo", image=f"subtasks/images/{i}.png"
            )
            comment = NewPeticionCommentPost.objects.create(
                post=post or self.post, created_by=self.viewer, text=f"c{i}", aportacion=aportacion
            )
            # Las respuestas también pueden llevar aportación.
            NewPeticionCommentPost.objects.create(
                post=post or self.post, created_by=self.owner, text=f"r{i}", parent=comment,
                aportacion=aportacion,
            )

    def _count(self, url):
        cache.clear()  # los listados de tareas usan caché por usuario
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(ctx)

    def test_comment_list_is_constant(self):
        url = reverse("task-comments", kwargs={"task_id": self.post.id})
        self._add_comments(0, self.SMALL)
        small = self._count(url)
        self._add_comments(self.SMALL, self.LARGE)
        large = self._count(url)
        self.assertLessEqual(large, small, f"{small} consultas con {self.SMALL} -> {large} con {self.LARGE}")

    def test_task_list_with_embedded_comments_is_constant(self):
        url = reverse("task-list-create")

        def populate(start, end):
            for i in range(start, end):
                post = Task.objects.create(user=self.owner, title=f"Post {i}")
                self._add_comments(i, i + 1, post=post)

        populate(0, self.SMALL)
        small = self._count(url)
        populate(self.SMALL, self.LARGE)
        large = self._count(url)
        self.assertLessEqual(large, small, f"{small} consultas con {self.SMALL} -> {large} con {self.LARGE}")
