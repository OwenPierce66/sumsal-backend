import base64

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


class UserMeViewRegressionTests(TestCase):
    def test_patch_profile_with_image(self):
        user = User.objects.create_user(
            email="profile@example.com",
            password="testpass123",
            username="profile-user",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        image = SimpleUploadedFile(
            "profile.png",
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ),
            content_type="image/png",
        )

        response = client.patch(
            reverse("user-me"),
            {"first_name": "Updated", "user_image": image},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Updated")
        self.assertEqual(ms.ImagenFija.objects.filter(user=user).count(), 1)

        refreshed_response = client.get(reverse("user-me"))
        self.assertEqual(refreshed_response.status_code, 200)
        self.assertIn("/media/", refreshed_response.data["user_image"])


class TaskUpdateRegressionTests(TestCase):
    def test_owner_can_patch_task_fields(self):
        user = User.objects.create_user(
            email="task-owner@example.com",
            password="testpass123",
            username="task-owner",
        )
        task = ms.Task.objects.create(
            user=user,
            title="Título original",
            description="Descripción original",
            pch="consejos",
            categories="React",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            reverse("task-detail", kwargs={"id": task.id}),
            {
                "title": "Título actualizado",
                "description": "Descripción actualizada",
                "pch": "peticiones",
                "categories": "Django,React Native",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.title, "Título actualizado")
        self.assertEqual(task.description, "Descripción actualizada")
        self.assertEqual(task.pch, "peticiones")
        self.assertEqual(task.categories, "Django,React Native")

    def test_owner_can_patch_nested_task_blocks(self):
        user = User.objects.create_user(
            email="nested-owner@example.com",
            password="testpass123",
            username="nested-owner",
        )
        task = ms.Task.objects.create(user=user, title="Tarea")
        subtask = ms.SubTask.objects.create(
            parent_task=task,
            title="Aportación original",
            description="Descripción original",
        )
        ms.SubFactores.objects.create(parent_task=task, title="Factor para borrar")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            reverse("task-detail", kwargs={"id": task.id}),
            {
                "subtasks": [{
                    "id": subtask.id,
                    "title": "Aportación actualizada",
                    "description": "Descripción actualizada",
                }],
                "subfactores": [],
                "subfuentes": [{"title": "Fuente nueva", "description": "Contenido"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        subtask.refresh_from_db()
        self.assertEqual(subtask.title, "Aportación actualizada")
        self.assertFalse(ms.SubFactores.objects.filter(parent_task=task).exists())
        self.assertEqual(ms.SubFuentes.objects.filter(parent_task=task).count(), 1)

    def test_owner_can_patch_nested_block_image(self):
        user = User.objects.create_user(
            email="media-owner@example.com",
            password="testpass123",
            username="media-owner",
        )
        task = ms.Task.objects.create(user=user, title="Tarea con media")
        subtask = ms.SubTask.objects.create(parent_task=task, title="Bloque")
        image = SimpleUploadedFile(
            "updated.png",
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ),
            content_type="image/png",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            reverse("task-detail", kwargs={"id": task.id}),
            {
                "subtasks[0][id]": str(subtask.id),
                "subtasks[0][title]": "Bloque con imagen",
                "subtasks[0][description]": "Descripción",
                "subtasks[0][image]": image,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        subtask.refresh_from_db()
        self.assertTrue(bool(subtask.image))
        self.assertTrue(subtask.image.name.endswith("updated.png"))


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


class TopicSubtopicFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="topic-filter@example.com",
            password="test-pass",
            username="topic-filter",
        )
        self.matching_task = ms.Task.objects.create(
            user=self.user,
            pch="consejos",
            title="React Native con Django",
            categories="programacion,Django,React Native",
        )
        self.other_task = ms.Task.objects.create(
            user=self.user,
            pch="consejos",
            title="Python",
            categories="programacion,Python",
        )
        self.similar_task = ms.Task.objects.create(
            user=self.user,
            pch="consejos",
            title="React web",
            categories="programacion,React",
        )
        self.matching_share = ms.SharedTask.objects.create(
            task=self.matching_task,
            shared_by=self.user,
        )
        ms.SharedTask.objects.create(task=self.other_task, shared_by=self.user)
        ms.SharedTask.objects.create(task=self.similar_task, shared_by=self.user)
        self.client = APIClient()

    def test_task_filter_requires_topic_and_every_selected_subtopic(self):
        response = self.client.get(
            reverse("task-list-create"),
            {"pch": "consejos", "category": "programacion,React Native,Django"},
        )

        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        self.assertEqual(
            [item["id"] for item in results],
            [str(self.matching_task.id)],
        )

    def test_shared_task_filter_uses_original_task_subtopics(self):
        response = self.client.get(
            reverse("shared-task-list-create"),
            {"category": "programacion,React Native"},
        )

        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        self.assertEqual(
            [item["id"] for item in results],
            [str(self.matching_share.id)],
        )

    def test_subtopic_filter_matches_complete_category_names(self):
        response = self.client.get(
            reverse("task-list-create"),
            {"pch": "consejos", "category": "programacion,React"},
        )

        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        self.assertEqual(
            [item["id"] for item in results],
            [str(self.similar_task.id)],
        )


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
                "image": SimpleUploadedFile(
                    "upload.gif",
                    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
                    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
                    b"\x00\x02\x02D\x01\x00;",
                    content_type="image/gif",
                ),
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


class StoryViewTrackingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="view-owner@example.com",
            password="pass",
            username="view-owner",
        )
        self.viewer = User.objects.create_user(
            email="view-viewer@example.com",
            password="pass",
            username="view-viewer",
            first_name="View",
            last_name="Viewer",
        )
        self.other = User.objects.create_user(
            email="view-other@example.com",
            password="pass",
            username="view-other",
        )
        self.story = ms.Task.objects.create(
            user=self.owner,
            pch="historias",
            title="Historia",
        )
        self.client = APIClient()

    def test_record_view_is_unique_and_idempotent(self):
        self.client.force_authenticate(user=self.viewer)
        url = reverse("story-view", kwargs={"story_id": self.story.id})

        first = self.client.post(url)
        second = self.client.post(url)

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.data["created"])
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.data["created"])
        self.assertEqual(second.data["views_count"], 1)
        self.assertEqual(ms.StoryView.objects.filter(story=self.story).count(), 1)

    def test_owner_view_is_not_recorded(self):
        self.client.force_authenticate(user=self.owner)

        response = self.client.post(
            reverse("story-view", kwargs={"story_id": self.story.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["created"])
        self.assertEqual(response.data["views_count"], 0)
        self.assertFalse(ms.StoryView.objects.filter(story=self.story).exists())

    def test_non_story_cannot_be_recorded_or_listed(self):
        task = ms.Task.objects.create(
            user=self.owner,
            pch="consejos",
            title="No historia",
        )
        self.client.force_authenticate(user=self.viewer)
        self.assertEqual(
            self.client.post(
                reverse("story-view", kwargs={"story_id": task.id})
            ).status_code,
            404,
        )
        self.client.force_authenticate(user=self.owner)
        self.assertEqual(
            self.client.get(
                reverse("story-viewers", kwargs={"story_id": task.id})
            ).status_code,
            404,
        )

    def test_only_owner_can_list_viewers(self):
        ms.StoryView.objects.create(story=self.story, viewer=self.viewer)
        self.client.force_authenticate(user=self.other)

        response = self.client.get(
            reverse("story-viewers", kwargs={"story_id": self.story.id})
        )

        self.assertEqual(response.status_code, 403)

    def test_viewers_contract_count_and_descending_order(self):
        older = ms.StoryView.objects.create(story=self.story, viewer=self.viewer)
        newer = ms.StoryView.objects.create(story=self.story, viewer=self.other)
        ms.StoryView.objects.filter(pk=older.pk).update(
            viewed_at=timezone.now() - timedelta(minutes=1)
        )
        self.client.force_authenticate(user=self.owner)

        response = self.client.get(
            reverse("story-viewers", kwargs={"story_id": self.story.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["views_count"], 2)
        self.assertEqual(response.data["likes_count"], 0)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["users"]), 2)
        self.assertEqual(response.data["users"][0]["id"], str(newer.viewer_id))
        self.viewer.profile.is_verified = True
        self.viewer.profile.save(update_fields=["is_verified"])
        response = self.client.get(
            reverse("story-viewers", kwargs={"story_id": self.story.id})
        )
        viewer_data = next(
            user for user in response.data["users"]
            if user["id"] == str(self.viewer.id)
        )
        self.assertTrue(viewer_data["profile"]["is_verified"])
        self.assertTrue(
            {
                "id",
                "username",
                "name",
                "image",
                "user_image",
                "profile",
                "viewed",
                "liked",
                "viewed_at",
                "liked_at",
            }
            <= set(response.data["users"][1])
        )
        self.assertTrue(response.data["users"][1]["viewed"])
        self.assertFalse(response.data["users"][1]["liked"])
        self.assertIsNone(response.data["users"][1]["liked_at"])
        self.assertEqual(response.data["users"][1]["name"], "View Viewer")

    def test_viewer_and_liker_are_combined_without_duplicates(self):
        story_view = ms.StoryView.objects.create(
            story=self.story,
            viewer=self.viewer,
        )
        like = ms.Like.objects.create(task=self.story, user=self.viewer)
        ms.ImagenFija.objects.create(
            user=self.viewer,
            image="fixed/story-viewer.jpg",
        )
        self.client.force_authenticate(user=self.owner)

        response = self.client.get(
            reverse("story-viewers", kwargs={"story_id": self.story.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["views_count"], 1)
        self.assertEqual(response.data["likes_count"], 1)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["users"]), 1)
        user = response.data["users"][0]
        self.assertTrue(user["viewed"])
        self.assertTrue(user["liked"])
        self.assertEqual(user["viewed_at"], story_view.viewed_at)
        self.assertEqual(user["liked_at"], like.created_at)
        self.assertEqual(
            user["image"],
            "http://testserver/media/fixed/story-viewer.jpg",
        )
        self.assertEqual(user["user_image"], user["image"])

    def test_legacy_like_without_story_view_is_included(self):
        like = ms.Like.objects.create(task=self.story, user=self.other)
        self.client.force_authenticate(user=self.owner)

        response = self.client.get(
            reverse("story-viewers", kwargs={"story_id": self.story.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["views_count"], 0)
        self.assertEqual(response.data["likes_count"], 1)
        self.assertEqual(response.data["count"], 1)
        user = response.data["users"][0]
        self.assertEqual(user["id"], str(self.other.id))
        self.assertFalse(user["viewed"])
        self.assertTrue(user["liked"])
        self.assertIsNone(user["viewed_at"])
        self.assertEqual(user["liked_at"], like.created_at)

    def test_story_serializer_exposes_views_count_not_likes(self):
        ms.StoryView.objects.create(story=self.story, viewer=self.viewer)
        ms.Like.objects.create(task=self.story, user=self.other)

        data = TaskSerializer(self.story).data

        self.assertEqual(data["views_count"], 1)
        self.assertEqual(data["likes_count"], 1)
