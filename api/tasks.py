"""
api/tasks.py

Tareas asíncronas en segundo plano ejecutadas por Celery.
"""
import logging
from celery import shared_task
from .utils.push_notifications import send_expo_push

logger = logging.getLogger(__name__)


class PushDeliveryError(Exception):
    """Expo no aceptó la entrega (error de red o respuesta HTTP de error)."""


def _backoff_seconds(task):
    """10s, 20s, 40s… según el número de reintentos ya realizados."""
    return task.default_retry_delay * (2 ** task.request.retries)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="api.tasks.send_push_notification_task",
)
def send_push_notification_task(self, tokens, title, body, data=None):
    """
    Envía notificaciones push de Expo en segundo plano.
    Reintenta hasta 3 veces con backoff exponencial si falla la entrega.

    Importante: `self.retry()` lanza `Retry` (subclase de Exception), por eso
    NO debe llamarse dentro de un `try` que capture `Exception`: se reintentaría
    dos veces por fallo y el usuario recibiría notificaciones duplicadas.
    """
    try:
        success = send_expo_push(
            tokens=tokens,
            title=title,
            body=body,
            data=data,
        )
    except Exception as exc:
        logger.error("[Celery Task] Error enviando push: %s", exc)
        raise self.retry(exc=exc, countdown=_backoff_seconds(self))

    if not success:
        logger.warning("[Celery Task] send_expo_push retornó False, reintentando...")
        raise self.retry(
            exc=PushDeliveryError("Fallo en entrega Expo push"),
            countdown=_backoff_seconds(self),
        )
    return True