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


class ProfileTestimonialTests(TestCase):
    """Un testimonio escrito en el perfil de otra persona es una publicación completa
    (pch "testimonios"): likes, comentarios, impulsar... La persona decide si se muestra."""

    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x", username="ana")
        self.luis = User.objects.create_user(email="luis@example.com", password="x", username="luis")
        self.eva = User.objects.create_user(email="eva@example.com", password="x", username="eva")
        self.ana_client = TestimonialTests.client_for(self.ana)
        self.luis_client = TestimonialTests.client_for(self.luis)
        self.eva_client = TestimonialTests.client_for(self.eva)
        self.url = reverse("user-testimonials", kwargs={"user_id": self.luis.pk})

    def write(self, client=None, **extra):
        body = {"title": "Gran maestro", "description": "Luis siempre ayuda", "testimonial_for": str(self.luis.pk), **extra}
        return (client or self.ana_client).post(reverse("task-list-create"), body, format="json")

    def answer(self, task_id, status):
        return self.luis_client.patch(reverse("testimonial-detail", kwargs={"pk": task_id}), {"status": status}, format="json")

    def test_written_testimonial_is_a_publication_waiting_for_approval(self):
        response = self.write(pch="consejos")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["pch"], "testimonios")
        self.assertEqual(response.data["testimonial_status"], "pending")
        self.assertEqual(response.data["testimonial_for_info"], {"id": str(self.luis.pk), "username": "luis"})
        task_id = response.data["id"]

        note = ms.Notification.objects.get(recipient=self.luis, notification_type="profile_testimonial")
        self.assertEqual(note.data["testimonial_id"], task_id)
        self.assertEqual(note.target_type, "testimonial")

        # Pendiente: Ana (lo suyo) y Luis lo ven; Eva no, ni siquiera abriéndolo.
        ana_view = self.ana_client.get(self.url).data
        self.assertEqual(ana_view["testimonials"], [])
        self.assertEqual([t["id"] for t in ana_view["mine"]], [task_id])
        luis_view = self.luis_client.get(self.url).data
        self.assertEqual([(t["kind"], t["status"]) for t in luis_view["pending"]], [("task", "pending")])
        self.assertEqual(self.eva_client.get(reverse("task-detail", kwargs={"id": task_id})).status_code, 404)

        self.assertEqual(self.ana_client.patch(reverse("testimonial-detail", kwargs={"pk": task_id}), {"status": "approved"}, format="json").status_code, 404)
        self.assertEqual(self.answer(task_id, "approved").status_code, 200)
        self.assertTrue(ms.Notification.objects.filter(recipient=self.ana, notification_type="testimonial_approved").exists())
        public = self.eva_client.get(self.url).data["testimonials"]
        self.assertEqual([(t["id"], t["user"]["username"]) for t in public], [(task_id, "ana")])

        # Ya aprobado: funciona como cualquier publicación.
        self.assertEqual(self.eva_client.post(reverse("task-like", kwargs={"task_id": task_id})).status_code, 201)
        comment = self.eva_client.post(reverse("task-comments", kwargs={"task_id": task_id}), {"text": "¡Totalmente!"}, format="json")
        self.assertEqual(comment.status_code, 201, comment.data)
        self.assertEqual(self.eva_client.post(reverse("task-repost", kwargs={"task_id": task_id})).status_code, 200)
        detail = self.eva_client.get(reverse("task-detail", kwargs={"id": task_id})).data
        self.assertEqual((detail["likes_count"], detail["comments_count"], detail["reposts_count"]), (1, 1, 1))

    def test_testimonials_stay_out_of_the_feed_and_the_authors_profile(self):
        task_id = self.write().data["id"]
        self.answer(task_id, "approved")
        consejo = ms.Task.objects.create(user=self.ana, title="Consejo", pch="consejos")
        feed_ids = [item["id"] for item in self.eva_client.get(reverse("task-list-create")).data["results"]]
        self.assertEqual(feed_ids, [str(consejo.id)])
        profile_ids = [item["id"] for item in self.eva_client.get(reverse("task-list-create"), {"user_id": str(self.ana.pk)}).data["results"]]
        self.assertEqual(profile_ids, [str(consejo.id)])
        unified = self.eva_client.get(reverse("feed"), {"sort_by": "all"}).data
        self.assertNotIn(task_id, [item["id"] for item in unified.get("results", unified)])

    def test_rules(self):
        own = self.ana_client.post(reverse("task-list-create"), {
            "title": "yo", "testimonial_for": str(self.ana.pk),
        }, format="json")
        self.assertEqual(own.status_code, 400)
        loose = self.ana_client.post(reverse("task-list-create"), {"title": "x", "pch": "testimonios"}, format="json")
        self.assertEqual(loose.status_code, 400)
        self.assertIn("pch", loose.data)

    def test_editing_goes_back_to_pending_and_deleting_retires_the_notice(self):
        task_id = self.write().data["id"]
        self.answer(task_id, "approved")
        ms.Notification.objects.filter(recipient=self.luis).update(is_read=True)

        edited = self.ana_client.patch(reverse("task-detail", kwargs={"id": task_id}), {"description": "Y mejor amigo"}, format="json")
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(ms.Task.objects.get(pk=task_id).testimonial_status, "pending")
        self.assertFalse(ms.Notification.objects.get(recipient=self.luis, notification_type="profile_testimonial").is_read)
        self.assertEqual(self.eva_client.get(self.url).data["testimonials"], [])

        moved = self.ana_client.patch(reverse("task-detail", kwargs={"id": task_id}), {"testimonial_for": str(self.eva.pk)}, format="json")
        self.assertEqual(moved.status_code, 400)

        self.assertEqual(self.ana_client.delete(reverse("task-detail", kwargs={"id": task_id})).status_code, 204)
        self.assertFalse(ms.Notification.objects.filter(notification_type="profile_testimonial").exists())

    def test_approved_testimonial_can_be_shared_to_a_story_as_text(self):
        task_id = self.write().data["id"]
        share = reverse("story-share-task")
        # Sin aprobar no se comparte (todavía no se muestra en el perfil).
        self.assertEqual(self.ana_client.post(share, {"task_id": task_id}, format="json").status_code, 400)
        self.answer(task_id, "approved")

        response = self.eva_client.post(share, {"task_id": task_id}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["testimonial_story"], {
            "title": "Gran maestro", "text": "Luis siempre ayuda", "for_username": "luis",
        })
        stories = self.luis_client.get(reverse("story-list-create")).data
        stories = stories.get("results", stories)
        self.assertIn(response.data["id"], [story["id"] for story in stories])

    def test_profile_and_comment_testimonials_are_listed_together(self):
        task = ms.Task.objects.create(user=self.eva, title="Aportación de Eva")
        self.eva_client.post(
            reverse("task-comments", kwargs={"task_id": task.id}),
            {"text": "Luis explicó todo", "tagged_user_ids": [str(self.luis.pk)]}, format="json",
        )
        self.write()
        pending = self.luis_client.get(self.url).data["pending"]
        self.assertEqual([t["kind"] for t in pending], ["task", "comment"])
        for item in pending:
            self.answer(item["id"], "approved")
        public = self.ana_client.get(self.url).data["testimonials"]
        self.assertEqual([t["kind"] for t in public], ["task", "comment"])
