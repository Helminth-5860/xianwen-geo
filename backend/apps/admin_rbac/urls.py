from django.urls import path

from .risk_views import (
    ApprovalApproveView,
    ApprovalCancelView,
    ApprovalDetailView,
    ApprovalListView,
    ApprovalRejectView,
    AuditEventDetailView,
    AuditEventListView,
    RiskActionListView,
    RiskPolicyDetailView,
    RiskPolicyListView,
)
from .security_views import (
    AdminForceLogoutView,
    AdminLogoutView,
    AdminPasswordLoginView,
    AdminStepUpChallengeView,
    AdminStepUpVerifyView,
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
    AdminRegistrationLinkView,
    AdminRoleChangeView,
    CustomerAssignmentView,
    PermissionListView,
    RoleDetailView,
    RoleDisableView,
    RoleListCreateView,
    RolePermissionsView,
    TenantDetailView,
    TenantListCreateView,
    status_view,
)

urlpatterns = [
    path(
        "admin/auth/login/password", AdminPasswordLoginView.as_view(), name="admin-password-login"
    ),
    path(
        "admin/auth/step-up/challenge",
        AdminStepUpChallengeView.as_view(),
        name="admin-step-up-challenge",
    ),
    path(
        "admin/auth/step-up/verify",
        AdminStepUpVerifyView.as_view(),
        name="admin-step-up-verify",
    ),
    path("admin/auth/logout", AdminLogoutView.as_view(), name="admin-logout"),
    path("admin/me", AdminMeView.as_view(), name="admin-me"),
    path("admin/tenants", TenantListCreateView.as_view(), name="tenant-list"),
    path("admin/tenants/<uuid:tenant_id>", TenantDetailView.as_view(), name="tenant-detail"),
    path("admin/admins", AdminListCreateView.as_view(), name="admin-list"),
    path("admin/admins/<uuid:profile_id>", AdminDetailView.as_view(), name="admin-detail"),
    path(
        "admin/admins/<uuid:profile_id>/registration-link",
        AdminRegistrationLinkView.as_view(),
        name="admin-registration-link",
    ),
    path(
        "admin/admins/<uuid:profile_id>/role",
        AdminRoleChangeView.as_view(),
        name="admin-role-change",
    ),
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
    path(
        "admin/roles/<uuid:role_id>/permissions",
        RolePermissionsView.as_view(),
        name="role-permissions",
    ),
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
    path("admin/risk-actions", RiskActionListView.as_view(), name="risk-action-list"),
    path("admin/risk-policies", RiskPolicyListView.as_view(), name="risk-policy-list"),
    path(
        "admin/risk-policies/<str:action_key>",
        RiskPolicyDetailView.as_view(),
        name="risk-policy-detail",
    ),
    path("admin/approvals", ApprovalListView.as_view(), name="approval-list"),
    path(
        "admin/approvals/<uuid:approval_id>", ApprovalDetailView.as_view(), name="approval-detail"
    ),
    path(
        "admin/approvals/<uuid:approval_id>/approve",
        ApprovalApproveView.as_view(),
        name="approval-approve",
    ),
    path(
        "admin/approvals/<uuid:approval_id>/reject",
        ApprovalRejectView.as_view(),
        name="approval-reject",
    ),
    path(
        "admin/approvals/<uuid:approval_id>/cancel",
        ApprovalCancelView.as_view(),
        name="approval-cancel",
    ),
    path("admin/audit-events", AuditEventListView.as_view(), name="audit-event-list"),
    path(
        "admin/audit-events/<uuid:event_id>",
        AuditEventDetailView.as_view(),
        name="audit-event-detail",
    ),
]
