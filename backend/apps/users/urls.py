from django.urls import path

from .account_views import ApprovalResubmitView, NotificationListView, NotificationReadView
from .admin_views import (
    AdminUserDetailView,
    AdminUserFreezeView,
    AdminUserHistoryView,
    AdminUserListView,
    AdminUserReviewView,
    AdminUserUnfreezeView,
)
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
    path(
        "me/approval/resubmit",
        ApprovalResubmitView.as_view(),
        name="approval-resubmit",
    ),
    path("notifications", NotificationListView.as_view(), name="notification-list"),
    path(
        "notifications/<uuid:notification_id>/read",
        NotificationReadView.as_view(),
        name="notification-read",
    ),
    path("admin/users", AdminUserListView.as_view(), name="admin-user-list"),
    path("admin/users/<uuid:user_id>", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path(
        "admin/users/<uuid:user_id>/history",
        AdminUserHistoryView.as_view(),
        name="admin-user-history",
    ),
    path(
        "admin/users/<uuid:user_id>/review",
        AdminUserReviewView.as_view(),
        name="admin-user-review",
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
]
