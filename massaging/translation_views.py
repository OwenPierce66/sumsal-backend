"""Vistas del traductor de mensajes (directos y de grupo)."""
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from api.models import Profile

from .models import GroupMembership, GroupMessage, Message, MessageTranslation
from .translation import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    TranslationError,
    TranslationNotConfigured,
    get_provider,
    normalize_language,
    translate_text,
)


class TranslateThrottle(UserRateThrottle):
    """Tope diario por usuario (`translate` en DEFAULT_THROTTLE_RATES)."""
    scope = "translate"


def _user_language(user):
    profile = Profile.objects.filter(user=user).only("language").first()
    return normalize_language(getattr(profile, "language", None))


def _translation_payload(translation, cached):
    return {
        "id": translation.id,
        "text": translation.text,
        "source_lang": translation.source_lang,
        "target_lang": translation.target_lang,
        # Si el mensaje ya estaba en tu idioma, el texto es el original.
        "same_language": bool(translation.source_lang) and translation.source_lang == translation.target_lang,
        "cached": cached,
    }


SHARED_PREFIXES = ("↪ Respuesta a tu historia:", "↪ Publicación compartida:")


def _message_body(content):
    """Quita la primera línea automática de contenido compartido (historia/publicación)."""
    text = (content or "").strip()
    if text.startswith(SHARED_PREFIXES):
        _, _, rest = text.partition("\n")
        return rest.strip()
    return text


def _translate(request, original_text, lookup, create_kwargs):
    """Traduce `original_text` al idioma de quien consulta y guarda el resultado."""
    text = _message_body(original_text)
    if not text:
        return Response(
            {"detail": "Este mensaje no tiene texto para traducir."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(text) > settings.TRANSLATION_MAX_CHARS:
        return Response(
            {"detail": "El mensaje es demasiado largo para traducirlo."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    requested = request.data.get("target") if hasattr(request.data, "get") else None
    target = normalize_language(requested, default=_user_language(request.user))

    cached = MessageTranslation.objects.filter(**lookup, target_lang=target).first()
    if cached:
        return Response(_translation_payload(cached, cached=True))

    try:
        translated, detected, provider = translate_text(text, target)
    except TranslationNotConfigured:
        return Response(
            {"detail": "El traductor todavía no está configurado."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except TranslationError:
        return Response(
            {"detail": "No se pudo traducir en este momento. Inténtalo de nuevo."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    translation, created = MessageTranslation.objects.get_or_create(
        **lookup,
        target_lang=target,
        defaults={
            **create_kwargs,
            "source_lang": detected or "",
            "text": translated,
            "provider": provider,
        },
    )
    return Response(_translation_payload(translation, cached=not created))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([TranslateThrottle])
def translate_message(request, message_id):
    """Traduce un mensaje directo al idioma de quien lo pide (o a `target`)."""
    message = get_object_or_404(Message, id=message_id)
    if request.user.id not in (message.sender_id, message.receiver_id):
        # No revelar que el mensaje existe.
        return Response(status=status.HTTP_404_NOT_FOUND)
    return _translate(
        request, message.content, {"message": message}, {"message": message}
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([TranslateThrottle])
def translate_group_message(request, message_id):
    """Traduce un mensaje de grupo; solo miembros del grupo."""
    message = get_object_or_404(GroupMessage, id=message_id)
    if not GroupMembership.objects.filter(group_id=message.group_id, user=request.user).exists():
        return Response(status=status.HTTP_404_NOT_FOUND)
    return _translate(
        request, message.content, {"group_message": message}, {"group_message": message}
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def translation_language(request):
    """GET: mi idioma y los disponibles. PATCH {language}: cambia mi idioma."""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == "PATCH":
        raw = str(request.data.get("language") or "").strip().lower()
        if raw not in SUPPORTED_LANGUAGES:
            return Response(
                {"detail": "Idioma no disponible."}, status=status.HTTP_400_BAD_REQUEST
            )
        profile.language = raw
        profile.save(update_fields=["language", "updated_at"])

    try:
        get_provider()
        configured = True
    except TranslationNotConfigured:
        configured = False
    return Response({
        "language": normalize_language(profile.language, default=DEFAULT_LANGUAGE),
        "supported": [{"code": code, "name": name} for code, name in SUPPORTED_LANGUAGES.items()],
        "configured": configured,
    })
