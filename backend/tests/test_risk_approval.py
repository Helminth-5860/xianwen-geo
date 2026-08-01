import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminProfile, ApprovalRequest, AuditEvent, RiskAction, RiskPolicy
from apps.admin_rbac.risk_catalog import RISK_ACTION_CATALOG, mode_is_valid
from apps.admin_rbac.risk_services import ApprovalPayloadInvalid, canonical_payload
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


def superuser(phone):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def admin_client(user, *, csrf=False):
    client = APIClient(enforce_csrf_checks=csrf)
    return authenticate_admin_client(client, user)


@pytest.mark.django_db
def test_risk_catalog_seed_sync_and_static_modes_are_consistent():
    assert RiskAction.objects.count() == len(RISK_ACTION_CATALOG)
    assert RiskPolicy.objects.count() == len(RISK_ACTION_CATALOG)
    for definition in RISK_ACTION_CATALOG:
        action = RiskAction.objects.get(pk=definition.key)
        assert action.handler_key == definition.key
        assert definition.default_mode in definition.supported_modes
        assert definition.minimum_mode in definition.supported_modes
        assert mode_is_valid(definition, action.policy.current_mode)
    call_command("sync_admin_rbac", "--apply")
    call_command("sync_admin_rbac", "--apply")
    assert RiskAction.objects.count() == len(RISK_ACTION_CATALOG)


@pytest.mark.django_db
def test_catalog_sync_repairs_metadata_and_invalid_policy_without_deleting_unknown():
    action = RiskAction.objects.get(pk="user.freeze")
    action.name = "drift"
    action.save(update_fields=["name"])
    policy = action.policy
    policy.current_mode = "password"
    policy.save(update_fields=["current_mode"])
    RiskAction.objects.create(
        key="future.safe.action",
        name="未来动作",
        module="future",
        target_type="future",
        supported_modes=["confirm"],
        default_mode="confirm",
        minimum_mode="confirm",
        handler_key="future.safe.action",
    )

    call_command("sync_admin_rbac", "--apply")

    action.refresh_from_db()
    policy.refresh_from_db()
    assert action.name == "冻结用户"
    assert policy.current_mode == "password"
    assert RiskAction.objects.filter(pk="future.safe.action").exists()


@pytest.mark.django_db
def test_canonical_payload_is_stable_bound_and_rejects_sensitive_or_executable_values():
    target = uuid.uuid4()
    left, left_digest = canonical_payload("user.freeze", "user", target, 1, {"reason": "安全原因"})
    right, right_digest = canonical_payload(
        "user.freeze", "user", target, 1, {"reason": "安全原因"}
    )
    assert left == right
    assert left_digest == right_digest
    assert (
        left_digest
        != canonical_payload("user.freeze", "user", target, 2, {"reason": "安全原因"})[1]
    )
    for payload in (
        {"password": "never"},
        {"reason": "https://invalid.example"},
        {"reason": "select * from users"},
        {"reason": "import os"},
        {"reason": "line\ncontrol"},
    ):
        with pytest.raises(ApprovalPayloadInvalid):
            canonical_payload("user.freeze", "user", target, 1, payload)


@pytest.mark.django_db
def test_confirm_mode_requires_confirmation_and_executes_with_audit():
    actor = superuser("13900139000")
    target = User.objects.create_user(phone="13800138000", nickname="客户", password=PASSWORD)
    client = admin_client(actor)
    path = f"/api/v1/admin/users/{target.id}/freeze"

    missing = client.post(path, {"expected_version": target.status_version}, format="json")
    executed = client.post(
        path,
        {"expected_version": target.status_version, "confirmed": True},
        format="json",
    )

    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "RISK_CONFIRMATION_REQUIRED"
    assert executed.status_code == 200
    target.refresh_from_db()
    assert target.account_status == User.AccountStatus.FROZEN
    assert target.status_version == 2
    assert AuditEvent.objects.get(action_key="user.freeze").outcome == "executed"


@pytest.mark.django_db
def test_password_mode_reauthenticates_and_two_person_creates_minimal_request():
    requester = superuser("13900139000")
    superuser("13700137000")
    target = superuser("13600136000")
    client = admin_client(requester)

    locked = client.post(
        f"/api/v1/admin/admins/{target.admin_profile.id}/lock",
        {
            "expected_version": target.admin_profile.version,
            "current_password": "wrong-password",
            "confirmed": True,
        },
        format="json",
    )
    requested = client.post(
        f"/api/v1/admin/admins/{target.admin_profile.id}/disable",
        {
            "expected_version": target.admin_profile.version,
            "current_password": PASSWORD,
            "confirmed": True,
        },
        format="json",
    )

    assert locked.status_code == 403
    assert locked.json()["error"]["code"] == "ADMIN_REAUTH_FAILED"
    assert requested.status_code == 202
    body = requested.json()["data"]
    assert body["approval_required"] is True
    assert set(body) == {"approval_required", "approval_id", "status", "expires_at"}
    target.refresh_from_db()
    assert target.is_active is True


@pytest.mark.django_db
def test_two_person_requires_another_valid_superuser_and_cannot_self_approve():
    requester = superuser("13900139000")
    target = User.objects.create_user(
        phone="13800138000", nickname="管理员", password=PASSWORD, is_staff=True
    )
    AdminProfile.objects.create(user=target)
    client = admin_client(requester)
    path = f"/api/v1/admin/admins/{target.admin_profile.id}/disable"

    unavailable = client.post(
        path,
        {"expected_version": target.admin_profile.version, "confirmed": True},
        format="json",
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == "APPROVAL_APPROVER_UNAVAILABLE"

    superuser("13700137000")
    requested = client.post(
        path,
        {"expected_version": target.admin_profile.version, "confirmed": True},
        format="json",
    )
    approval_id = requested.json()["data"]["approval_id"]
    self_approval = client.post(
        f"/api/v1/admin/approvals/{approval_id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    assert self_approval.status_code == 403
    assert self_approval.json()["error"]["code"] == "APPROVAL_SELF_NOT_ALLOWED"


@pytest.mark.django_db
def test_approval_approve_executes_exactly_once_and_replay_conflicts():
    requester = superuser("13900139000")
    approver = superuser("13700137000")
    target = superuser("13600136000")
    request_client = admin_client(requester)
    approve_client = admin_client(approver)
    response = request_client.post(
        f"/api/v1/admin/admins/{target.admin_profile.id}/disable",
        {"expected_version": target.admin_profile.version, "confirmed": True},
        format="json",
    )
    approval_id = response.json()["data"]["approval_id"]

    executed = approve_client.post(
        f"/api/v1/admin/approvals/{approval_id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    replay = approve_client.post(
        f"/api/v1/admin/approvals/{approval_id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )

    assert executed.status_code == 200
    assert executed.json()["data"]["status"] == "executed"
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "APPROVAL_STATE_CONFLICT"
    target.refresh_from_db()
    assert target.is_staff is False
    assert target.admin_profile.admin_status == AdminProfile.Status.DISABLED
    assert (
        AuditEvent.objects.filter(approval_request_id=approval_id, outcome="executed").count() == 1
    )


@pytest.mark.django_db
def test_approval_cancel_reject_expire_and_no_generic_create_route():
    requester = superuser("13900139000")
    approver = superuser("13700137000")
    target = superuser("13600136000")
    requester_client = admin_client(requester)
    approver_client = admin_client(approver)

    def create_request():
        response = requester_client.post(
            f"/api/v1/admin/admins/{target.admin_profile.id}/disable",
            {"expected_version": target.admin_profile.version, "confirmed": True},
            format="json",
        )
        return ApprovalRequest.objects.get(pk=response.json()["data"]["approval_id"])

    cancelled = create_request()
    cancel_response = requester_client.post(
        f"/api/v1/admin/approvals/{cancelled.id}/cancel", {}, format="json"
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["data"]["status"] == "cancelled"

    rejected = create_request()
    reject_response = approver_client.post(
        f"/api/v1/admin/approvals/{rejected.id}/reject",
        {"reason": "当前变更不符合安全要求"},
        format="json",
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["data"]["status"] == "rejected"

    expired = create_request()
    now = timezone.now()
    ApprovalRequest.objects.filter(pk=expired.pk).update(
        created_at=now - timedelta(hours=2), expires_at=now - timedelta(hours=1)
    )
    expired_response = approver_client.post(
        f"/api/v1/admin/approvals/{expired.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    assert expired_response.status_code == 410
    expired.refresh_from_db()
    assert expired.status == ApprovalRequest.Status.EXPIRED
    assert requester_client.post("/api/v1/admin/approvals", {}, format="json").status_code == 405


@pytest.mark.django_db
def test_pending_duplicate_has_database_uniqueness():
    requester = superuser("13900139000")
    action = RiskAction.objects.get(pk="admin.disable")
    target = uuid.uuid4()
    fields = {
        "action": action,
        "action_key": action.key,
        "policy_version": action.policy.version,
        "requester": requester,
        "target_type": action.target_type,
        "target_id": target,
        "target_version": 1,
        "sanitized_payload": {},
        "payload_digest": "a" * 64,
        "safe_summary": "安全摘要",
        "expires_at": timezone.now() + timedelta(hours=1),
        "request_id": uuid.uuid4(),
    }
    ApprovalRequest.objects.create(**fields)
    with pytest.raises(IntegrityError), transaction.atomic():
        ApprovalRequest.objects.create(**fields)


@pytest.mark.django_db
def test_approval_visibility_audit_visibility_and_append_only_guards():
    requester = superuser("13900139000")
    other = superuser("13700137000")
    target = superuser("13600136000")
    request_client = admin_client(requester)
    other_client = admin_client(other)
    response = request_client.post(
        f"/api/v1/admin/admins/{target.admin_profile.id}/disable",
        {"expected_version": target.admin_profile.version, "confirmed": True},
        format="json",
    )
    approval_id = response.json()["data"]["approval_id"]

    assert request_client.get("/api/v1/admin/approvals").status_code == 200
    assert other_client.get(f"/api/v1/admin/approvals/{approval_id}").status_code == 200
    assert request_client.patch(f"/api/v1/admin/approvals/{approval_id}", {}).status_code == 405
    event = AuditEvent.objects.filter(approval_request_id=approval_id).first()
    assert event is not None
    with pytest.raises(TypeError):
        AuditEvent.objects.filter(pk=event.pk).update(outcome="tampered")
    with pytest.raises(TypeError):
        event.delete()


@pytest.mark.django_db
def test_old_composite_patch_paths_reject_high_risk_fields_without_mutation():
    actor = superuser("13900139000")
    target = User.objects.create_user(
        phone="13800138000", nickname="管理员", password=PASSWORD, is_staff=True
    )
    profile = AdminProfile.objects.create(user=target)
    from apps.admin_rbac.models import AdminPermission, AdminRole, AdminRolePermission

    first_role = AdminRole.objects.create(name="原角色", data_scope=AdminRole.DataScope.ALL)
    second_role = AdminRole.objects.create(name="新角色", data_scope=AdminRole.DataScope.ALL)
    profile.role = first_role
    profile.save(update_fields=["role", "updated_at"])
    permission = AdminPermission.objects.get(key="users.list")
    api = admin_client(actor)

    admin_response = api.patch(
        f"/api/v1/admin/admins/{profile.id}",
        {"expected_version": profile.version, "role_id": str(second_role.id)},
        format="json",
    )
    role_response = api.patch(
        f"/api/v1/admin/roles/{first_role.id}",
        {
            "expected_version": first_role.version,
            "permission_keys": [permission.key],
        },
        format="json",
    )

    assert admin_response.status_code == 422
    assert role_response.status_code == 422
    profile.refresh_from_db()
    assert profile.role_id == first_role.id
    assert not AdminRolePermission.objects.filter(role=first_role).exists()
