from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from django.test import TestCase

from massaging.models import (
    Group,
    GroupMembership,
    GroupMessage,
    Message,
    MessageLike,
)

from .models import (
    Favorito,
    Like,
    LikeP,
    LikePostt,
    LikeSharedTask,
    LikeSharedTaskComment,
    NewPeticionCommentPost,
    Notification,
    Postt,
    SharedTask,
    SharedTaskComment,
    Task,
    pFavorito,
)
from .notifications import create_notification


User = get_user_model()


class NotificationAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="recipient@example.com",
            password="test-pass",
            username="recipient",
        )
        self.other = User.objects.create_user(
            email="other@example.com",
            password="test-pass",
            username="other",
        )
        self.actor = User.objects.create_user(
            email="actor@example.com",
            password="test-pass",
            username="actor",
            first_name="Actor",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make_notification(self, recipient=None, key="test"):
        return create_notification(
            recipient=recipient or self.user,
            actor=self.actor,
            notification_type="task_like",
            target_type="task",
            target_id="task-id",
            data={"text": "Actor indicó que le gusta tu tarea.", "title": "Tarea"},
            dedupe_key=key,
        )

    def test_list_is_paginated_filtered_and_isolated_by_recipient(self):
        own = self.make_notification(key="own")
        own_read = self.make_notification(key="own-read")
        own_read.is_read = True
        own_read.save(update_fields=["is_read"])
        self.make_notification(recipient=self.other, key="other")

        response = self.client.get(reverse("notification-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            {item["id"] for item in response.data["results"]},
            {str(own.id), str(own_read.id)},
        )
        item = next(item for item in response.data["results"] if item["id"] == str(own.id))
        self.assertEqual(item["actor"]["username"], "actor")
        self.assertEqual(item["actor"]["name"], "Actor")
        self.assertEqual(item["type"], "task_like")
        self.assertEqual(item["target_type"], "task")
        self.assertEqual(item["data"]["title"], "Tarea")

        unread = self.client.get(reverse("notification-list"), {"unread": "true"})
        self.assertEqual(unread.data["count"], 1)
        self.assertEqual(unread.data["results"][0]["id"], str(own.id))

    def test_helper_deduplicates_the_same_action(self):
        first = self.make_notification(key="same-action")
        second = self.make_notification(key="same-action")

        self.assertEqual(first.id, second.id)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.user,
                dedupe_key="same-action",
            ).count(),
            1,
        )

    def test_unread_mark_one_mark_all_and_delete(self):
        first = self.make_notification(key="first")
        second = self.make_notification(key="second")

        count = self.client.get(reverse("notification-unread-count"))
        self.assertEqual(count.data, {"unread_count": 2})

        marked = self.client.post(
            reverse("notification-mark-read", args=[first.id]),
            format="json",
        )
        self.assertEqual(marked.status_code, 200)
        self.assertTrue(marked.data["is_read"])
        self.assertIsNotNone(marked.data["read_at"])

        all_marked = self.client.post(
            reverse("notification-mark-all-read"),
            format="json",
        )
        self.assertEqual(all_marked.data, {"updated": 1})
        self.assertFalse(
            Notification.objects.filter(recipient=self.user, is_read=False).exists()
        )

        deleted = self.client.delete(reverse("notification-delete", args=[second.id]))
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(Notification.objects.filter(id=second.id).exists())

    def test_cannot_read_modify_or_delete_another_users_notification(self):
        foreign = self.make_notification(recipient=self.other, key="foreign")

        listed = self.client.get(reverse("notification-list"))
        self.assertEqual(listed.data["count"], 0)
        marked = self.client.post(
            reverse("notification-mark-read", args=[foreign.id]),
            format="json",
        )
        deleted = self.client.delete(
            reverse("notification-delete", args=[foreign.id])
        )

        self.assertEqual(marked.status_code, 404)
        self.assertEqual(deleted.status_code, 404)
        foreign.refresh_from_db()
        self.assertFalse(foreign.is_read)


class NotificationSignalTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-pass",
            username="owner",
        )
        self.actor = User.objects.create_user(
            email="actor@example.com",
            password="test-pass",
            username="actor",
        )
        self.third = User.objects.create_user(
            email="third@example.com",
            password="test-pass",
            username="third",
        )
        self.task = Task.objects.create(
            user=self.owner,
            title="Tarea notificable",
            description="Descripción",
        )

    def test_no_self_notification_and_like_is_created_then_retired(self):
        Like.objects.create(user=self.owner, task=self.task)
        self.assertFalse(Notification.objects.exists())

        like = Like.objects.create(user=self.actor, task=self.task)
        notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="task_like",
        )
        self.assertEqual(notification.actor, self.actor)
        self.assertEqual(notification.target_id, str(self.task.id))

        like.delete()
        self.assertFalse(Notification.objects.filter(id=notification.id).exists())

    def test_notification_survives_social_target_and_actor_deletion(self):
        like = Like.objects.create(user=self.actor, task=self.task)
        target_id = str(self.task.id)
        notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="task_like",
        )

        self.task.delete()
        notification.refresh_from_db()
        self.assertEqual(notification.target_id, target_id)

        self.actor.delete()
        notification.refresh_from_db()
        self.assertIsNone(notification.actor)
        self.assertFalse(Like.objects.filter(id=like.id).exists())

    def test_comment_and_reply_prioritize_the_replied_author(self):
        comment = NewPeticionCommentPost.objects.create(
            created_by=self.actor,
            post=self.task,
            text="Comentario raíz",
        )
        root_notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="task_comment",
        )
        self.assertEqual(root_notification.secondary_target_id, str(comment.id))

        reply = NewPeticionCommentPost.objects.create(
            created_by=self.third,
            post=self.task,
            parent=comment,
            text="Respuesta",
        )
        reply_notification = Notification.objects.get(
            recipient=self.actor,
            notification_type="task_reply",
        )
        self.assertEqual(reply_notification.secondary_target_id, str(reply.id))
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.owner,
                notification_type="task_reply",
            ).exists()
        )

    def test_share_notifies_task_owner(self):
        shared = SharedTask.objects.create(
            task=self.task,
            shared_by=self.actor,
            description="Mira esto",
        )

        notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="task_shared",
        )
        self.assertEqual(notification.target_type, "shared_task")
        self.assertEqual(notification.target_id, str(shared.id))
        self.assertEqual(notification.secondary_target_id, str(self.task.id))

    def test_direct_message_and_reply_notify_the_expected_recipient(self):
        message = Message.objects.create(
            sender=self.actor,
            receiver=self.owner,
            content="Hola",
        )
        received = Notification.objects.get(
            recipient=self.owner,
            notification_type="direct_message",
        )
        self.assertEqual(received.target_type, "direct_chat")
        self.assertEqual(received.target_id, str(self.actor.id))

        Message.objects.create(
            sender=self.owner,
            receiver=self.actor,
            content="Respuesta",
            replied_to=message,
        )
        reply = Notification.objects.get(
            recipient=self.actor,
            notification_type="direct_message_reply",
        )
        self.assertEqual(reply.target_id, str(self.owner.id))

    def test_group_message_notifies_every_member_once_except_sender(self):
        group = Group.objects.create(name="Equipo", created_by=self.actor)
        for user in (self.actor, self.owner, self.third):
            GroupMembership.objects.create(user=user, group=group)

        message = GroupMessage.objects.create(
            group=group,
            sender=self.actor,
            content="Mensaje grupal",
        )

        notifications = Notification.objects.filter(
            notification_type="group_message",
            secondary_target_id=str(message.id),
        )
        self.assertEqual(
            set(notifications.values_list("recipient_id", flat=True)),
            {self.owner.id, self.third.id},
        )

    def test_story_like_and_task_shared_to_story(self):
        story = Task.objects.create(
            user=self.owner,
            pch="historias",
            title="Historia original",
            description="Contenido de la historia",
        )
        like = Like.objects.create(user=self.actor, task=story)
        story_like = Notification.objects.get(
            recipient=self.owner,
            notification_type="story_like",
        )
        self.assertEqual(story_like.target_type, "story")
        self.assertEqual(story_like.target_id, str(story.id))
        self.assertEqual(story_like.data["title"], story.title)
        self.assertEqual(story_like.data["excerpt"], story.description)

        Like.objects.create(user=self.owner, task=story)
        self.assertEqual(
            Notification.objects.filter(notification_type="story_like").count(),
            1,
        )
        like.delete()
        self.assertFalse(Notification.objects.filter(id=story_like.id).exists())

        shared_story = Task.objects.create(
            user=self.actor,
            pch="historias",
            title="Historia compartida",
            description="Extracto compartido",
            story_is_shared=True,
            story_source_task=self.task,
        )
        shared_notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="task_shared_to_story",
        )
        self.assertEqual(shared_notification.target_type, "story")
        self.assertEqual(shared_notification.target_id, str(shared_story.id))
        self.assertEqual(shared_notification.secondary_target_type, "task")
        self.assertEqual(shared_notification.secondary_target_id, str(self.task.id))
        self.assertEqual(shared_notification.data["title"], self.task.title)
        self.assertEqual(
            shared_notification.data["excerpt"],
            shared_story.description,
        )

        Task.objects.create(
            user=self.owner,
            pch="historias",
            title="Autocompartida",
            story_is_shared=True,
            story_source_task=self.task,
        )
        self.assertEqual(
            Notification.objects.filter(
                notification_type="task_shared_to_story"
            ).count(),
            1,
        )

    def test_shared_task_comment_reply_and_delete(self):
        shared = SharedTask.objects.create(task=self.task, shared_by=self.owner)
        comment = SharedTaskComment.objects.create(
            shared_task=shared,
            created_by=self.actor,
            text="Comentario compartido",
        )
        comment_notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="shared_task_comment",
        )
        self.assertEqual(comment_notification.target_type, "shared_task")
        self.assertEqual(comment_notification.target_id, str(shared.id))
        self.assertEqual(comment_notification.secondary_target_type, "comment")
        self.assertEqual(comment_notification.secondary_target_id, str(comment.id))
        self.assertEqual(comment_notification.data["title"], self.task.title)
        self.assertEqual(comment_notification.data["excerpt"], comment.text)

        SharedTaskComment.objects.create(
            shared_task=shared,
            created_by=self.owner,
            text="Comentario propio",
        )
        self.assertEqual(
            Notification.objects.filter(
                notification_type="shared_task_comment"
            ).count(),
            1,
        )

        reply = SharedTaskComment.objects.create(
            shared_task=shared,
            created_by=self.third,
            parent=comment,
            text="Respuesta compartida",
        )
        reply_notification = Notification.objects.get(
            recipient=self.actor,
            notification_type="shared_task_reply",
        )
        self.assertEqual(reply_notification.target_id, str(shared.id))
        self.assertEqual(reply_notification.secondary_target_id, str(reply.id))
        self.assertEqual(reply_notification.data["excerpt"], reply.text)
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.owner,
                notification_type="shared_task_reply",
            ).exists()
        )

        reply.delete()
        self.assertFalse(Notification.objects.filter(id=reply_notification.id).exists())
        comment.delete()
        self.assertFalse(
            Notification.objects.filter(id=comment_notification.id).exists()
        )

    def test_shared_task_and_shared_comment_likes_are_retired(self):
        shared = SharedTask.objects.create(task=self.task, shared_by=self.owner)
        shared_like = LikeSharedTask.objects.create(
            user=self.actor,
            shared_task=shared,
        )
        like_notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="shared_task_like",
        )
        self.assertEqual(like_notification.target_type, "shared_task")
        self.assertEqual(like_notification.target_id, str(shared.id))
        self.assertEqual(like_notification.secondary_target_id, str(self.task.id))
        self.assertEqual(like_notification.data["title"], self.task.title)

        LikeSharedTask.objects.create(user=self.owner, shared_task=shared)
        self.assertEqual(
            Notification.objects.filter(notification_type="shared_task_like").count(),
            1,
        )
        shared_like.delete()
        self.assertFalse(Notification.objects.filter(id=like_notification.id).exists())

        comment = SharedTaskComment.objects.create(
            shared_task=shared,
            created_by=self.actor,
            text="Comentario para like",
        )
        comment_like = LikeSharedTaskComment.objects.create(
            user=self.third,
            comment=comment,
        )
        comment_like_notification = Notification.objects.get(
            recipient=self.actor,
            notification_type="shared_task_comment_like",
        )
        self.assertEqual(comment_like_notification.target_type, "shared_task")
        self.assertEqual(comment_like_notification.target_id, str(shared.id))
        self.assertEqual(
            comment_like_notification.secondary_target_id,
            str(comment.id),
        )
        self.assertEqual(comment_like_notification.data["title"], self.task.title)
        self.assertEqual(comment_like_notification.data["excerpt"], comment.text)

        LikeSharedTaskComment.objects.create(user=self.actor, comment=comment)
        self.assertEqual(
            Notification.objects.filter(
                notification_type="shared_task_comment_like"
            ).count(),
            1,
        )
        comment_like.delete()
        self.assertFalse(
            Notification.objects.filter(id=comment_like_notification.id).exists()
        )

    def test_profile_like_and_favorites_are_created_and_retired(self):
        profile_like = LikeP.objects.create(user=self.actor, profile=self.owner)
        profile_like_notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="profile_like",
        )
        self.assertEqual(profile_like_notification.target_type, "profile")
        self.assertEqual(profile_like_notification.target_id, str(self.owner.id))

        LikeP.objects.create(user=self.owner, profile=self.owner)
        self.assertEqual(
            Notification.objects.filter(notification_type="profile_like").count(),
            1,
        )
        profile_like.delete()
        self.assertFalse(
            Notification.objects.filter(id=profile_like_notification.id).exists()
        )

        task_favorite = Favorito.objects.create(user=self.actor, task=self.task)
        task_favorite_notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="task_favorite",
        )
        self.assertEqual(task_favorite_notification.target_type, "task")
        self.assertEqual(task_favorite_notification.target_id, str(self.task.id))
        self.assertEqual(task_favorite_notification.data["title"], self.task.title)

        Favorito.objects.create(user=self.owner, task=self.task)
        self.assertEqual(
            Notification.objects.filter(notification_type="task_favorite").count(),
            1,
        )
        task_favorite.delete()
        self.assertFalse(
            Notification.objects.filter(id=task_favorite_notification.id).exists()
        )

        profile_favorite = pFavorito.objects.create(
            user=self.actor,
            perfil=self.owner,
        )
        profile_favorite_notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="profile_favorite",
        )
        self.assertEqual(profile_favorite_notification.target_type, "profile")
        self.assertEqual(profile_favorite_notification.target_id, str(self.owner.id))

        pFavorito.objects.create(user=self.owner, perfil=self.owner)
        self.assertEqual(
            Notification.objects.filter(
                notification_type="profile_favorite"
            ).count(),
            1,
        )
        profile_favorite.delete()
        self.assertFalse(
            Notification.objects.filter(id=profile_favorite_notification.id).exists()
        )

    def test_forum_reply_and_like_are_created_and_retired(self):
        post = Postt.objects.create(
            user=self.owner,
            title="Tema del foro",
            content="Contenido del foro",
        )
        reply = Postt.objects.create(
            user=self.actor,
            parent=post,
            content="Respuesta del foro",
        )
        reply_notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="forum_reply",
        )
        self.assertEqual(reply_notification.target_type, "forum_post")
        self.assertEqual(reply_notification.target_id, str(post.id))
        self.assertEqual(reply_notification.secondary_target_type, "forum_reply")
        self.assertEqual(reply_notification.secondary_target_id, str(reply.id))
        self.assertEqual(reply_notification.data["title"], post.title)
        self.assertEqual(reply_notification.data["excerpt"], reply.content)

        Postt.objects.create(
            user=self.owner,
            parent=post,
            content="Respuesta propia",
        )
        self.assertEqual(
            Notification.objects.filter(notification_type="forum_reply").count(),
            1,
        )
        reply.delete()
        self.assertFalse(Notification.objects.filter(id=reply_notification.id).exists())

        post_like = LikePostt.objects.create(user=self.actor, post=post)
        like_notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="forum_post_like",
        )
        self.assertEqual(like_notification.target_type, "forum_post")
        self.assertEqual(like_notification.target_id, str(post.id))
        self.assertEqual(like_notification.data["title"], post.title)
        self.assertEqual(like_notification.data["excerpt"], post.content)

        LikePostt.objects.create(user=self.owner, post=post)
        self.assertEqual(
            Notification.objects.filter(notification_type="forum_post_like").count(),
            1,
        )
        post_like.delete()
        self.assertFalse(Notification.objects.filter(id=like_notification.id).exists())

    def test_direct_message_like_is_created_and_retired(self):
        message = Message.objects.create(
            sender=self.owner,
            receiver=self.actor,
            content="Mensaje con like",
        )
        message_like = MessageLike.objects.create(user=self.actor, message=message)
        notification = Notification.objects.get(
            recipient=self.owner,
            notification_type="direct_message_like",
        )
        self.assertEqual(notification.target_type, "direct_chat")
        self.assertEqual(notification.target_id, str(self.actor.id))
        self.assertEqual(notification.secondary_target_type, "message")
        self.assertEqual(notification.secondary_target_id, str(message.id))
        self.assertEqual(notification.data["excerpt"], message.content)

        MessageLike.objects.create(user=self.owner, message=message)
        self.assertEqual(
            Notification.objects.filter(
                notification_type="direct_message_like"
            ).count(),
            1,
        )
        message_like.delete()
        self.assertFalse(Notification.objects.filter(id=notification.id).exists())
