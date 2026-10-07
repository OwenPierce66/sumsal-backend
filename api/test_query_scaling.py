"""
Tests de rendimiento (Fase 36): detectan consultas N+1.

Para cada listado se mide el numero de queries con pocos items y con muchos;
si crece con el volumen de datos hay un N+1.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from api import models as ms
from massaging.models import Group, GroupMembership, GroupMessage, Message

User = get_user_model()

SMALL, LARGE = 2, 8


def _user(name):
    return User.objects.create_user(username=name, email=f"{name}@example.com", password="pass12345")


def _rich_task(i, author=None):
    """Tarea con likes, comentario + respuesta, subtareas y etiqueta (como en produccion)."""
    author = author or _user(f"a{i}")
    task = ms.Task.objects.create(user=author, title=f"t{i}")
    liker = _user(f"l{i}")
    ms.Like.objects.create(user=liker, task=task)
    ms.LikeP.objects.create(user=liker, profile=author)
    comment = ms.NewPeticionCommentPost.objects.create(created_by=liker, post=task, text="c")
    ms.NewPeticionCommentPost.objects.create(created_by=author, post=task, parent=comment, text="r")
    ms.TaskTag.objects.create(task=task, user=liker, tagged_by=author)
    return task


class QueryScalingMixin:
    def _count(self, url):
        cache.clear()  # los listados usan cache por usuario: medimos siempre en frio
        client = APIClient()
        client.force_authenticate(self.viewer)
        with CaptureQueriesContext(connection) as ctx:
            res = client.get(url)
        self.assertEqual(res.status_code, 200, res.content[:300])
        data = res.json()
        items = data.get('results') if isinstance(data, dict) else data
        self.last_items = len(items) if isinstance(items, list) else None
        self.last_queries = [q['sql'] for q in ctx.captured_queries]
        return len(ctx)

    def _repeated(self):
        import re
        from collections import Counter
        norm = Counter(re.sub(r'\d+|\x27[^\x27]*\x27', '?', q)[:230] for q in self.last_queries)
        return '\n'.join(f'{n}x {q}' for q, n in norm.most_common(12) if n > 1)

    def assert_constant(self, url_name, populate, slack=0, per_item=1):
        url = reverse(url_name)
        populate(0, SMALL)
        small = self._count(url)
        populate(SMALL, LARGE)
        large = self._count(url)
        if self.last_items is not None:
            self.assertEqual(self.last_items, LARGE * per_item, 'la lista no devolvio todos los items (test vacio)')
        self.assertLessEqual(
            large, small + slack,
            f"{url_name}: {small} queries con {SMALL} items -> {large} con {LARGE} (N+1)\n" + self._repeated(),
        )


class ListQueryScalingTests(QueryScalingMixin, TestCase):
    def setUp(self):
        self.viewer = _user("viewer")

    def test_feed(self):
        def populate(start, end):
            for i in range(start, end):
                task = _rich_task(i)
                ms.SharedTask.objects.create(task=task, shared_by=_user(f"s{i}"))
        self.assert_constant("feed", populate)

    def test_task_list(self):
        def populate(start, end):
            for i in range(start, end):
                _rich_task(i)
        self.assert_constant("task-list-create", populate)

    def test_shared_task_list(self):
        def populate(start, end):
            for i in range(start, end):
                task = _rich_task(i)
                ms.SharedTask.objects.create(task=task, shared_by=_user(f"s{i}"))
        self.assert_constant("shared-task-list-create", populate)

    def test_forum_posts(self):
        def populate(start, end):
            for i in range(start, end):
                post = ms.Postt.objects.create(user=_user(f"a{i}"), title=f"p{i}", content="c")
                ms.Postt.objects.create(user=_user(f"r{i}"), content="re", parent=post)
        self.assert_constant("post-list-create", populate)

    def test_notifications(self):
        def populate(start, end):
            for i in range(start, end):
                ms.Notification.objects.create(
                    recipient=self.viewer, actor=_user(f"a{i}"), notification_type="like"
                )
        self.assert_constant("notification-list", populate)

    def test_conversations(self):
        def populate(start, end):
            for i in range(start, end):
                other = _user(f"c{i}")
                Message.objects.create(sender=other, receiver=self.viewer, content="hola")
                Message.objects.create(sender=self.viewer, receiver=other, content="hey")
                group = Group.objects.create(name=f"g{i}", created_by=other)
                GroupMembership.objects.create(user=self.viewer, group=group)
                GroupMembership.objects.create(user=other, group=group)
                GroupMessage.objects.create(group=group, sender=other, content="grupo")
        self.assert_constant("unified-conversations", populate, per_item=2)
