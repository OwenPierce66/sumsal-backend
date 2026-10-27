"""Cuenta que representa a la App (settings.APP_ACCOUNT_EMAIL, por defecto owen@gmail.com).

Un superadmin puede dar o quitar el "like de la App" a una tarea o a un perfil;
ese like queda a nombre de esta cuenta, como en la web antigua.
"""
from django.conf import settings
from django.contrib.auth import get_user_model


def app_account_email():
    return (getattr(settings, "APP_ACCOUNT_EMAIL", "") or "").strip()


def get_app_account():
    """La cuenta de la App, o None si no existe."""
    email = app_account_email()
    if not email:
        return None
    return get_user_model().objects.filter(email__iexact=email).first()


def app_account_id_for(request):
    """Id de la cuenta de la App, consultado una sola vez por petición (listas)."""
    if not hasattr(request, "_app_account_id"):
        email = app_account_email()
        request._app_account_id = (
            get_user_model().objects.filter(email__iexact=email).values_list("id", flat=True).first()
            if email else None
        )
    return request._app_account_id
