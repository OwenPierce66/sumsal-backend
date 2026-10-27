from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class TestimonialTests(TestCase):
    """Etiquetar en comentarios; si la persona aprueba, sale en su perfil como testimonio."""

    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x", username="ana")
        self.luis = User.objects.create_user(email="luis@example.com", password="x", username="luis")
        self.eva = User.objects.create_user(email="eva@example.com", password="x", username="eva")
        self.task = ms.Task.objects.create(user=self.eva, title="Aportación de Eva")
        self.ana_client = self.client_for(self.ana)
        self.luis_client = self.client_for(self.luis)

    @staticmethod
    def client_for(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def comment(self, text="Luis me ayudó muchísimo", tagged=None, **extra):
        body = {"text": text, **extra}
        if tagged is not None:
            body["tagged_user_ids"] = [str(u.pk) for u in tagged]
        return self.ana_client.post(reverse("task-comments", kwargs={"task_id": self.task.id}), body, format="json")

    def fetch_testimonials(self, client, user):
        return client.get(reverse("user-testimonials", kwargs={"user_id": user.pk})).data

    def test_tagging_in_a_comment_notifies_and_waits_for_approval(self):
        response = self.comment(tagged=[self.luis, self.ana])  # etiquetarse a sí mismo se ignora
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["tagged_users"], [{"id": str(self.luis.pk), "username": "luis", "status": "pending"}],
        )

        notification = ms.Notification.objects.get(recipient=self.luis, notification_type="comment_tag")
        self.assertEqual(notification.actor, self.ana)
        tag = ms.CommentTag.objects.get()
        self.assertEqual(notification.data["testimonial_id"], str(tag.pk))

        # Pendiente: Luis lo ve para decidir; los demás todavía no.
        mine = self.fetch_testimonials(self.luis_client, self.luis)
        self.assertEqual(mine["testimonials"], [])
        self.assertEqual([t["comment"]["text"] for t in mine["pending"]], ["Luis me ayudó muchísimo"])
        public = self.fetch_testimonials(self.ana_client, self.luis)
        self.assertEqual(public["testimonials"], [])
        self.assertNotIn("pending", public)

    def test_approved_testimonial_is_public_and_can_be_hidden_again(self):
        self.comment(tagged=[self.luis])
        tag = ms.CommentTag.objects.get()
        url = reverse("testimonial-detail", kwargs={"pk": tag.pk})

        self.assertEqual(self.ana_client.patch(url, {"status": "approved"}, format="json").status_code, 404)
        response = self.luis_client.patch(url, {"status": "approved"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        public = self.fetch_testimonials(self.client_for(self.eva), self.luis)
        self.assertEqual(len(public["testimonials"]), 1)
        item = public["testimonials"][0]
        self.assertEqual(item["author"]["username"], "ana")
        self.assertEqual(item["task"], {"id": str(self.task.pk), "title": "Aportación de Eva"})

        self.luis_client.patch(url, {"status": "rejected"}, format="json")
        self.assertEqual(self.fetch_testimonials(self.ana_client, self.luis)["testimonials"], [])
        # Rechazado: deja de aparecer como etiquetado en el comentario.
        comments = self.ana_client.get(reverse("task-comments", kwargs={"task_id": self.task.id})).data
        comments = comments.get("results", comments) if isinstance(comments, dict) else comments
        self.assertEqual(comments[0]["tagged_users"], [])

        self.assertEqual(self.luis_client.patch(url, {"status": "maybe"}, format="json").status_code, 400)

    def test_editing_the_comment_updates_tags_and_removed_ones_lose_the_notification(self):
        comment_id = self.comment(tagged=[self.luis]).data["id"]
        url = reverse("task-comment-detail", kwargs={"comment_id": comment_id})

        response = self.ana_client.patch(url, {"text": "Gracias a Eva", "tagged_user_ids": [str(self.eva.pk)]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([t["username"] for t in response.data["tagged_users"]], ["eva"])
        self.assertFalse(ms.Notification.objects.filter(recipient=self.luis, notification_type="comment_tag").exists())
        self.assertTrue(ms.Notification.objects.filter(recipient=self.eva, notification_type="comment_tag").exists())

        # Editar solo el texto no toca las etiquetas.
        self.ana_client.patch(url, {"text": "Gracias a Eva!"}, format="json")
        self.assertEqual(ms.CommentTag.objects.get().user, self.eva)

    def test_replies_can_tag_too_and_limits_apply(self):
        parent = self.comment(text="Raíz").data["id"]
        reply = self.comment(text="Respuesta", tagged=[self.luis], parent=parent)
        self.assertEqual(reply.status_code, 201, reply.data)
        self.assertEqual(len(reply.data["tagged_users"]), 1)

        too_many = self.comment(tagged=[self.luis] * 11)
        self.assertEqual(too_many.status_code, 400)

    def test_testimonials_from_hidden_tasks_stay_private(self):
        self.task.is_hidden = True
        self.task.user = self.ana
        self.task.save()
        self.comment(tagged=[self.luis])
        tag = ms.CommentTag.objects.get()
        tag.status = "approved"
        tag.save()
        # Una tarea oculta no avisa ni deja ver el testimonio a nadie más.
        self.assertFalse(ms.Notification.objects.filter(recipient=self.luis).exists())
        self.assertEqual(self.fetch_testimonials(self.luis_client, self.luis)["testimonials"], [])

    def test_comment_list_tags_do_not_add_queries_per_comment(self):
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                self.ana_client.get(reverse("task-comments", kwargs={"task_id": self.task.id}))
            return len(ctx.captured_queries)

        self.comment(tagged=[self.luis])
        baseline = count_queries()
        for i in range(5):
            self.comment(text=f"otro {i}", tagged=[self.luis, self.eva])
        self.assertEqual(count_queries(), baseline)
