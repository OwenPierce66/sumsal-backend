from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from . import views as vs

from .throttling import LoginThrottle, RefreshThrottle

urlpatterns = [
    path("auth/register/", vs.RegisterView.as_view(), name="register"),
    path(
        "auth/login/",
        TokenObtainPairView.as_view(throttle_classes=[LoginThrottle]),
        name="login",
    ),
    path(
        "auth/refresh/",
        TokenRefreshView.as_view(throttle_classes=[RefreshThrottle]),
        name="token_refresh",
    ),
    path("users/me/", vs.UserMeView.as_view(), name="user-me"),
]

# v1
