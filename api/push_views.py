from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PushToken


class PushTokenView(APIView):
    """
    POST /api/push-tokens/

    Registra o actualiza el ExponentPushToken del dispositivo actual.
    - Desactiva tokens anteriores del usuario (un token activo por dispositivo).
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

        if platform not in {"ios", "android", "web"}:
            platform = "ios"

        # Desactivar tokens anteriores del usuario en otros dispositivos
        PushToken.objects.filter(user=request.user, is_active=True).exclude(
            token=token
        ).update(is_active=False)

        # Crear o reasignar el token (manejo de cambios de cuenta)
        obj, created = PushToken.objects.update_or_create(
            token=token,
            defaults={
                "user": request.user,
                "platform": platform,
                "is_active": True,
            },
        )

        return Response(
            {"registered": True},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )