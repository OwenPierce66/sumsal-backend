"""
api/utils/push_notifications.py

Cliente liviano para Expo Push Notifications API.
Envía notificaciones a iOS/Android vía Expo sin necesitar APNs/FCM directamente.
Documentación: https://docs.expo.dev/push-notifications/sending-notifications/
"""
import logging

import requests

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/push/send"
_TIMEOUT = 5  # segundos — no bloquear request del usuario más de esto


def send_expo_push(tokens, title, body, data=None, badge=1):
    """
    Envía una notificación push a uno o más ExponentPushTokens.

    Args:
        tokens (list[str]): Lista de ExponentPushToken[xxxxx].
        title (str): Título visible de la notificación.
        body (str): Cuerpo / descripción de la notificación.
        data (dict): Payload extra — llega al cliente como
                     notification.request.content.data.
        badge (int): Número en el icono de la app (solo iOS).

    Returns:
        bool: True si la petición HTTP fue exitosa, False si hubo error de red.
    """
    # Expo solo acepta sus propios tokens — ignorar tokens FCM/APNs crudos
    valid = [t for t in (tokens or []) if t and t.startswith("ExponentPushToken")]
    if not valid:
        return True  # no hay tokens válidos, nada que enviar

    messages = [
        {
            "to": token,
            "title": title,
            "body": body,
            "data": data or {},
            "sound": "default",
            "badge": badge,
        }
        for token in valid
    ]

    try:
        resp = requests.post(
            EXPO_PUSH_URL,
            json=messages,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("[push] Error enviando notificación push: %s", exc)
        return False

    logger.debug("[push] Enviado a %d tokens: %s", len(valid), title)
    # La entrega ya fue aceptada: limpiar tokens muertos nunca debe provocar
    # un reintento (duplicaría pushes), por eso va fuera del try anterior.
    try:
        _deactivate_dead_tokens(valid, resp)
    except Exception:
        logger.exception("[push] No se pudieron procesar los tickets de Expo")
    return True


def _dead_tokens_from_tickets(tokens, tickets):
    """Devuelve los tokens cuyo ticket indica DeviceNotRegistered.

    Expo responde un ticket por mensaje, en el mismo orden que se envió.
    """
    if not isinstance(tickets, list):
        return []
    dead = []
    for token, ticket in zip(tokens, tickets):
        if not isinstance(ticket, dict) or ticket.get("status") != "error":
            continue
        details = ticket.get("details")
        if isinstance(details, dict) and details.get("error") == "DeviceNotRegistered":
            dead.append(token)
    return dead


def _deactivate_dead_tokens(tokens, resp):
    payload = resp.json()
    tickets = payload.get("data") if isinstance(payload, dict) else None
    dead = _dead_tokens_from_tickets(tokens, tickets)
    if not dead:
        return
    from api.models import PushToken  # import tardío: evita ciclos al cargar apps

    updated = PushToken.objects.filter(token__in=dead, is_active=True).update(
        is_active=False
    )
    logger.info("[push] %d token(s) desactivados (DeviceNotRegistered)", updated)