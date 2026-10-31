"""Envío de correos por la API HTTP de Brevo.

El plan gratis de Render bloquea los puertos SMTP, así que el backend de correo
normal de Django no llega a salir: por HTTPS sí.
"""
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
TIMEOUT_SECONDS = 15


class BrevoEmailBackend(BaseEmailBackend):
    def _send(self, message):
        name, address = parseaddr(message.from_email)
        response = requests.post(
            BREVO_URL,
            headers={"api-key": settings.BREVO_API_KEY, "accept": "application/json"},
            json={
                "sender": {"name": name or "Aportaciones", "email": address},
                "to": [{"email": recipient} for recipient in message.to],
                "subject": message.subject,
                "textContent": message.body,
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            try:
                self._send(message)
            except requests.RequestException:
                if not self.fail_silently:
                    raise
            else:
                sent += 1
        return sent
