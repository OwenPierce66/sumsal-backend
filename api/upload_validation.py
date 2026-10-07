"""
Validacion de archivos subidos (Fase 36).

Los archivos se sirven desde /media/, asi que un adjunto .html/.svg/.js seria XSS
almacenado en el dominio de la API. Ademas se limita el tamano para que un
cliente no pueda llenar el disco / saturar el servidor.

Limites configurables en settings (UPLOAD_MAX_*_BYTES).
"""
import os

from django.conf import settings
from rest_framework.exceptions import ValidationError

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".3gp", ".mkv", ".avi"}

# Contenido activo o ejecutable: nunca se acepta como adjunto.
BLOCKED_EXTENSIONS = {
    ".html", ".htm", ".xhtml", ".svg", ".js", ".mjs", ".php", ".phtml", ".py",
    ".exe", ".dll", ".bat", ".cmd", ".com", ".msi", ".scr", ".sh", ".jar",
    ".apk", ".vbs", ".ps1", ".xml", ".swf",
}

DEFAULT_MAX_VIDEO = 100 * 1024 * 1024
DEFAULT_MAX_IMAGE = 20 * 1024 * 1024
DEFAULT_MAX_ATTACHMENT = 50 * 1024 * 1024


def _limit(name, default):
    return getattr(settings, name, default)


def _ext(f):
    return os.path.splitext(getattr(f, "name", "") or "")[1].lower()


def _check_size(f, limit, label):
    if f.size > limit:
        raise ValidationError(
            f"{label} demasiado grande (máximo {limit // (1024 * 1024) or 1} MB)."
            if limit >= 1024 * 1024
            else f"{label} demasiado grande."
        )


def validate_video_upload(f):
    """Un campo `video` debe ser realmente un video (extension) y no pasar el limite."""
    if not f:
        return f
    if _ext(f) not in VIDEO_EXTENSIONS:
        raise ValidationError("El archivo de video no tiene un formato permitido.")
    _check_size(f, _limit("UPLOAD_MAX_VIDEO_BYTES", DEFAULT_MAX_VIDEO), "El video")
    return f


def validate_image_upload(f):
    """Las imagenes ya se verifican con Pillow (ImageField); aqui solo el tamano."""
    if not f:
        return f
    if _ext(f) in BLOCKED_EXTENSIONS:
        raise ValidationError("La imagen no tiene un formato permitido.")
    _check_size(f, _limit("UPLOAD_MAX_IMAGE_BYTES", DEFAULT_MAX_IMAGE), "La imagen")
    return f


def validate_attachment_upload(f):
    """Adjuntos genericos: se bloquea contenido activo/ejecutable y se limita el tamano."""
    if not f:
        return f
    if _ext(f) in BLOCKED_EXTENSIONS:
        raise ValidationError("Este tipo de archivo no está permitido.")
    _check_size(f, _limit("UPLOAD_MAX_ATTACHMENT_BYTES", DEFAULT_MAX_ATTACHMENT), "El archivo")
    return f


def validate_chat_uploads(request):
    """
    Valida image/video/attachments de un mensaje de chat.
    Devuelve el texto del error (str) o None si todo es valido.
    """
    try:
        validate_image_upload(request.FILES.get("image"))
        validate_video_upload(request.FILES.get("video"))
        for f in request.FILES.getlist("attachments"):
            validate_attachment_upload(f)
    except ValidationError as exc:
        detail = exc.detail
        return str(detail[0] if isinstance(detail, list) else detail)
    return None
