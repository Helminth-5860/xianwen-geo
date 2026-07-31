from django.urls import path

from .views import (
    CsrfTokenView,
    LogoutView,
    MeView,
    PasswordLoginView,
    PasswordResetView,
    RegistrationView,
    SmsLoginView,
    SmsSendView,
)

app_name = "users"

urlpatterns = [
    path("auth/csrf", CsrfTokenView.as_view(), name="csrf"),
    path("auth/sms/send", SmsSendView.as_view(), name="sms-send"),
    path("auth/register", RegistrationView.as_view(), name="register"),
    path("auth/login/password", PasswordLoginView.as_view(), name="password-login"),
    path("auth/login/sms", SmsLoginView.as_view(), name="sms-login"),
    path("auth/password/reset", PasswordResetView.as_view(), name="password-reset"),
    path("auth/logout", LogoutView.as_view(), name="logout"),
    path("me", MeView.as_view(), name="me"),
]
