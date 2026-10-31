from rest_framework.throttling import UserRateThrottle, AnonRateThrottle


# ─── Autenticación ────────────────────────────────────────────────────────────

class LoginThrottle(AnonRateThrottle):
    """
    Protección contra fuerza bruta en el endpoint de login.
    Usa AnonRateThrottle (por IP) porque el atacante no tiene usuario todavía.
    Límite estricto: 10 intentos/hora, 20/día.
    """
    scope = "login"


class RegisterThrottle(AnonRateThrottle):
    """
    Limita la creación masiva de cuentas falsas.
    Usa AnonRateThrottle (por IP) porque el usuario aún no existe.
    """
    scope = "register"


class RefreshThrottle(AnonRateThrottle):
    """
    Limita el uso del endpoint de refresh de tokens.
    Un silent-refresh legítimo no debería ocurrir más de una vez por minuto.
    """
    scope = "refresh"


class LogoutThrottle(UserRateThrottle):
    """
    Limita llamadas al endpoint de logout (usuario autenticado).
    """
    scope = "logout"


class PasswordResetThrottle(AnonRateThrottle):
    """Limita cuántos códigos para recuperar la contraseña se piden desde una IP."""
    scope = "password_reset"


class PasswordResetConfirmThrottle(AnonRateThrottle):
    """Limita los intentos de adivinar un código desde una IP."""
    scope = "password_reset_confirm"


# ─── Usuario autenticado ──────────────────────────────────────────────────────

class DeleteAccountThrottle(UserRateThrottle):
    scope = "delete_account"


class UserMeThrottle(UserRateThrottle):
    scope = "user_me"


class BurstThrottle(UserRateThrottle):
    """Límite de ráfaga: muchas peticiones en poco tiempo."""
    scope = "burst"


class SustainedThrottle(UserRateThrottle):
    """Límite sostenido: cuota diaria total."""
    scope = "sustained"


class VaultThrottle(UserRateThrottle):
    scope = "vault"


class UploadThrottle(UserRateThrottle):
    scope = "uploads"


# ─── Acceso público (sin autenticación) ──────────────────────────────────────

class PublicApiThrottle(AnonRateThrottle):
    """Para endpoints de lectura pública (tareas, perfiles, etc.)."""
    scope = "public"
