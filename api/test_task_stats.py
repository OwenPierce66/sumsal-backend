from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class TaskStatsTests(TestCase):
    """El creador ve cuántas veces guardaron, pusieron en favoritos, anclaron o citaron su
    publicación; los demás, solo los números públicos."""

    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x", username="ana")
        self.luis = User.objects.create_user(email="luis@example.com", password="x", username="luis")
        self.eva = User.objects.create_user(email="eva@example.com", password="x", username="eva")
        self.task = ms.Task.objects.create(user=self.ana, title="Guía de becas", pch="consejos")
        self.url = reverse("task-stats", kwargs={"task_id": self.task.id})

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_owner_sees_private_counts_and_others_only_public(self):
        ms.TaskSave.objects.create(user=self.luis, task=self.task)
        favorite = ms.Favorito.objects.create(user=self.luis, task=self.task, is_pinned=True)
        ms.TaskCategoryPin.objects.create(favorite=favorite, category="Becas", position=0)
        ms.TaskSave.objects.create(user=self.eva, task=self.task)
        ms.Like.objects.create(user=self.eva, task=self.task)
        ms.Repost.objects.create(user=self.eva, task=self.task)
        other = ms.Task.objects.create(user=self.eva, title="Otra", pch="consejos")
        ms.NewPeticionCommentPost.objects.create(created_by=self.eva, post=other, text="mira esta", aportacion=self.task)
        ms.Postt.objects.create(user=self.luis, title="Becas", content="esta ayuda", aportacion=self.task)

        owner = self.client_for(self.ana).get(self.url).data
        self.assertTrue(owner["is_owner"])
        self.assertEqual(owner["private"], {"saves": 2, "favorites": 1, "pinned": 1, "category_pins": 1, "story_shares": 0})
        self.assertEqual(owner["public"]["likes"], 1)
        self.assertEqual(owner["public"]["reposts"], 1)
        self.assertEqual(owner["public"]["citations"], {"comments": 1, "forum": 1, "shared_comments": 0, "total": 2})

        visitor = self.client_for(self.eva).get(self.url).data
        self.assertFalse(visitor["is_owner"])
        self.assertIsNone(visitor["private"])
        self.assertEqual(visitor["public"]["citations"]["total"], 2)

    def test_hidden_publication_has_no_stats_for_others(self):
        self.task.is_hidden = True
        self.task.save(update_fields=["is_hidden"])
        self.assertEqual(self.client_for(self.eva).get(self.url).status_code, 404)
        self.assertEqual(self.client_for(self.ana).get(self.url).status_code, 200)

    def test_feed_card_shows_how_many_times_it_was_cited(self):
        other = ms.Task.objects.create(user=self.eva, title="Otra", pch="consejos")
        ms.NewPeticionCommentPost.objects.create(created_by=self.eva, post=other, text="mira", aportacion=self.task)
        ms.Postt.objects.create(user=self.luis, title="Becas", content="esta", aportacion=self.task)
        detail = self.client_for(self.eva).get(reverse("task-detail", kwargs={"id": self.task.id})).data
        self.assertEqual(detail["citations_count"], 2)
        feed = self.client_for(self.eva).get(reverse("task-list-create")).data["results"]
        self.assertEqual({item["title"]: item["citations_count"] for item in feed}, {"Guía de becas": 2, "Otra": 0})
