import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (
    Group,
    GroupMembership,
    GroupMessage,
    Message,
    MessageAttachment,
)


User = get_user_model()


class MessagingInboxTests(TestCase):
    def setUp(self):
        self.user = self.create_user("user")
        self.other = self.create_user("other")
        self.third = self.create_user("third")
        self.fourth = self.create_user("fourth")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @staticmethod
    def create_user(username):
        return User.objects.create_user(
            email=f"{username}@example.com",
            password="test-password",
            username=username,
        )

    def test_direct_messages_are_isolated_and_require_user_id(self):
        expected = Message.objects.create(
            sender=self.user,
            receiver=self.other,
            content="visible",
        )
        Message.objects.create(
            sender=self.third,
            receiver=self.fourth,
            content="private",
        )

        missing_user = self.client.get(reverse("message-list"))
        self.assertEqual(missing_user.status_code, 400)

        response = self.client.get(
            reverse("message-list"),
            {"user_id": str(self.other.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data], [expected.id])

    def test_opening_direct_conversation_marks_only_received_messages_read(self):
        received = Message.objects.create(
            sender=self.other,
            receiver=self.user,
            content="received",
        )
        sent = Message.objects.create(
            sender=self.user,
            receiver=self.other,
            content="sent",
        )
        unrelated = Message.objects.create(
            sender=self.third,
            receiver=self.user,
            content="unrelated",
        )

        response = self.client.get(
            reverse("message-list"),
            {"user_id": str(self.other.id)},
        )

        self.assertEqual(response.status_code, 200)
        received.refresh_from_db()
        sent.refresh_from_db()
        unrelated.refresh_from_db()
        self.assertTrue(received.is_read)
        self.assertIsNotNone(received.read_at)
        self.assertFalse(sent.is_read)
        self.assertIsNone(sent.read_at)
        self.assertFalse(unrelated.is_read)
        returned = {item["id"]: item for item in response.data}
        self.assertTrue(returned[received.id]["is_read"])

    def test_group_unread_count_and_opening_updates_last_read(self):
        group = Group.objects.create(name="Team", created_by=self.other)
        membership = GroupMembership.objects.create(user=self.user, group=group)
        GroupMembership.objects.create(
            user=self.other,
            group=group,
            is_admin=True,
        )
        read_boundary = timezone.now() - timedelta(hours=1)
        membership.last_read_at = read_boundary
        membership.save(update_fields=["last_read_at"])

        old_message = GroupMessage.objects.create(
            group=group,
            sender=self.other,
            content="old",
        )
        unread_message = GroupMessage.objects.create(
            group=group,
            sender=self.other,
            content="new",
        )
        own_message = GroupMessage.objects.create(
            group=group,
            sender=self.user,
            content="mine",
        )
        GroupMessage.objects.filter(id=old_message.id).update(
            timestamp=read_boundary - timedelta(minutes=1)
        )
        GroupMessage.objects.filter(id=unread_message.id).update(
            timestamp=read_boundary + timedelta(minutes=1)
        )
        GroupMessage.objects.filter(id=own_message.id).update(
            timestamp=read_boundary + timedelta(minutes=2)
        )

        unified = self.client.get(reverse("unified-conversations"))
        group_data = next(item for item in unified.data if item["type"] == "group")
        self.assertEqual(group_data["unread_count"], 1)

        opened = self.client.get(reverse("group-messages", args=[group.id]))
        self.assertEqual(opened.status_code, 200)
        membership.refresh_from_db()
        self.assertGreater(membership.last_read_at, read_boundary)

        unified = self.client.get(reverse("unified-conversations"))
        group_data = next(item for item in unified.data if item["type"] == "group")
        self.assertEqual(group_data["unread_count"], 0)

    def test_unified_conversations_contract_and_media_previews(self):
        direct = Message.objects.create(
            sender=self.other,
            receiver=self.user,
            content="",
        )
        MessageAttachment.objects.create(
            message=direct,
            file="messages/attachments/document.pdf",
            file_type="application/pdf",
        )

        group = Group.objects.create(name="Project", created_by=self.user)
        GroupMembership.objects.create(
            user=self.user,
            group=group,
            is_admin=True,
        )
        GroupMembership.objects.create(user=self.third, group=group)
        GroupMessage.objects.create(
            group=group,
            sender=self.third,
            content="",
            image="group_messages/photo.jpg",
        )

        response = self.client.get(reverse("unified-conversations"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["type"] for item in response.data], ["group", "direct"])
        direct_data = next(item for item in response.data if item["type"] == "direct")
        self.assertEqual(direct_data["last_message"], "Archivo adjunto")
        self.assertEqual(direct_data["last_message_type"], "attachment")
        self.assertEqual(direct_data["last_sender_name"], self.other.username)
        self.assertEqual(direct_data["unread_count"], 1)

        group_data = next(item for item in response.data if item["type"] == "group")
        self.assertEqual(group_data["last_message"], "Imagen")
        self.assertEqual(group_data["last_message_type"], "image")
        self.assertEqual(group_data["last_sender_name"], self.third.username)
        self.assertEqual(group_data["unread_count"], 1)
        self.assertEqual(group_data["member_count"], 2)
        self.assertEqual(str(group_data["created_by"]), str(self.user.id))
        self.assertTrue(group_data["current_user_is_admin"])

    def test_create_group_validates_and_deduplicates_members(self):
        response = self.client.post(
            reverse("create-group"),
            {
                "name": "New group",
                "members": [
                    str(self.other.id),
                    str(self.other.id),
                    str(self.user.id),
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        group = Group.objects.get(id=response.data["id"])
        memberships = GroupMembership.objects.filter(group=group)
        self.assertEqual(memberships.count(), 2)
        self.assertTrue(memberships.get(user=self.user).is_admin)
        self.assertFalse(memberships.get(user=self.other).is_admin)
        self.assertEqual(
            {str(member["id"]) for member in response.data["members"]},
            {str(self.user.id), str(self.other.id)},
        )

        group_count = Group.objects.count()
        invalid = self.client.post(
            reverse("create-group"),
            {"name": "Invalid", "members": [str(uuid.uuid4())]},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(Group.objects.count(), group_count)

    def test_group_membership_is_unique(self):
        group = Group.objects.create(name="Unique", created_by=self.user)
        GroupMembership.objects.create(user=self.user, group=group, is_admin=True)

        with self.assertRaises(IntegrityError), transaction.atomic():
            GroupMembership.objects.create(user=self.user, group=group)
