import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connection, connections
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    ApprovalRequest,
    AuditEvent,
    CustomerAssignment,
    RiskPolicy,
)
from apps.admin_rbac.services import (
    LastSuperuserProtected,
    change_admin_status,
    create_admin,
)
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def seed_catalog_and_clear_redis():
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    if connection.vendor != "postgresql":
        yield
        return
    redis = get_redis_connection("default")
    redis.flushdb()
    yield
    redis.flushdb()


def require_postgresql():
    if connection.vendor != "postgresql":
        pytest.skip("仅通过 scripts/test-risk-approval.* 在真实 PostgreSQL/Redis 执行。")


def run_parallel(*operations):
    barrier = threading.Barrier(len(operations))

    def run(operation):
        close_old_connections()
        barrier.wait()
        try:
            return operation()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        futures = [pool.submit(run, operation) for operation in operations]
        return [future.result() for future in futures]


def superuser(phone):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def client(user):
    return authenticate_admin_client(APIClient(), user)


def create_disable_request(requester, target):
    response = client(requester).post(
        f"/api/v1/admin/admins/{target.admin_profile.id}/disable",
        {"expected_version": target.admin_profile.version, "confirmed": True},
        format="json",
    )
    assert response.status_code == 202
    return ApprovalRequest.objects.get(pk=response.json()["data"]["approval_id"])


def test_postgresql_concurrent_approve_executes_handler_exactly_once():
    require_postgresql()
    requester = superuser("13900139000")
    approver = superuser("13700137000")
    target = superuser("13600136000")
    approval = create_disable_request(requester, target)
    first = client(approver)
    second = client(approver)

    responses = run_parallel(
        lambda: first.post(
            f"/api/v1/admin/approvals/{approval.id}/approve",
            {"current_password": PASSWORD},
            format="json",
        ),
        lambda: second.post(
            f"/api/v1/admin/approvals/{approval.id}/approve",
            {"current_password": PASSWORD},
            format="json",
        ),
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    approval.refresh_from_db()
    target.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.EXECUTED
    assert target.is_staff is False
    assert AuditEvent.objects.filter(approval_request=approval, outcome="executed").count() == 1


def test_postgresql_approve_cancel_race_has_one_terminal_winner():
    require_postgresql()
    requester = superuser("13900139000")
    approver = superuser("13700137000")
    target = superuser("13600136000")
    approval = create_disable_request(requester, target)
    approve_client = client(approver)
    cancel_client = client(requester)

    responses = run_parallel(
        lambda: approve_client.post(
            f"/api/v1/admin/approvals/{approval.id}/approve",
            {"current_password": PASSWORD},
            format="json",
        ),
        lambda: cancel_client.post(
            f"/api/v1/admin/approvals/{approval.id}/cancel", {}, format="json"
        ),
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    approval.refresh_from_db()
    assert approval.status in {
        ApprovalRequest.Status.EXECUTED,
        ApprovalRequest.Status.CANCELLED,
    }


def test_postgresql_target_version_change_marks_approval_stale():
    require_postgresql()
    requester = superuser("13900139000")
    approver = superuser("13700137000")
    target = superuser("13600136000")
    approval = create_disable_request(requester, target)
    profile = target.admin_profile
    profile.version += 1
    profile.save(update_fields=["version", "updated_at"])

    response = client(approver).post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPROVAL_STALE"
    approval.refresh_from_db()
    target.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.STALE
    assert target.is_staff is True


def test_postgresql_requester_permission_loss_marks_approval_stale():
    require_postgresql()
    approver = superuser("13900139000")
    role = AdminRole.objects.create(name="风控管理员", data_scope=AdminRole.DataScope.ALL)
    permissions = AdminPermission.objects.filter(
        key__in=("users.freeze", "approvals.request", "approvals.list", "approvals.view")
    )
    AdminRolePermission.objects.bulk_create(
        [AdminRolePermission(role=role, permission=permission) for permission in permissions]
    )
    requester = create_admin(
        actor_id=approver.pk,
        phone="13700137000",
        nickname="普通管理员",
        password=PASSWORD,
        role_id=role.pk,
        request_id=uuid.uuid4(),
    ).user
    target = User.objects.create_user(phone="13800138000", nickname="客户", password=PASSWORD)
    policy = RiskPolicy.objects.get(action_id="user.freeze")
    policy.current_mode = "two_person"
    policy.version += 1
    policy.save(update_fields=["current_mode", "version", "updated_at"])
    response = client(requester).post(
        f"/api/v1/admin/users/{target.id}/freeze",
        {"expected_version": target.status_version, "confirmed": True},
        format="json",
    )
    assert response.status_code == 202
    approval = ApprovalRequest.objects.get(pk=response.json()["data"]["approval_id"])
    AdminRolePermission.objects.filter(role=role, permission__key="users.freeze").delete()

    approved = client(approver).post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )

    assert approved.status_code == 409
    approval.refresh_from_db()
    target.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.STALE
    assert target.account_status == User.AccountStatus.ACTIVE


def test_postgresql_duplicate_business_requests_share_one_pending_row():
    require_postgresql()
    requester = superuser("13900139000")
    superuser("13700137000")
    target = superuser("13600136000")
    first = client(requester)
    second = client(requester)
    path = f"/api/v1/admin/admins/{target.admin_profile.id}/disable"
    body = {"expected_version": target.admin_profile.version, "confirmed": True}

    responses = run_parallel(
        lambda: first.post(path, body, format="json"),
        lambda: second.post(path, body, format="json"),
    )

    assert [response.status_code for response in responses] == [202, 202]
    ids = {response.json()["data"]["approval_id"] for response in responses}
    assert len(ids) == 1
    assert ApprovalRequest.objects.filter(status="pending").count() == 1


def test_postgresql_handler_failure_rolls_back_savepoint_and_records_safe_failure():
    require_postgresql()
    requester = superuser("13900139000")
    approver = superuser("13700137000")
    role = AdminRole.objects.create(name="客户经理", data_scope=AdminRole.DataScope.ALL)
    target = create_admin(
        actor_id=requester.pk,
        phone="13600136000",
        nickname="目标管理员",
        password=PASSWORD,
        role_id=role.pk,
        request_id=uuid.uuid4(),
    )
    customer = User.objects.create_user(phone="13800138000", nickname="客户", password=PASSWORD)
    CustomerAssignment.objects.create(customer=customer, owner_admin=target)
    approval = create_disable_request(requester, target.user)

    response = client(approver).post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )

    assert response.status_code == 200
    approval.refresh_from_db()
    target.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.EXECUTION_FAILED
    assert approval.stable_error_code
    assert target.admin_status == target.Status.ACTIVE
    assert (
        AuditEvent.objects.filter(approval_request=approval, outcome="execution_failed").count()
        == 1
    )


def test_postgresql_audit_failure_rolls_back_business_and_keeps_request_pending(monkeypatch):
    require_postgresql()
    requester = superuser("13900139000")
    approver = superuser("13700137000")
    target = superuser("13600136000")
    approval = create_disable_request(requester, target)

    def fail_audit(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.admin_rbac.risk_services.record_audit_event", fail_audit)
    response = client(approver).post(
        f"/api/v1/admin/approvals/{approval.id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )

    assert response.status_code == 500
    approval.refresh_from_db()
    target.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING
    assert target.is_staff is True


def test_postgresql_existing_last_superuser_protection_remains_enforced():
    require_postgresql()
    only = superuser("13900139000")
    with pytest.raises(LastSuperuserProtected):
        change_admin_status(
            actor_id=only.pk,
            profile_id=only.admin_profile.pk,
            action="disable",
            expected_version=only.admin_profile.version,
            request_id=uuid.uuid4(),
        )
