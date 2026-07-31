from django.urls import path

from .security_views import (
    AdminForceLogoutView,
    AdminLogoutView,
    AdminPasswordLoginView,
    AdminSmsSendView,
    AdminSmsVerifyView,
    RoleIpAllowlistDetailView,
    RoleIpAllowlistView,
    RoleSecurityView,
    SuperuserIpAllowlistDetailView,
    SuperuserIpAllowlistView,
    SuperuserSecurityView,
)
from .views import (
    AdminDetailView,
    AdminListCreateView,
    AdminMeView,
    CustomerAssignmentView,
    PermissionListView,
    RoleDetailView,
    RoleDisableView,
    RoleListCreateView,
    status_view,
)

urlpatterns = [
    path(
        "admin/auth/login/password", AdminPasswordLoginView.as_view(), name="admin-password-login"
    ),
    path("admin/auth/login/sms/send", AdminSmsSendView.as_view(), name="admin-sms-send"),
    path("admin/auth/login/sms/verify", AdminSmsVerifyView.as_view(), name="admin-sms-verify"),
    path("admin/auth/logout", AdminLogoutView.as_view(), name="admin-logout"),
    path("admin/me", AdminMeView.as_view(), name="admin-me"),
    path("admin/admins", AdminListCreateView.as_view(), name="admin-list"),
    path("admin/admins/<uuid:profile_id>", AdminDetailView.as_view(), name="admin-detail"),
    path(
        "admin/admins/<uuid:profile_id>/disable",
        status_view("disable").as_view(),
        name="admin-disable",
    ),
    path(
        "admin/admins/<uuid:profile_id>/enable",
        status_view("enable").as_view(),
        name="admin-enable",
    ),
    path("admin/admins/<uuid:profile_id>/lock", status_view("lock").as_view(), name="admin-lock"),
    path(
        "admin/admins/<uuid:profile_id>/unlock",
        status_view("unlock").as_view(),
        name="admin-unlock",
    ),
    path(
        "admin/admins/<uuid:profile_id>/force-logout",
        AdminForceLogoutView.as_view(),
        name="admin-force-logout",
    ),
    path("admin/roles", RoleListCreateView.as_view(), name="role-list"),
    path("admin/roles/<uuid:role_id>", RoleDetailView.as_view(), name="role-detail"),
    path("admin/roles/<uuid:role_id>/disable", RoleDisableView.as_view(), name="role-disable"),
    path("admin/roles/<uuid:role_id>/security", RoleSecurityView.as_view(), name="role-security"),
    path(
        "admin/roles/<uuid:role_id>/ip-allowlist",
        RoleIpAllowlistView.as_view(),
        name="role-ip-allowlist",
    ),
    path(
        "admin/roles/<uuid:role_id>/ip-allowlist/<uuid:entry_id>",
        RoleIpAllowlistDetailView.as_view(),
        name="role-ip-allowlist-detail",
    ),
    path("admin/security/superuser", SuperuserSecurityView.as_view(), name="superuser-security"),
    path(
        "admin/security/superuser/ip-allowlist",
        SuperuserIpAllowlistView.as_view(),
        name="superuser-ip-allowlist",
    ),
    path(
        "admin/security/superuser/ip-allowlist/<uuid:entry_id>",
        SuperuserIpAllowlistDetailView.as_view(),
        name="superuser-ip-allowlist-detail",
    ),
    path("admin/permissions", PermissionListView.as_view(), name="permission-list"),
    path(
        "admin/users/<uuid:customer_id>/assignment",
        CustomerAssignmentView.as_view(),
        name="customer-assignment",
    ),
]
