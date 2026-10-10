"""
Tests de Fase 28: registro de push tokens, envío a Expo, tarea Celery y señal.

Nunca se hace una llamada real a Expo: `requests.post` / `send_expo_push`
siempre se mockean. En los tests CELERY_TASK_ALWAYS_EAGER=True, por eso la
señal se prueba parcheando `.delay`.
"""
from types import SimpleNamespace
from unittest import mock

import requests
from celery.exceptions import Retry
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import Notification, PushToken
from api.tasks import (
    PushDeliveryError,
    _backoff_seconds,
    send_push_notification_task,
)
from api.utils.push_notifications import send_expo_push

User = get_user_model()

TOKEN_A = "ExponentPushToken[aaaaaaaaaaaaaaaaaaaaaa]"
TOKEN_B = "ExponentPushToken[bbbbbbbbbbbbbbbbbbbbbb]"


def make_user(name):
    return User.objects.create_user(
        username=name, email=f"{name}@example.com", password="pass12345"
    )


class PushTokenViewTests(TestCase):
    def setUp(self):
        self.user = make_user("alice")
        self.other = make_user("bob")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("push-token-register")

    def test_requires_authentication(self):
        res = APIClient().post(self.url, {"token": TOKEN_A}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_missing_or_blank_token_is_400(self):
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, 400)
        res = self.client.post(self.url, {"token": "   "}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_too_long_token_is_400_not_500(self):
        max_length = PushToken._meta.get_field("token").max_length
        res = self.client.post(
            self.url, {"token": "x" * (max_length + 1)}, format="json"
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(PushToken.objects.count(), 0)

    def test_create_then_update(self):
        res = self.client.post(self.url, {"token": TOKEN_A}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json(), {"registered": True})
        res = self.client.post(self.url, {"token": TOKEN_A}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(PushToken.objects.filter(token=TOKEN_A).count(), 1)

    def test_token_is_stripped(self):
        self.client.post(self.url, {"token": f"  {TOKEN_A}  "}, format="json")
        self.assertTrue(PushToken.objects.filter(token=TOKEN_A).exists())

    def test_platform_stored_and_invalid_falls_back_to_ios(self):
        self.client.post(
            self.url, {"token": TOKEN_A, "platform": "android"}, format="json"
        )
        self.assertEqual(PushToken.objects.get(token=TOKEN_A).platform, "android")
        self.client.post(
            self.url, {"token": TOKEN_B, "platform": "nokia"}, format="json"
        )
        self.assertEqual(PushToken.objects.get(token=TOKEN_B).platform, "ios")

    def test_delete_requires_authentication(self):
        res = APIClient().delete(self.url, {"token": TOKEN_A}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_delete_without_token_is_400(self):
        self.assertEqual(self.client.delete(self.url, {}, format="json").status_code, 400)

    def test_delete_deactivates_only_that_device(self):
        self.client.post(self.url, {"token": TOKEN_A}, format="json")
        self.client.post(self.url, {"token": TOKEN_B}, format="json")
        res = self.client.delete(self.url, {"token": TOKEN_A}, format="json")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(PushToken.objects.get(token=TOKEN_A).is_active)
        self.assertTrue(PushToken.objects.get(token=TOKEN_B).is_active)

    def test_delete_is_idempotent_and_ignores_unknown_tokens(self):
        res = self.client.delete(self.url, {"token": TOKEN_A}, format="json")
        self.assertEqual(res.status_code, 204)

    def test_delete_cannot_deactivate_another_users_token(self):
        PushToken.objects.create(user=self.other, token=TOKEN_B, is_active=True)
        res = self.client.delete(self.url, {"token": TOKEN_B}, format="json")
        self.assertEqual(res.status_code, 204)
        self.assertTrue(PushToken.objects.get(token=TOKEN_B).is_active)

    def test_multiple_devices_stay_active(self):
        self.client.post(self.url, {"token": TOKEN_A}, format="json")
        self.client.post(self.url, {"token": TOKEN_B}, format="json")
        active = set(
            PushToken.objects.filter(user=self.user, is_active=True).values_list(
                "token", flat=True
            )
        )
        self.assertEqual(active, {TOKEN_A, TOKEN_B})

    def test_active_tokens_are_capped_dropping_oldest(self):
        from api.push_views import MAX_ACTIVE_TOKENS_PER_USER

        tokens = [
            f"ExponentPushToken[device{i:02d}xxxxxxxxxxxxxx]"
            for i in range(MAX_ACTIVE_TOKENS_PER_USER + 1)
        ]
        for token in tokens:
            self.client.post(self.url, {"token": token}, format="json")
        active = PushToken.objects.filter(user=self.user, is_active=True)
        self.assertEqual(active.count(), MAX_ACTIVE_TOKENS_PER_USER)
        self.assertFalse(PushToken.objects.get(token=tokens[0]).is_active)
        self.assertTrue(PushToken.objects.get(token=tokens[-1]).is_active)

    def test_other_users_tokens_untouched_by_cap(self):
        PushToken.objects.create(user=self.other, token=TOKEN_B, is_active=True)
        self.client.post(self.url, {"token": TOKEN_A}, format="json")
        self.assertTrue(PushToken.objects.get(token=TOKEN_B).is_active)

    def test_token_is_reassigned_between_users(self):
        self.client.post(self.url, {"token": TOKEN_A}, format="json")
        other_client = APIClient()
        other_client.force_authenticate(self.other)
        other_client.post(self.url, {"token": TOKEN_A}, format="json")
        token = PushToken.objects.get(token=TOKEN_A)
        self.assertEqual(token.user, self.other)
        self.assertTrue(token.is_active)
        self.assertEqual(PushToken.objects.count(), 1)


class SendExpoPushTests(SimpleTestCase):
    POST = "api.utils.push_notifications.requests.post"

    def test_non_expo_tokens_are_filtered_without_http_call(self):
        with mock.patch(self.POST) as post:
            self.assertTrue(send_expo_push(["fcm-token", ""], "t", "b"))
        post.assert_not_called()

    def test_payload_and_timeout(self):
        with mock.patch(self.POST) as post:
            ok = send_expo_push(
                [TOKEN_A, "otro"], "Título", "Cuerpo", data={"k": 1}, badge=2
            )
        self.assertTrue(ok)
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://exp.host/push/send")
        self.assertEqual(kwargs["timeout"], 5)
        messages = kwargs["json"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["to"], TOKEN_A)
        self.assertEqual(messages[0]["title"], "Título")
        self.assertEqual(messages[0]["body"], "Cuerpo")
        self.assertEqual(messages[0]["data"], {"k": 1})
        self.assertEqual(messages[0]["badge"], 2)

    def test_returns_false_on_network_error(self):
        with mock.patch(self.POST, side_effect=requests.ConnectionError("boom")):
            self.assertFalse(send_expo_push([TOKEN_A], "t", "b"))

    def test_returns_false_on_http_error(self):
        response = mock.Mock()
        response.raise_for_status.side_effect = requests.HTTPError("500")
        with mock.patch(self.POST, return_value=response):
            self.assertFalse(send_expo_push([TOKEN_A], "t", "b"))


class PushTaskTests(SimpleTestCase):
    SEND = "api.tasks.send_expo_push"
    # Se llama la tarea directamente (sin worker) y se mockea `retry`.
    def _run(self, send_mock):
        retry = mock.Mock(side_effect=Retry())
        with mock.patch(self.SEND, send_mock), mock.patch.object(
            send_push_notification_task, "retry", retry
        ):
            return retry

    def test_success_returns_true_without_retry(self):
        send = mock.Mock(return_value=True)
        retry = self._run(send)
        with mock.patch(self.SEND, send), mock.patch.object(
            send_push_notification_task, "retry", retry
        ):
            self.assertTrue(send_push_notification_task([TOKEN_A], "t", "b", {"a": 1}))
        send.assert_called_once_with(
            tokens=[TOKEN_A], title="t", body="b", data={"a": 1}
        )
        retry.assert_not_called()

    def test_false_result_schedules_exactly_one_retry(self):
        """Regresión: antes se programaban dos reintentos por cada fallo."""
        send = mock.Mock(return_value=False)
        retry = mock.Mock(side_effect=Retry())
        with mock.patch(self.SEND, send), mock.patch.object(
            send_push_notification_task, "retry", retry
        ):
            with self.assertRaises(Retry):
                send_push_notification_task([TOKEN_A], "t", "b")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(retry.call_count, 1)
        self.assertIsInstance(retry.call_args.kwargs["exc"], PushDeliveryError)
        self.assertEqual(retry.call_args.kwargs["countdown"], 10)

    def test_exception_schedules_exactly_one_retry(self):
        boom = RuntimeError("red caída")
        send = mock.Mock(side_effect=boom)
        retry = mock.Mock(side_effect=Retry())
        with mock.patch(self.SEND, send), mock.patch.object(
            send_push_notification_task, "retry", retry
        ):
            with self.assertRaises(Retry):
                send_push_notification_task([TOKEN_A], "t", "b")
        self.assertEqual(retry.call_count, 1)
        self.assertIs(retry.call_args.kwargs["exc"], boom)

    def test_backoff_is_exponential(self):
        def task(retries):
            return SimpleNamespace(
                default_retry_delay=10, request=SimpleNamespace(retries=retries)
            )

        self.assertEqual(
            [_backoff_seconds(task(n)) for n in range(3)], [10, 20, 40]
        )

    def test_task_config(self):
        self.assertEqual(send_push_notification_task.max_retries, 3)
        self.assertEqual(
            send_push_notification_task.name, "api.tasks.send_push_notification_task"
        )


class PushSignalTests(TestCase):
    DELAY = "api.tasks.send_push_notification_task.delay"

    def setUp(self):
        self.user = make_user("carol")
        self.other = make_user("dave")
        PushToken.objects.create(user=self.user, token=TOKEN_A, is_active=True)

    def _notify(self, recipient=None, **data):
        return Notification.objects.create(
            recipient=recipient or self.user,
            actor=self.other,
            notification_type="task_like",
            target_type="task",
            target_id="7",
            data=data,
        )

    def test_enqueues_once_after_commit_with_payload(self):
        with mock.patch(self.DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                n = self._notify(title="Mi tarea", excerpt="Hola", text="otro")
        delay.assert_called_once_with(
            tokens=[TOKEN_A],
            title="Mi tarea",
            body="Hola",
            data={
                "notification_id": str(n.id),
                "type": "task_like",
                "target_type": "task",
                "target_id": "7",
            },
        )

    def test_defaults_for_title_and_body(self):
        with mock.patch(self.DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._notify(text="Te dieron like")
        kwargs = delay.call_args.kwargs
        self.assertEqual(kwargs["title"], "Sumsal")
        self.assertEqual(kwargs["body"], "Te dieron like")

    def test_nothing_enqueued_before_commit(self):
        with mock.patch(self.DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=False):
                self._notify(text="x")
        delay.assert_not_called()

    def test_no_tokens_no_enqueue(self):
        with mock.patch(self.DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._notify(recipient=self.other, text="x")
        delay.assert_not_called()

    def test_inactive_tokens_ignored(self):
        PushToken.objects.update(is_active=False)
        with mock.patch(self.DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._notify(text="x")
        delay.assert_not_called()

    def test_update_does_not_enqueue(self):
        with mock.patch(self.DELAY):
            with self.captureOnCommitCallbacks(execute=True):
                n = self._notify(text="x")
        with mock.patch(self.DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                n.is_read = True
                n.save()
        delay.assert_not_called()

    def test_broker_failure_does_not_break_notification(self):
        with mock.patch(self.DELAY, side_effect=ConnectionError("redis caído")):
            with self.captureOnCommitCallbacks(execute=True):
                n = self._notify(text="x")
        self.assertTrue(Notification.objects.filter(pk=n.pk).exists())

    def test_signal_does_not_send_synchronously(self):
        """Regresión: el viejo envío síncrono duplicaba cada push."""
        with mock.patch(self.DELAY), mock.patch(
            "api.tasks.send_expo_push"
        ) as send, mock.patch(
            "api.utils.push_notifications.requests.post"
        ) as post:
            with self.captureOnCommitCallbacks(execute=True):
                self._notify(text="x")
        send.assert_not_called()
        post.assert_not_called()


class DeadTokenCleanupTests(TestCase):
    """Fase 29: tokens con DeviceNotRegistered se desactivan automáticamente."""

    POST = "api.utils.push_notifications.requests.post"

    def setUp(self):
        self.user = make_user("erin")
        self.alive = PushToken.objects.create(user=self.user, token=TOKEN_A)
        self.dead = PushToken.objects.create(
            user=self.user, token=TOKEN_B, is_active=True
        )

    def _response(self, body):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = body
        return response

    def test_device_not_registered_deactivates_only_that_token(self):
        body = {
            "data": [
                {"status": "ok", "id": "1"},
                {
                    "status": "error",
                    "message": "not registered",
                    "details": {"error": "DeviceNotRegistered"},
                },
            ]
        }
        with mock.patch(self.POST, return_value=self._response(body)):
            self.assertTrue(send_expo_push([TOKEN_A, TOKEN_B], "t", "b"))
        self.alive.refresh_from_db()
        self.dead.refresh_from_db()
        self.assertTrue(self.alive.is_active)
        self.assertFalse(self.dead.is_active)

    def test_other_errors_keep_token_active(self):
        body = {
            "data": [
                {
                    "status": "error",
                    "details": {"error": "MessageRateExceeded"},
                }
            ]
        }
        with mock.patch(self.POST, return_value=self._response(body)):
            self.assertTrue(send_expo_push([TOKEN_A], "t", "b"))
        self.alive.refresh_from_db()
        self.assertTrue(self.alive.is_active)

    def test_malformed_response_does_not_fail_delivery(self):
        response = self._response(None)
        response.json.side_effect = ValueError("no es JSON")
        with mock.patch(self.POST, return_value=response):
            self.assertTrue(send_expo_push([TOKEN_A], "t", "b"))
        self.alive.refresh_from_db()
        self.assertTrue(self.alive.is_active)
