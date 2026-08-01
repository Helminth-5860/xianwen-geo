import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminRole,
    ApprovalRequest,
    AuditEvent,
    RiskPolicy,
)
from apps.admin_rbac.services import change_admin_status, create_admin
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


def superuser(phone):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def admin_client(user):
    return authenticate_admin_client(APIClient(), user)


def create_disable_request(requester, target):
    response = admin_client(requester).post(
        f"/api/v1/admin/admins/{target.admin_profile.id}/disable",
        {
            "expected_version": target.admin_profile.version,
            "confirmed": True,
        },
        format="json",
    )
    assert response.status_code == 202
    return ApprovalRequest.objects.get(pk=response.json()["data"]["approval_id"])


def expire_in_database(approval):
    now = timezone.now()
    ApprovalRequest.objects.filter(pk=approval.pk).update(
        created_at=now - timedelta(minutes=2),
        expires_at=now - timedelta(minutes=1),
    )


@pytest.mark.django_db
@pytest.mark.parametrize("trigger", ["list", "detail", "approve", "cancel"])
def test_expiration_path_is_atomic_audited_and_idempotent(trigger):
    requester = superuser("13900139000")
    approver = superuser("13700137000")
    target = superuser("13600136000")
    approval = create_disable_request(requester, target)
    expire_in_database(approval)

    if trigger == "list":
        response = admin_client(requester).get("/api/v1/admin/approvals")
        assert response.status_code == 200
    elif trigger == "detail":
        response = admin_client(requester).get(f"/api/v1/admin/approvals/{approval.id}")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "expired"
    elif trigger == "approve":
        response = admin_client(approver).post(
            f"/api/v1/admin/approvals/{approval.id}/approve",
            {"current_password": PASSWORD},
            format="json",
        )
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "APPROVAL_EXPIRED"
    else:
        response = admin_client(requester).post(
            f"/api/v1/admin/approvals/{approval.id}/cancel", {}, format="json"
        )
        assert response.status_code == 410
        body = response.json()
        assert body["error"]["code"] == "APPROVAL_EXPIRED"
        assert body["request_id"] == response["X-Request-ID"]

    approval.refresh_from_db()
    target.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.EXPIRED
    assert approval.cancelled_at is None
    assert target.is_staff is True
    assert AuditEvent.objects.filter(approval_request=approval, outcome="expired").count() == 1

    repeated = admin_client(requester).get(f"/api/v1/admin/approvals/{approval.id}")
    assert repeated.status_code == 200
    assert AuditEvent.objects.filter(approval_request=approval, outcome="expired").count() == 1


@pytest.mark.django_db
def test_cancel_of_expired_request_is_stable_410_and_never_500():
    requester = superuser("13900139000")
    superuser("13700137000")
    target = superuser("13600136000")
    approval = create_disable_request(requester, target)
    expire_in_database(approval)
    client = admin_client(requester)

    for _ in range(2):
        response = client.post(f"/api/v1/admin/approvals/{approval.id}/cancel", {}, format="json")
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "APPROVAL_EXPIRED"

    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.EXPIRED
    assert approval.cancelled_at is None
    assert AuditEvent.objects.filter(approval_request=approval, outcome="expired").count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("trigger", ["list", "detail", "approve", "cancel"])
def test_expiration_audit_failure_rolls_back_to_pending(monkeypatch, trigger):
    requester = superuser("13900139000")
    approver = superuser("13700137000")
    target = superuser("13600136000")
    approval = create_disable_request(requester, target)
    expire_in_database(approval)

    def fail_audit(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.admin_rbac.risk_services.record_audit_event", fail_audit)
    if trigger == "list":
        response = admin_client(requester).get("/api/v1/admin/approvals")
    elif trigger == "detail":
        response = admin_client(requester).get(f"/api/v1/admin/approvals/{approval.id}")
    elif trigger == "approve":
        response = admin_client(approver).post(
            f"/api/v1/admin/approvals/{approval.id}/approve",
            {"current_password": PASSWORD},
            format="json",
        )
    else:
        response = admin_client(requester).post(
            f"/api/v1/admin/approvals/{approval.id}/cancel", {}, format="json"
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    approval.refresh_from_db()
    target.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING
    assert target.is_staff is True
    assert not AuditEvent.objects.filter(approval_request=approval, outcome="expired").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("status_action", ["disable", "lock"])
def test_disabled_or_locked_approver_cannot_execute_but_another_can(status_action):
    requester = superuser("13900139000")
    invalid_approver = superuser("13700137000")
    valid_approver = superuser("13500135000")
    target = superuser("13600136000")
    approval = create_disable_request(requester, target)
    invalid_client = admin_client(invalid_approver)

    profile = invalid_approver.admin_profile
    change_admin_status(
        actor_id=requester.pk,
        profile_id=profile.pk,
        action=status_action,
        expected_version=profile.version,
        request_id=uuid.uuid4(),
    )
    denied = invalid_client.post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    assert denied.status_code in {401, 403}
    approval.refresh_from_db()
    target.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING
    assert target.is_staff is True

    approved = admin_client(valid_approver).post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    assert approved.status_code == 200
    approval.refresh_from_db()
    target.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.EXECUTED
    assert target.is_staff is False


@pytest.mark.django_db
def test_approver_requires_admin_security_session_superuser_and_correct_password():
    requester = superuser("13900139000")
    valid_approver = superuser("13700137000")
    target = superuser("13600136000")
    approval = create_disable_request(requester, target)

    legacy = APIClient()
    legacy.force_login(valid_approver)
    missing_context = legacy.post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    assert missing_context.status_code in {401, 403}

    role = AdminRole.objects.create(name="无审批权限角色", data_scope=AdminRole.DataScope.ALL)
    ordinary_admin = create_admin(
        actor_id=requester.pk,
        phone="13500135000",
        nickname="普通管理员",
        password=PASSWORD,
        role_id=role.pk,
        request_id=uuid.uuid4(),
    ).user
    not_superuser = admin_client(ordinary_admin).post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    assert not_superuser.status_code == 403

    self_approval = admin_client(requester).post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    assert self_approval.status_code == 403
    assert self_approval.json()["error"]["code"] == "APPROVAL_SELF_NOT_ALLOWED"

    wrong_password = admin_client(valid_approver).post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": "Wrong-Password-2026!"},
        format="json",
    )
    assert wrong_password.status_code == 403
    assert wrong_password.json()["error"]["code"] == "ADMIN_REAUTH_FAILED"
    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING


@pytest.mark.django_db
@pytest.mark.parametrize("new_mode", ["password", "two_person"])
def test_policy_version_or_mode_change_marks_pending_request_stale(new_mode):
    requester = superuser("13900139000")
    approver = superuser("13700137000")
    target = superuser("13600136000")
    approval = create_disable_request(requester, target)
    original_policy_version = approval.policy_version
    policy = RiskPolicy.objects.get(action_id=approval.action_key)
    policy.current_mode = new_mode
    policy.version += 1
    policy.save(update_fields=["current_mode", "version", "updated_at"])

    response = admin_client(approver).post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPROVAL_STALE"
    approval.refresh_from_db()
    target.refresh_from_db()
    assert approval.policy_version == original_policy_version
    assert approval.status == ApprovalRequest.Status.STALE
    assert target.is_staff is True
    assert AuditEvent.objects.filter(approval_request=approval, outcome="stale").count() == 1
