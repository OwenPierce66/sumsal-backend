import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class ModerationWorkflowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="moderation-owner@example.com",
            password="test-password",
            username="moderation_owner",
        )
        self.admin = User.objects.create_user(
            email="moderation-admin@example.com",
            password="test-password",
            username="moderation_admin",
            is_staff=True,
        )
        self.invitee = User.objects.create_user(
            email="moderation-invitee@example.com",
            password="test-password",
            username="moderation_invitee",
        )
        self.client = APIClient()

    def create_task(self, *, pch="peticiones", categories="Procesando"):
        return ms.Task.objects.create(
            user=self.owner,
            title="Aportación moderable",
            pch=pch,
            categories=categories,
        )

    def approval_url(self, task):
        return reverse("task-approve", kwargs={"task_id": task.id})

    def test_non_admin_cannot_approve_petition_or_edit_moderation_status(self):
        task = self.create_task()
        self.client.force_authenticate(user=self.owner)

        approval = self.client.post(self.approval_url(task), {"approve": True}, format="json")
        edit = self.client.patch(
            reverse("task-detail", kwargs={"id": task.id}),
            {"categories": "Procesando, Aprobada"},
            format="json",
        )

        self.assertEqual(approval.status_code, 403)
        self.assertEqual(edit.status_code, 400)
        task.refresh_from_db()
        self.assertEqual(task.categories, "Procesando")
        self.assertFalse(
            ms.Notification.objects.filter(
                recipient=self.owner,
                notification_type="task_approved",
            ).exists()
        )

    def test_admin_can_approve_and_revoke_petition_once(self):
        task = self.create_task()
        self.client.force_authenticate(user=self.admin)

        approved = self.client.post(self.approval_url(task), {"approve": True}, format="json")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.data["categories"], "aprobada")
        self.assertEqual(
            ms.Notification.objects.filter(
                recipient=self.owner,
                notification_type="task_approved",
            ).count(),
            1,
        )

        repeated = self.client.post(self.approval_url(task), {"approve": True}, format="json")
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(
            ms.Notification.objects.filter(
                recipient=self.owner,
                notification_type="task_approved",
            ).count(),
            1,
        )

        revoked = self.client.post(self.approval_url(task), {"approve": False}, format="json")
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(revoked.data["categories"], "Procesando")
        self.assertFalse(
            ms.Notification.objects.filter(
                recipient=self.owner,
                notification_type="task_approved",
            ).exists()
        )

    def test_admin_approval_of_podcast_notifies_invitees_and_creates_invitation(self):
        task = self.create_task(
            pch="consejos",
            categories="Grabar Podcast, Procesando",
        )
        ms.TaskTag.objects.create(task=task, user=self.invitee, tagged_by=self.owner)
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(self.approval_url(task), {"approve": True}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["categories"], "Grabar Podcast, aprobada")
        invitation = ms.PodcastInvitation.objects.get(task=task, user=self.invitee)
        self.assertEqual(invitation.status, ms.PodcastInvitation.STATUS_PENDING)
        for recipient in (self.owner, self.invitee):
            self.assertTrue(
                ms.Notification.objects.filter(
                    recipient=recipient,
                    notification_type="podcast_approved",
                    target_id=str(task.id),
                ).exists()
            )

        self.client.force_authenticate(user=self.invitee)
        response = self.client.post(
            reverse("podcast-invitation-response", kwargs={"task_id": task.id}),
            {"accepted": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        for recipient in (self.owner, self.admin):
            self.assertTrue(
                ms.Notification.objects.filter(
                    recipient=recipient,
                    notification_type="podcast_invitation_response",
                    target_id=str(task.id),
                ).exists()
            )

    def test_invalid_approval_value_is_rejected_without_approving(self):
        task = self.create_task()
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            self.approval_url(task),
            {"approve": "not-a-boolean"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        task.refresh_from_db()
        self.assertEqual(task.categories, "Procesando")

    def test_podcast_creation_starts_in_processing(self):
        self.client.force_authenticate(user=self.owner)

        response = self.client.post(
            reverse("task-list-create"),
            {
                "title": "Nueva propuesta de podcast",
                "pch": "consejos",
                "categories": "Grabar Podcast",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["categories"], "Grabar Podcast, Procesando")

    def test_comment_mention_notifies_matching_user(self):
        task = self.create_task()
        self.client.force_authenticate(user=self.owner)

        response = self.client.post(
            reverse("task-comments", kwargs={"task_id": task.id}),
            {"text": f"Revisa esto @{self.invitee.username.upper()}."},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            ms.Notification.objects.filter(
                recipient=self.invitee,
                notification_type="task_mention",
                target_id=str(task.id),
            ).exists()
        )

    def test_tag_endpoint_rejects_malformed_user_ids(self):
        task = self.create_task()
        self.client.force_authenticate(user=self.owner)

        response = self.client.post(
            reverse("task-tags", kwargs={"task_id": task.id}),
            {"user_ids": ["not-a-uuid"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ms.TaskTag.objects.filter(task=task).exists())

    def test_monthly_petition_top_five_notifies_admin_once(self):
        task = self.create_task()
        first_liker = User.objects.create_user(
            email="monthly-liker@example.com",
            password="test-password",
            username="monthly_liker",
        )
        second_liker = User.objects.create_user(
            email="monthly-liker-two@example.com",
            password="test-password",
            username="monthly_liker_two",
        )

        ms.Like.objects.create(task=task, user=first_liker)
        ms.Like.objects.create(task=task, user=second_liker)

        self.assertEqual(
            ms.Notification.objects.filter(
                recipient=self.admin,
                notification_type="petition_top_month",
                target_id=str(task.id),
            ).count(),
            1,
        )

    def test_monthly_petition_alert_is_limited_to_five_tasks(self):
        for index in range(1, 7):
            task = ms.Task.objects.create(
                id=uuid.UUID(int=index),
                user=self.owner,
                title=f"Petición {index}",
                pch="peticiones",
            )
            liker = User.objects.create_user(
                email=f"top-five-liker-{index}@example.com",
                password="test-password",
                username=f"top_five_liker_{index}",
            )
            ms.Like.objects.create(task=task, user=liker)

        alerts = ms.Notification.objects.filter(
            recipient=self.admin,
            notification_type="petition_top_month",
        )
        self.assertEqual(alerts.count(), 5)
        self.assertFalse(alerts.filter(target_id=str(uuid.UUID(int=6))).exists())
