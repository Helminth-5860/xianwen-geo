import uuid

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminProfile, AuditEvent, RiskAction, RiskPolicy
from apps.admin_rbac.risk_catalog import (
    RISK_ACTION_CATALOG,
    SMS_STEP_UP_REQUIRED_ACTIONS,
    mode_is_valid,
)
from apps.admin_rbac.risk_services import RiskPayloadInvalid, canonical_payload
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


def test_sms_step_up_policy_is_narrow_and_explicit():
    expected_security_critical = {
        "admin.disable",
        "admin.lock",
        "admin.role.change",
        "admin.force_logout",
        "role.permissions.replace",
        "role.disable",
        "role.security.update",
        "role.ip_allowlist.update",
        "superuser.ip_allowlist.update",
        "user.freeze",
        "quota.grant",
        "quota.compensate",
        "quota.manual_deduct",
        "subject_risk.catalog.publish",
    }
    business_high_risk = {
        "customer.assignment.change",
        "plan.create",
        "plan.update",
        "plan.version.create",
        "plan.version.update",
        "plan.version.publish",
        "plan.online",
        "plan.offline",
        "plan.version.retire",
        "plan.archive",
        "plan.copy",
        "plan_application.contact",
        "plan_application.close",
        "subscription.open",
        "subscription.grant_trial",
        "subscription.terminate",
        "subscription.change",
        "subscription.change.cancel",
    }

    assert len(RISK_ACTION_CATALOG) == 32
    assert SMS_STEP_UP_REQUIRED_ACTIONS == expected_security_critical
    assert len(SMS_STEP_UP_REQUIRED_ACTIONS) == 14
    assert SMS_STEP_UP_REQUIRED_ACTIONS.isdisjoint(business_high_risk)


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
    assert action.name == "禁用用户"
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
        with pytest.raises(RiskPayloadInvalid):
            canonical_payload("user.freeze", "user", target, 1, payload)


@pytest.mark.django_db
def test_confirm_mode_requires_confirmation_and_executes_with_audit():
    actor = superuser("13900139000")
    target = User.objects.create_user(phone="13800138000", nickname="客户", password=PASSWORD)
    denied_client = authenticate_admin_client(APIClient(), actor, step_up=False)
    denied = denied_client.post(
        f"/api/v1/admin/users/{target.id}/freeze",
        {"expected_version": target.status_version, "confirmed": True},
        format="json",
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ADMIN_STEP_UP_REQUIRED"

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
def test_password_mode_reauthenticates_and_executes_without_creating_request():
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
    assert requested.status_code == 200
    target.refresh_from_db()
    assert target.is_staff is False
    assert target.admin_profile.admin_status == AdminProfile.Status.DISABLED
    assert AuditEvent.objects.get(action_key="admin.disable").outcome == "executed"


@pytest.mark.django_db
def test_single_superuser_can_execute_and_retired_workflow_route_is_unavailable():
    requester = superuser("13900139000")
    target = User.objects.create_user(
        phone="13800138000", nickname="管理员", password=PASSWORD, is_staff=True
    )
    AdminProfile.objects.create(user=target)
    client = admin_client(requester)
    path = f"/api/v1/admin/admins/{target.admin_profile.id}/disable"

    missing_password = client.post(
        path,
        {"expected_version": target.admin_profile.version, "confirmed": True},
        format="json",
    )
    executed = client.post(
        path,
        {
            "expected_version": target.admin_profile.version,
            "confirmed": True,
            "current_password": PASSWORD,
        },
        format="json",
    )
    assert missing_password.status_code == 422
    assert executed.status_code == 200
    assert client.get("/api/v1/admin/approvals").status_code == 404


@pytest.mark.django_db
def test_direct_action_executes_exactly_once_and_stale_replay_conflicts():
    requester = superuser("13900139000")
    target = superuser("13600136000")
    request_client = admin_client(requester)
    original_version = target.admin_profile.version
    response = request_client.post(
        f"/api/v1/admin/admins/{target.admin_profile.id}/disable",
        {
            "expected_version": original_version,
            "confirmed": True,
            "current_password": PASSWORD,
        },
        format="json",
    )
    replay = request_client.post(
        f"/api/v1/admin/admins/{target.admin_profile.id}/disable",
        {
            "expected_version": original_version,
            "confirmed": True,
            "current_password": PASSWORD,
        },
        format="json",
    )

    assert response.status_code == 200
    assert replay.status_code == 409
    target.refresh_from_db()
    assert target.is_staff is False
    assert target.admin_profile.admin_status == AdminProfile.Status.DISABLED
    assert AuditEvent.objects.filter(action_key="admin.disable", outcome="executed").count() == 1


@pytest.mark.django_db
def test_all_retired_workflow_routes_are_unavailable():
    requester = superuser("13900139000")
    client = admin_client(requester)
    request_id = uuid.uuid4()

    assert client.get("/api/v1/admin/approvals").status_code == 404
    assert client.post("/api/v1/admin/approvals", {}, format="json").status_code == 404
    for suffix in ("", "/approve", "/reject", "/cancel"):
        assert client.post(f"/api/v1/admin/approvals/{request_id}{suffix}", {}).status_code == 404


@pytest.mark.django_db
def test_direct_action_audit_visibility_and_append_only_guards():
    requester = superuser("13900139000")
    target = superuser("13600136000")
    request_client = admin_client(requester)
    response = request_client.post(
        f"/api/v1/admin/admins/{target.admin_profile.id}/disable",
        {
            "expected_version": target.admin_profile.version,
            "confirmed": True,
            "current_password": PASSWORD,
        },
        format="json",
    )
    assert response.status_code == 200
    event = AuditEvent.objects.filter(action_key="admin.disable", outcome="executed").first()
    assert event is not None
    assert request_client.get("/api/v1/admin/audit-events").status_code == 200
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
