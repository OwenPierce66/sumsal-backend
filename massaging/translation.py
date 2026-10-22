"""Traductor de mensajes (directos y de grupo).

Los proveedores se eligen por configuración (`TRANSLATION_PROVIDER`), así que
cambiar de DeepL a Google no toca ni la app ni las vistas. Las claves viven solo
en el backend (variables de entorno), nunca en el cliente.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Idiomas que la app ofrece como "Mi idioma". Código -> nombre en su propio idioma.
SUPPORTED_LANGUAGES = {
    "es": "Español",
    "en": "English",
    "pt": "Português",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "ja": "日本語",
    "ko": "한국어",
    "zh": "中文",
    "ru": "Русский",
}
DEFAULT_LANGUAGE = "es"
REQUEST_TIMEOUT = 10


class TranslationError(Exception):
    """El proveedor falló o respondió algo inesperado."""


class TranslationNotConfigured(TranslationError):
    """Falta la clave o el proveedor no existe."""


def normalize_language(code, default=DEFAULT_LANGUAGE):
    """Devuelve un código de `SUPPORTED_LANGUAGES` ('en-US' -> 'en') o `default`."""
    base = str(code or "").strip().lower().replace("_", "-").split("-")[0]
    return base if base in SUPPORTED_LANGUAGES else default


class DeepLProvider:
    name = "deepl"
    # DeepL exige variante regional para estos destinos.
    _TARGETS = {"en": "EN-US", "pt": "PT-BR", "zh": "ZH-HANS"}

    def __init__(self, api_key):
        if not api_key:
            raise TranslationNotConfigured("Falta DEEPL_API_KEY.")
        self.api_key = api_key
        # Las claves gratuitas terminan en ':fx' y usan otro dominio.
        host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
        self.url = f"https://{host}/v2/translate"

    def translate(self, text, target, source=None):
        payload = {
            "text": [text],
            "target_lang": self._TARGETS.get(target, target.upper()),
        }
        if source:
            payload["source_lang"] = source.upper()
        response = requests.post(
            self.url,
            json=payload,
            headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 456:
            raise TranslationError("Se agotó la cuota mensual del traductor.")
        if response.status_code != 200:
            raise TranslationError(f"DeepL respondió {response.status_code}.")
        try:
            item = response.json()["translations"][0]
            return item["text"], normalize_language(item.get("detected_source_language"), default="")
        except (KeyError, IndexError, ValueError) as exc:
            raise TranslationError("Respuesta inesperada de DeepL.") from exc


class GoogleProvider:
    name = "google"

    def __init__(self, api_key):
        if not api_key:
            raise TranslationNotConfigured("Falta GOOGLE_TRANSLATE_API_KEY.")
        self.api_key = api_key

    def translate(self, text, target, source=None):
        payload = {"q": text, "target": target, "format": "text"}
        if source:
            payload["source"] = source
        response = requests.post(
            "https://translation.googleapis.com/language/translate/v2",
            params={"key": self.api_key},
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise TranslationError(f"Google respondió {response.status_code}.")
        try:
            item = response.json()["data"]["translations"][0]
            return item["translatedText"], normalize_language(item.get("detectedSourceLanguage"), default="")
        except (KeyError, IndexError, ValueError) as exc:
            raise TranslationError("Respuesta inesperada de Google.") from exc


def get_provider():
    name = str(getattr(settings, "TRANSLATION_PROVIDER", "deepl") or "deepl").lower()
    if name == "deepl":
        return DeepLProvider(getattr(settings, "DEEPL_API_KEY", ""))
    if name == "google":
        return GoogleProvider(getattr(settings, "GOOGLE_TRANSLATE_API_KEY", ""))
    raise TranslationNotConfigured(f"Proveedor de traducción desconocido: {name}.")


def translate_text(text, target, source=None):
    """Traduce `text` a `target`. Devuelve (texto_traducido, idioma_origen, proveedor)."""
    provider = get_provider()
    translated, detected = provider.translate(text, target, source)
    return translated, detected, provider.name
