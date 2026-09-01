from django.urls import path

from .account_views import (
    AppearanceUpdateView,
    NotificationListView,
    NotificationReadView,
    PasswordChangeView,
    PhoneChangeView,
    PhoneCodeSendView,
    ProfileUpdateView,
    SessionRevokeView,
)
from .admin_views import (
    AdminUserDetailView,
    AdminUserFreezeView,
    AdminUserHistoryView,
    AdminUserListView,
    AdminUserTestAccountView,
    AdminUserUnfreezeView,
)
from .control_center_views import AdminUserControlCenterView
from .views import (
    CsrfTokenView,
    LogoutView,
    MeView,
    PasswordLoginView,
    PasswordResetView,
    RegistrationReferenceView,
    RegistrationView,
    SmsLoginView,
    SmsSendView,
)

app_name = "users"

urlpatterns = [
    path("auth/csrf", CsrfTokenView.as_view(), name="csrf"),
    path("auth/sms/send", SmsSendView.as_view(), name="sms-send"),
    path("auth/register", RegistrationView.as_view(), name="register"),
    path(
        "auth/registration-ref",
        RegistrationReferenceView.as_view(),
        name="registration-reference",
    ),
    path("auth/login/password", PasswordLoginView.as_view(), name="password-login"),
    path("auth/login/sms", SmsLoginView.as_view(), name="sms-login"),
    path("auth/password/reset", PasswordResetView.as_view(), name="password-reset"),
    path("auth/logout", LogoutView.as_view(), name="logout"),
    path("me", MeView.as_view(), name="me"),
    path("me/profile", ProfileUpdateView.as_view(), name="me-profile"),
    path("me/phone/code", PhoneCodeSendView.as_view(), name="me-phone-code"),
    path("me/phone", PhoneChangeView.as_view(), name="me-phone"),
    path("me/password", PasswordChangeView.as_view(), name="me-password"),
    path("me/appearance", AppearanceUpdateView.as_view(), name="me-appearance"),
    path("me/sessions/revoke", SessionRevokeView.as_view(), name="me-sessions-revoke"),
    path("notifications", NotificationListView.as_view(), name="notification-list"),
    path(
        "notifications/<uuid:notification_id>/read",
        NotificationReadView.as_view(),
        name="notification-read",
    ),
    path("admin/users", AdminUserListView.as_view(), name="admin-user-list"),
    path("admin/users/<uuid:user_id>", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path(
        "admin/users/<uuid:user_id>/control-center",
        AdminUserControlCenterView.as_view(),
        name="admin-user-control-center",
    ),
    path(
        "admin/users/<uuid:user_id>/history",
        AdminUserHistoryView.as_view(),
        name="admin-user-history",
    ),
    path(
        "admin/users/<uuid:user_id>/freeze",
        AdminUserFreezeView.as_view(),
        name="admin-user-freeze",
    ),
    path(
        "admin/users/<uuid:user_id>/unfreeze",
        AdminUserUnfreezeView.as_view(),
        name="admin-user-unfreeze",
    ),
    path(
        "admin/users/<uuid:user_id>/test-account",
        AdminUserTestAccountView.as_view(),
        name="admin-user-test-account",
    ),
]
