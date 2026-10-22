from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import Favorito, NewPeticionCommentPost, Task

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

    def test_replies_cannot_carry_aportacion(self):
        parent = NewPeticionCommentPost.objects.create(
            post=self.post, created_by=self.owner, text="padre"
        )
        response = self._post(parent=parent.id, aportacion=str(self.fav_task.id))
        self.assertEqual(response.status_code, 400)

        response = self._post(parent=parent.id)
        self.assertEqual(response.status_code, 201, response.data)

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
