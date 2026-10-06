"""Tests de Fase 31: paginación del historial de chat (directo y grupo)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Group, GroupMembership, GroupMessage, Message

User = get_user_model()


def make_user(name):
    return User.objects.create_user(
        username=name, email=f"{name}@example.com", password="test-password"
    )


class DirectChatPaginationTests(TestCase):
    def setUp(self):
        self.user = make_user("p_user")
        self.other = make_user("p_other")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("message-list")
        # 25 mensajes; el id más alto es el más reciente
        self.messages = [
            Message.objects.create(
                sender=self.user if i % 2 else self.other,
                receiver=self.other if i % 2 else self.user,
                content=f"m{i}",
            )
            for i in range(25)
        ]

    def _ids(self, **params):
        params["user_id"] = str(self.other.id)
        res = self.client.get(self.url, params)
        self.assertEqual(res.status_code, 200)
        return [m["id"] for m in res.data]

    def test_default_page_size_is_unchanged(self):
        self.assertEqual(len(self._ids()), 10)

    def test_pages_are_newest_first_without_overlap_or_gaps(self):
        all_ids = []
        for page in (1, 2, 3):
            all_ids += self._ids(page=page, page_size=10)
        expected = [m.id for m in reversed(self.messages)]
        self.assertEqual(all_ids, expected)
        self.assertEqual(self._ids(page=4, page_size=10), [])

    def test_page_size_is_capped_at_100(self):
        for i in range(110):
            Message.objects.create(sender=self.user, receiver=self.other, content="x")
        self.assertEqual(len(self._ids(page_size=1000)), 100)

    def test_invalid_page_params_are_400(self):
        for params in ({"page": "abc"}, {"page_size": "xyz"}):
            res = self.client.get(
                self.url, {"user_id": str(self.other.id), **params}
            )
            self.assertEqual(res.status_code, 400)


class GroupChatPaginationTests(TestCase):
    def setUp(self):
        self.user = make_user("g_user")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.group = Group.objects.create(name="Team", created_by=self.user)
        GroupMembership.objects.create(user=self.user, group=self.group, is_admin=True)
        self.messages = [
            GroupMessage.objects.create(
                group=self.group, sender=self.user, content=f"g{i}"
            )
            for i in range(25)
        ]
        self.url = reverse("group-messages", args=[self.group.id])

    def test_without_page_returns_full_history(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 25)

    def test_pages_are_newest_first_without_overlap(self):
        collected = []
        for page in (1, 2, 3):
            res = self.client.get(self.url, {"page": page, "page_size": 10})
            self.assertEqual(res.status_code, 200)
            collected += [m["id"] for m in res.data]
        self.assertEqual(collected, [m.id for m in reversed(self.messages)])
        res = self.client.get(self.url, {"page": 4, "page_size": 10})
        self.assertEqual(res.data, [])

    def test_invalid_page_is_400(self):
        self.assertEqual(self.client.get(self.url, {"page": "abc"}).status_code, 400)

    def test_non_member_is_forbidden(self):
        outsider = APIClient()
        outsider.force_authenticate(make_user("g_outsider"))
        res = outsider.get(self.url, {"page": 1})
        self.assertEqual(res.status_code, 403)

    def test_opening_updates_last_read(self):
        self.client.get(self.url, {"page": 1, "page_size": 10})
        membership = GroupMembership.objects.get(user=self.user, group=self.group)
        self.assertIsNotNone(membership.last_read_at)
