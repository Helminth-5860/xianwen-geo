import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminPermission,
    AdminProfile,
    AdminRole,
    ApprovalRequest,
    CustomerAssignment,
    RiskPolicy,
)
from apps.admin_rbac.risk_catalog import RISK_ACTION_BY_KEY
from apps.admin_rbac.services import create_admin
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"
MODES = ("confirm", "password", "two_person")


@dataclass
class EndpointCase:
    path: str
    method: str
    body: dict
    snapshot: Callable[[], object]


def superuser(phone):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def admin_client(user):
    return authenticate_admin_client(APIClient(), user)


def send(client, case, body):
    return getattr(client, case.method)(case.path, body, format="json")


def build_case(action_key, actor):
    target_role = AdminRole.objects.create(
        name=f"目标角色-{action_key}", data_scope=AdminRole.DataScope.ALL
    )
    replacement_role = AdminRole.objects.create(
        name=f"替换角色-{action_key}", data_scope=AdminRole.DataScope.ALL
    )
    target_admin = create_admin(
        actor_id=actor.pk,
        phone="13600136000",
        nickname="目标管理员",
        password=PASSWORD,
        role_id=target_role.pk,
        request_id=uuid.uuid4(),
    )
    customer = User.objects.create_user(phone="13800138000", nickname="目标客户", password=PASSWORD)

    if action_key == "admin.disable":
        return EndpointCase(
            f"/api/v1/admin/admins/{target_admin.id}/disable",
            "post",
            {"expected_version": target_admin.version},
            lambda: (
                AdminProfile.objects.get(pk=target_admin.pk).admin_status,
                User.objects.get(pk=target_admin.user_id).is_staff,
            ),
        )
    if action_key == "admin.lock":
        return EndpointCase(
            f"/api/v1/admin/admins/{target_admin.id}/lock",
            "post",
            {"expected_version": target_admin.version},
            lambda: AdminProfile.objects.get(pk=target_admin.pk).admin_status,
        )
    if action_key == "admin.role.change":
        return EndpointCase(
            f"/api/v1/admin/admins/{target_admin.id}/role",
            "post",
            {
                "expected_version": target_admin.version,
                "role_id": str(replacement_role.pk),
            },
            lambda: AdminProfile.objects.get(pk=target_admin.pk).role_id,
        )
    if action_key == "admin.force_logout":
        return EndpointCase(
            f"/api/v1/admin/admins/{target_admin.id}/force-logout",
            "post",
            {"expected_version": target_admin.version},
            lambda: User.objects.get(pk=target_admin.user_id).session_version,
        )
    if action_key == "role.permissions.replace":
        permission = AdminPermission.objects.get(key="users.list")
        return EndpointCase(
            f"/api/v1/admin/roles/{replacement_role.id}/permissions",
            "put",
            {
                "expected_version": replacement_role.version,
                "permission_keys": [permission.key],
            },
            lambda: (
                AdminRole.objects.get(pk=replacement_role.pk).version,
                tuple(
                    replacement_role.permission_links.order_by("permission__key").values_list(
                        "permission__key", flat=True
                    )
                ),
            ),
        )
    if action_key == "role.disable":
        return EndpointCase(
            f"/api/v1/admin/roles/{replacement_role.id}/disable",
            "post",
            {"expected_version": replacement_role.version},
            lambda: AdminRole.objects.get(pk=replacement_role.pk).status,
        )
    if action_key == "role.security.update":
        return EndpointCase(
            f"/api/v1/admin/roles/{replacement_role.id}/security",
            "patch",
            {
                "expected_security_version": replacement_role.security_version,
                "require_sms_2fa": True,
                "confirm_lockout": False,
            },
            lambda: (
                AdminRole.objects.get(pk=replacement_role.pk).security_version,
                AdminRole.objects.get(pk=replacement_role.pk).require_sms_2fa,
            ),
        )
    if action_key == "role.ip_allowlist.update":
        return EndpointCase(
            f"/api/v1/admin/roles/{replacement_role.id}/ip-allowlist",
            "post",
            {
                "expected_security_version": replacement_role.security_version,
                "network_cidr": "203.0.113.44/32",
                "label": "运维出口",
                "confirm_lockout": False,
            },
            lambda: (
                AdminRole.objects.get(pk=replacement_role.pk).security_version,
                tuple(
                    replacement_role.ip_allowlist_entries.order_by("id").values_list(
                        "network_cidr", flat=True
                    )
                ),
            ),
        )
    if action_key == "superuser.ip_allowlist.update":
        policy = actor.superuser_security_policy
        return EndpointCase(
            "/api/v1/admin/security/superuser/ip-allowlist",
            "post",
            {
                "expected_security_version": policy.security_version,
                "network_cidr": "203.0.113.45/32",
                "label": "超级管理员出口",
                "confirm_lockout": False,
            },
            lambda: (
                actor.superuser_security_policy.__class__.objects.get(
                    pk=policy.pk
                ).security_version,
                tuple(
                    policy.ip_allowlist_entries.order_by("id").values_list(
                        "network_cidr", flat=True
                    )
                ),
            ),
        )
    if action_key == "customer.assignment.change":
        return EndpointCase(
            f"/api/v1/admin/users/{customer.id}/assignment",
            "put",
            {
                "expected_version": 0,
                "owner_admin_id": str(target_admin.id),
                "reason": "分配负责人",
            },
            lambda: tuple(
                CustomerAssignment.objects.filter(customer=customer).values_list(
                    "owner_admin_id", "version"
                )
            ),
        )
    if action_key == "user.freeze":
        return EndpointCase(
            f"/api/v1/admin/users/{customer.id}/freeze",
            "post",
            {"expected_version": customer.status_version, "reason": "安全冻结"},
            lambda: (
                User.objects.get(pk=customer.pk).account_status,
                User.objects.get(pk=customer.pk).status_version,
            ),
        )
    if action_key == "user.review.reject":
        return EndpointCase(
            f"/api/v1/admin/users/{customer.id}/review",
            "post",
            {
                "decision": "reject",
                "expected_version": customer.status_version,
                "reason": "资料不完整",
            },
            lambda: (
                User.objects.get(pk=customer.pk).approval_status,
                User.objects.get(pk=customer.pk).status_version,
            ),
        )
    raise AssertionError(action_key)


@pytest.mark.django_db
@pytest.mark.parametrize("action_key", sorted(RISK_ACTION_BY_KEY))
@pytest.mark.parametrize("mode", MODES)
def test_each_existing_high_risk_endpoint_enforces_policy_without_bypass(action_key, mode):
    requester = superuser("13900139000")
    cache.clear()
    approver = superuser("13700137000")
    case = build_case(action_key, requester)
    policy = RiskPolicy.objects.get(action_id=action_key)
    policy.current_mode = mode
    policy.version += 1
    policy.save(update_fields=["current_mode", "version", "updated_at"])
    before = case.snapshot()
    client = admin_client(requester)
    definition = RISK_ACTION_BY_KEY[action_key]

    if mode not in definition.supported_modes:
        body = {
            **case.body,
            "current_password": PASSWORD,
        }
        response = send(client, case, body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "RISK_SECURITY_MODE_NOT_SUPPORTED"
        assert case.snapshot() == before
        return

    if mode == "confirm":
        missing = send(client, case, dict(case.body))
        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "RISK_CONFIRMATION_REQUIRED"
        assert case.snapshot() == before
        response = send(client, case, {**case.body, "confirmed": True})
    elif mode == "password":
        missing = send(client, case, dict(case.body))
        assert missing.status_code == 422
        assert case.snapshot() == before
        wrong = send(
            client,
            case,
            {**case.body, "current_password": "Wrong-Password-2026!"},
        )
        assert wrong.status_code == 403
        assert wrong.json()["error"]["code"] == "ADMIN_REAUTH_FAILED"
        assert case.snapshot() == before
        response = send(
            client,
            case,
            {**case.body, "current_password": PASSWORD},
        )
    else:
        response = send(
            client,
            case,
            {
                **case.body,
                "confirmed": True,
                "current_password": PASSWORD,
            },
        )
        assert response.status_code == 202
        data = response.json()["data"]
        assert set(data) == {
            "approval_required",
            "approval_id",
            "status",
            "expires_at",
        }
        assert data["approval_required"] is True
        assert data["status"] == "pending"
        assert case.snapshot() == before
        approval = ApprovalRequest.objects.get(pk=data["approval_id"])
        approved = admin_client(approver).post(
            f"/api/v1/admin/approvals/{approval.id}/approve",
            {"current_password": PASSWORD},
            format="json",
        )
        assert approved.status_code == 200
        approval.refresh_from_db()
        assert approval.status == ApprovalRequest.Status.EXECUTED
        assert case.snapshot() != before
        replay = admin_client(approver).post(
            f"/api/v1/admin/approvals/{approval.id}/approve",
            {"current_password": PASSWORD},
            format="json",
        )
        assert replay.status_code == 409
        return

    assert response.status_code in {200, 201}
    assert case.snapshot() != before
    assert ApprovalRequest.objects.count() == 0
