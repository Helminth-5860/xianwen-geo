import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connection, connections
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.models import AuditEvent, RiskAction, RiskPolicy
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def require_postgresql_and_seed_catalog():
    if connection.vendor != "postgresql":
        pytest.skip("Run through scripts/test-risk-action.* with PostgreSQL and Redis.")
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


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
        return [future.result(timeout=30) for future in futures]


def superuser(phone):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def client(user):
    return authenticate_admin_client(APIClient(), user)


def test_postgresql_catalog_has_only_confirmation_and_password_modes():
    assert RiskAction.objects.exists()
    assert all(
        set(action.supported_modes) <= {"confirm", "password"}
        for action in RiskAction.objects.all()
    )
    assert not RiskPolicy.objects.exclude(current_mode__in=("confirm", "password")).exists()


def test_postgresql_retired_queue_routes_are_unavailable():
    actor = superuser("13900139000")
    request_id = "00000000-0000-0000-0000-000000000001"
    admin = client(actor)
    assert admin.get("/api/v1/admin/approvals").status_code == 404
    for suffix in ("", "/approve", "/reject", "/cancel"):
        assert admin.post(f"/api/v1/admin/approvals/{request_id}{suffix}", {}).status_code == 404


def test_postgresql_concurrent_direct_action_executes_and_audits_exactly_once():
    actor = superuser("13900139001")
    target = superuser("13800138001")
    target_version = target.admin_profile.version
    target_profile_id = target.admin_profile.pk
    path = f"/api/v1/admin/admins/{target_profile_id}/disable"
    payload = {
        "expected_version": target_version,
        "confirmed": True,
        "current_password": PASSWORD,
    }

    responses = run_parallel(
        lambda: client(User.objects.get(pk=actor.pk)).post(path, payload, format="json"),
        lambda: client(User.objects.get(pk=actor.pk)).post(path, payload, format="json"),
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    target.refresh_from_db()
    target.admin_profile.refresh_from_db()
    assert target.is_staff is False
    assert target.admin_profile.admin_status == "disabled"
    assert (
        AuditEvent.objects.filter(
            action_key="admin.disable", outcome="executed", target_id=str(target_profile_id)
        ).count()
        == 1
    )


def test_postgresql_stale_target_fails_closed_without_queue_or_execution_audit():
    actor = superuser("13900139002")
    target = superuser("13800138002")
    target_profile_id = target.admin_profile.pk
    response = client(actor).post(
        f"/api/v1/admin/admins/{target_profile_id}/disable",
        {
            "expected_version": target.admin_profile.version + 1,
            "confirmed": True,
            "current_password": PASSWORD,
        },
        format="json",
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RISK_TARGET_STALE"
    assert not AuditEvent.objects.filter(action_key="admin.disable", outcome="executed").exists()
