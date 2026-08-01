import uuid

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminPermission, AdminRole, AdminRolePermission
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.services import create_admin, set_permission_status
from apps.users.models import User

PASSWORD = "Correct-Horse-Battery-2026!"


def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return client, response.json()["data"]["csrf_token"]


def login(client, token, phone):
    return client.post(
        "/api/v1/admin/auth/login/password",
        {"phone": phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )


@pytest.fixture(autouse=True)
def clear_limits():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_permission_status_command_revokes_only_affected_sessions_and_is_idempotent():
    actor = User.objects.create_superuser(
        phone="13900139000", nickname="超级管理员", password=PASSWORD
    )
    affected_role = AdminRole.objects.create(name="审核员", data_scope=AdminRole.DataScope.ALL)
    unrelated_role = AdminRole.objects.create(name="观察员", data_scope=AdminRole.DataScope.ALL)
    permission = AdminPermission.objects.get(key="users.list")
    dashboard = AdminPermission.objects.get(key="admin.dashboard.view")
    AdminRolePermission.objects.bulk_create(
        [
            AdminRolePermission(role=affected_role, permission=permission),
            AdminRolePermission(role=unrelated_role, permission=dashboard),
        ]
    )
    affected = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="受影响管理员",
        password=PASSWORD,
        role_id=affected_role.id,
        request_id=uuid.uuid4(),
    )
    unrelated = create_admin(
        actor_id=actor.id,
        phone="13600136000",
        nickname="不相关管理员",
        password=PASSWORD,
        role_id=unrelated_role.id,
        request_id=uuid.uuid4(),
    )
    affected_client, affected_csrf = csrf_client()
    unrelated_client, unrelated_csrf = csrf_client()
    assert login(affected_client, affected_csrf, affected.user.phone).status_code == 200
    assert login(unrelated_client, unrelated_csrf, unrelated.user.phone).status_code == 200
    affected_version = affected.user.session_version
    unrelated_version = unrelated.user.session_version

    call_command(
        "sync_admin_rbac",
        "--apply",
        "--permission-key",
        "users.list",
        "--permission-status",
        "inactive",
    )
    affected.user.refresh_from_db()
    unrelated.user.refresh_from_db()
    permission.refresh_from_db()

    assert affected.user.session_version == affected_version + 1
    assert unrelated.user.session_version == unrelated_version
    assert affected_client.get("/api/v1/me").status_code == 401
    assert unrelated_client.get("/api/v1/me").status_code == 200
    assert permission.status == AdminPermission.Status.INACTIVE
    context = resolve_admin_context(affected.user)
    assert context is not None
    assert "users.list" not in context.permission_keys

    call_command(
        "sync_admin_rbac",
        "--apply",
        "--permission-key",
        "users.list",
        "--permission-status",
        "inactive",
    )
    affected.user.refresh_from_db()
    assert affected.user.session_version == affected_version + 1

    call_command(
        "sync_admin_rbac",
        "--apply",
        "--permission-key",
        "users.list",
        "--permission-status",
        "active",
    )
    affected.user.refresh_from_db()
    assert affected.user.session_version == affected_version + 1
    assert affected_client.get("/api/v1/me").status_code == 401


@pytest.mark.django_db
def test_permission_status_cannot_be_changed_with_model_save():
    permission = AdminPermission.objects.get(key="users.list")
    permission.status = AdminPermission.Status.INACTIVE
    with pytest.raises(ValidationError):
        permission.save(update_fields=["status"])

    permission.refresh_from_db()
    assert permission.status == AdminPermission.Status.ACTIVE


@pytest.mark.django_db
def test_permission_status_service_rejects_invalid_status():
    with pytest.raises(ValueError):
        set_permission_status(permission_key="users.list", status="deleted")
