from django.urls import path

from .views import CsrfTokenView, LogoutView, MeView, PasswordLoginView, SmsSendView

app_name = "users"

urlpatterns = [
    path("auth/csrf", CsrfTokenView.as_view(), name="csrf"),
    path("auth/sms/send", SmsSendView.as_view(), name="sms-send"),
    path("auth/login/password", PasswordLoginView.as_view(), name="password-login"),
    path("auth/logout", LogoutView.as_view(), name="logout"),
    path("me", MeView.as_view(), name="me"),
]
