from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PushToken

# Máximo de dispositivos (tokens activos) por usuario.
MAX_ACTIVE_TOKENS_PER_USER = 5


class PushTokenView(APIView):
    """
    POST /api/push-tokens/

    Registra o actualiza el ExponentPushToken del dispositivo actual.
    - Un usuario puede tener varios dispositivos activos (hasta
      MAX_ACTIVE_TOKENS_PER_USER); al superar el límite se desactivan los
      menos recientes.
    - Si el token pertenecía a otro usuario (re-login), lo reasigna.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = (request.data.get("token") or "").strip()
        platform = request.data.get("platform", "ios")

        if not token:
            return Response(
                {"error": "token es requerido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_length = PushToken._meta.get_field("token").max_length
        if len(token) > max_length:
            return Response(
                {"error": f"token excede los {max_length} caracteres permitidos."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if platform not in {"ios", "android", "web"}:
            platform = "ios"

        # Crear o reasignar el token (manejo de cambios de cuenta)
        obj, created = PushToken.objects.update_or_create(
            token=token,
            defaults={
                "user": request.user,
                "platform": platform,
                "is_active": True,
            },
        )

        # Multi-dispositivo: se conservan activos los más recientes y se
        # desactivan los sobrantes (tokens de dispositivos que ya no se usan).
        stale_ids = list(
            PushToken.objects.filter(user=request.user, is_active=True)
            .order_by("-updated_at", "-id")
            .values_list("id", flat=True)[MAX_ACTIVE_TOKENS_PER_USER:]
        )
        if stale_ids:
            PushToken.objects.filter(id__in=stale_ids).update(is_active=False)

        return Response(
            {"registered": True},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request):
        """
        DELETE /api/push-tokens/  body: {"token": "..."}

        Da de baja el token de ESTE dispositivo (logout) para que deje de
        recibir pushes del usuario. Es idempotente y solo afecta tokens del
        propio usuario: un token desconocido o ajeno responde 204 igualmente
        (no revela si el token existe).
        """
        token = (request.data.get("token") or "").strip()
        if not token:
            return Response(
                {"error": "token es requerido."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        PushToken.objects.filter(user=request.user, token=token).update(
            is_active=False
        )
        return Response(status=status.HTTP_204_NO_CONTENT)