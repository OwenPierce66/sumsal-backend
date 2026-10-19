from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api import models as ms

User = get_user_model()


class TemporalLikeSortingTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(
            username="ranking-viewer",
            email="ranking-viewer@example.com",
            password="test-password",
        )
        self.author = User.objects.create_user(
            username="ranking-author",
            email="ranking-author@example.com",
            password="test-password",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.viewer)
        self.old_popular = ms.Task.objects.create(
            user=self.author,
            title="Popular antes del periodo",
        )
        self.period_popular = ms.Task.objects.create(
            user=self.author,
            title="Popular dentro del periodo",
            pch="consejos",
        )
        self.no_recent_votes = ms.Task.objects.create(
            user=self.author,
            title="Sin votos recientes",
        )

        old_likes = [
            ms.Like.objects.create(user=self._user(f"old-{index}"), task=self.old_popular)
            for index in range(3)
        ]
        ms.Like.objects.filter(pk__in=[like.pk for like in old_likes]).update(
            created_at=timezone.now() - timedelta(days=35)
        )
        for index in range(2):
            ms.Like.objects.create(
                user=self._user(f"recent-{index}"),
                task=self.period_popular,
            )

    def _user(self, username):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="test-password",
        )

    def _titles(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        return [item["title"] for item in response.data["results"]]

    def test_task_top_periods_count_likes_created_in_each_period(self):
        for sort_by, old_expected in (
            ("top_day", False),
            ("top_week", False),
            ("top_month", False),
            ("likes", True),
        ):
            with self.subTest(sort_by=sort_by):
                titles = self._titles(
                    self.client.get(
                        reverse("task-list-create"),
                        {"sort_by": sort_by},
                    )
                )
                if old_expected:
                    self.assertEqual(titles[0], self.old_popular.title)
                else:
                    self.assertEqual(titles[0], self.period_popular.title)
                    self.assertGreater(titles.index(self.old_popular.title), titles.index(self.period_popular.title))

    def test_shared_task_top_period_uses_task_like_activity(self):
        old_shared = ms.SharedTask.objects.create(
            task=self.old_popular,
            shared_by=self._user("old-sharer"),
        )
        period_shared = ms.SharedTask.objects.create(
            task=self.period_popular,
            shared_by=self._user("period-sharer"),
        )

        response = self.client.get(
            reverse("shared-task-list-create"),
            {"sort_by": "top_month"},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(str(response.data["results"][0]["id"]), str(period_shared.id))
        self.assertGreater(
            [str(item["id"]) for item in response.data["results"]].index(str(old_shared.id)),
            0,
        )

    def test_temporal_scores_are_exposed_for_mixed_feed_ordering(self):
        shared = ms.SharedTask.objects.create(
            task=self.period_popular,
            shared_by=self._user("score-sharer"),
        )
        task_response = self.client.get(
            reverse("task-list-create"),
            {"sort_by": "top_month"},
        )
        shared_response = self.client.get(
            reverse("shared-task-list-create"),
            {"sort_by": "top_month"},
        )

        task_result = next(
            item for item in task_response.data["results"]
            if item["id"] == str(self.period_popular.id)
        )
        shared_result = next(
            item for item in shared_response.data["results"]
            if item["id"] == str(shared.id)
        )
        self.assertEqual(task_result["period_likes_count"], 2)
        self.assertEqual(shared_result["period_likes_count"], 2)

    def test_shared_task_filter_respects_pch(self):
        other_topic_task = ms.Task.objects.create(
            user=self.author,
            title="Peticiones solamente",
            pch="peticiones",
        )
        expected = ms.SharedTask.objects.create(
            task=self.period_popular,
            shared_by=self._user("expected-topic-sharer"),
        )
        ms.SharedTask.objects.create(
            task=other_topic_task,
            shared_by=self._user("other-topic-sharer"),
        )

        response = self.client.get(
            reverse("shared-task-list-create"),
            {"pch": "consejos"},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [str(item["id"]) for item in response.data["results"]],
            [str(expected.id)],
        )
