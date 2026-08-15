from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIRequestFactory
from rest_framework.test import APIClient

from api import models as ms
from api.views import SharedTaskListCreateView
from api.serializers import SharedTaskSerializer, TaskSerializer

User = get_user_model()


class SharedTaskViewRegressionTests(TestCase):
    def test_shared_task_list_view_uses_shared_task_serializer(self):
        view = SharedTaskListCreateView()
        self.assertEqual(view.get_serializer_class(), SharedTaskSerializer)

    def test_shared_task_list_endpoint_returns_200_for_anonymous_get(self):
        client = APIClient()
        response = client.get(reverse("shared-task-list-create"))
        self.assertIn(response.status_code, {200, 404})

    def test_task_serializer_shared_by_list_includes_share_description(self):
        owner = User.objects.create_user(
            email="owner@example.com",
            password="testpass123",
            username="owner",
        )
        sharer = User.objects.create_user(
            email="sharer@example.com",
            password="testpass123",
            username="sharer",
        )
        task = ms.Task.objects.create(user=owner, title="Reel original")
        ms.SharedTask.objects.create(
            task=task,
            shared_by=sharer,
            description="Texto del que compartio",
        )

        serialized = TaskSerializer(task).data

        self.assertEqual(len(serialized["shared_by_list"]), 1)
        self.assertEqual(str(serialized["shared_by_list"][0]["id"]), str(sharer.id))
        self.assertEqual(serialized["shared_by_list"][0]["username"], "sharer")
        self.assertEqual(serialized["shared_by_list"][0]["description"], "Texto del que compartio")

    def test_task_serializer_includes_last_favorite_sharer_for_request_user(self):
        viewer = User.objects.create_user(
            email="viewer@example.com",
            password="testpass123",
            username="viewer",
        )
        owner = User.objects.create_user(
            email="owner2@example.com",
            password="testpass123",
            username="owner2",
        )
        favorite_sharer = User.objects.create_user(
            email="favorite@example.com",
            password="testpass123",
            username="favorite-sharer",
        )
        non_favorite_sharer = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            username="other-sharer",
        )
        task = ms.Task.objects.create(user=owner, title="Reel con favorito")
        ms.pFavorito.objects.create(user=viewer, perfil=favorite_sharer)
        ms.SharedTask.objects.create(
            task=task,
            shared_by=non_favorite_sharer,
            description="No favorito",
        )
        ms.SharedTask.objects.create(
            task=task,
            shared_by=favorite_sharer,
            description="Favorito reciente",
        )

        request = APIRequestFactory().get("/api/tasks/")
        request.user = viewer
        serialized = TaskSerializer(task, context={"request": request}).data

        self.assertEqual(serialized["favorite_sharers_count"], 1)
        self.assertEqual(len(serialized["favorite_shared_by_list"]), 1)
        self.assertEqual(str(serialized["favorite_shared_by"]["id"]), str(favorite_sharer.id))
        self.assertEqual(serialized["favorite_shared_by"]["username"], "favorite-sharer")
        self.assertEqual(serialized["favorite_shared_by"]["description"], "Favorito reciente")


class pFavoritoViewRegressionTests(TestCase):
    def test_agregar_pfavorito_accepts_user_uuid_target(self):
        viewer = User.objects.create_user(email="viewer@example.com", password="password123")
        target_user = User.objects.create_user(email="target@example.com", password="password123")
        target_profile = target_user.profile

        client = APIClient()
        client.force_authenticate(user=viewer)

        response = client.post(
            reverse("agregar-pfavorito"),
            {"perfil_id": str(target_user.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(ms.pFavorito.objects.filter(user=viewer, perfil=target_user).exists())


class StoryViewRegressionTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(
            email="story-viewer@example.com",
            password="storypass123",
            username="story-viewer",
        )
        self.owner = User.objects.create_user(
            email="story-owner@example.com",
            password="storypass123",
            username="story-owner",
        )
        self.client = APIClient()

    def test_story_list_only_includes_recent_histories_with_media(self):
        recent_story = ms.Task.objects.create(
            user=self.owner,
            pch="historias",
            title="Story reciente",
            image=SimpleUploadedFile("recent.jpg", b"recent-image", content_type="image/jpeg"),
        )
        stale_story = ms.Task.objects.create(
            user=self.owner,
            pch="historias",
            title="Story vieja",
            image=SimpleUploadedFile("stale.jpg", b"stale-image", content_type="image/jpeg"),
        )
        non_story = ms.Task.objects.create(
            user=self.owner,
            pch="consejos",
            title="No story",
            image=SimpleUploadedFile("other.jpg", b"other-image", content_type="image/jpeg"),
        )
        no_media_story = ms.Task.objects.create(
            user=self.owner,
            pch="historias",
            title="Sin media",
        )
        ms.Task.objects.filter(id=stale_story.id).update(created_at=timezone.now() - timedelta(hours=25))

        response = self.client.get(reverse("story-list-create"))
        self.assertEqual(response.status_code, 200)

        result_ids = {str(item["id"]) for item in response.data.get("results", [])}
        self.assertIn(str(recent_story.id), result_ids)
        self.assertNotIn(str(stale_story.id), result_ids)
        self.assertNotIn(str(non_story.id), result_ids)
        self.assertNotIn(str(no_media_story.id), result_ids)

    def test_story_create_forces_historias_and_uses_caption(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(
            reverse("story-list-create"),
            {
                "caption": "Texto de historia",
                "image": SimpleUploadedFile("upload.jpg", b"upload-image", content_type="image/jpeg"),
                "pch": "consejos",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        created = ms.Task.objects.get(id=response.data["id"])
        self.assertEqual(created.pch, "historias")
        self.assertEqual(created.description, "Texto de historia")
        self.assertEqual(created.user_id, self.viewer.id)

    def test_share_task_to_story_creates_historias_copy(self):
        source_task = ms.Task.objects.create(
            user=self.owner,
            pch="consejos",
            title="Original",
            description="Desc original",
            image=SimpleUploadedFile("orig.jpg", b"orig-image", content_type="image/jpeg"),
        )
        self.client.force_authenticate(user=self.viewer)

        response = self.client.post(
            reverse("story-share-task"),
            {"task_id": str(source_task.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        created = ms.Task.objects.get(id=response.data["id"])
        self.assertEqual(created.pch, "historias")
        self.assertEqual(created.user_id, self.viewer.id)
        self.assertEqual(created.username, self.owner.username)
        self.assertTrue(created.story_is_shared)
        self.assertEqual(created.story_source_task_id, source_task.id)
        self.assertEqual(created.title, source_task.title)
        self.assertEqual(created.description, source_task.description)
        self.assertTrue(bool(created.image))

    def test_share_task_to_story_uses_selected_subtask_media_and_title(self):
        source_task = ms.Task.objects.create(
            user=self.owner,
            pch="consejos",
            title="Tarea principal",
            description="Desc principal",
            image=SimpleUploadedFile("main.jpg", b"main-image", content_type="image/jpeg"),
        )
        subtask = ms.SubTask.objects.create(
            parent_task=source_task,
            title="Aportación puntual",
            description="Desc de la aportación",
            image=SimpleUploadedFile("subtask.jpg", b"sub-image", content_type="image/jpeg"),
        )
        self.client.force_authenticate(user=self.viewer)

        response = self.client.post(
            reverse("story-share-task"),
            {
                "task_id": str(source_task.id),
                "source_item_type": "subtasks",
                "source_item_id": str(subtask.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        created = ms.Task.objects.get(id=response.data["id"])
        self.assertEqual(created.title, source_task.title)
        self.assertEqual(created.description, subtask.description)
        self.assertEqual(response.data["source_task_title"], source_task.title)
        self.assertEqual(response.data["source_item_title"], subtask.title)
        self.assertEqual(response.data["source_item_description"], subtask.description)
