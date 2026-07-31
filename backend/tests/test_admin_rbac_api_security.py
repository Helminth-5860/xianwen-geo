import uuid

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    CustomerAssignment,
)
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.services import create_admin
from apps.users.models import User

PASSWORD = "Correct-Horse-Battery-2026!"
CSRF_PATH = "/api/v1/auth/csrf"
LOGIN_PATH = "/api/v1/auth/login/password"


def create_superuser(phone="13900139000"):
    return User.objects.create_superuser(
        phone=phone,
        nickname="超级管理员",
        password=PASSWORD,
    )


def browser_client(phone):
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get(CSRF_PATH).json()["data"]["csrf_token"]
    response = client.post(
        LOGIN_PATH,
        {"phone": phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 200
    return client


@pytest.mark.django_db
def test_rbac_writes_require_real_csrf_and_keep_envelope_request_id():
    actor = create_superuser()
    client = browser_client(actor.phone)
    path = "/api/v1/admin/roles"
    payload = {"name": "客服", "description": "", "data_scope": "own"}

    rejected = client.post(path, payload, format="json")
    csrf = client.cookies["xianwen_csrf"].value
    request_id = str(uuid.uuid4())
    created = client.post(
        path,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_X_REQUEST_ID=request_id,
    )

    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "CSRF_FAILED"
    assert created.status_code == 201
    assert created["X-Request-ID"] == request_id
    assert created.json()["success"] is True
    assert created.json()["request_id"] == request_id


@pytest.mark.django_db
def test_inactive_permission_and_invalid_admin_invariants_fail_closed():
    actor = create_superuser()
    role = AdminRole.objects.create(name="只读", data_scope=AdminRole.DataScope.ALL)
    permission = AdminPermission.objects.get(key="users.list")
    AdminRolePermission.objects.create(role=role, permission=permission)
    profile = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="普通管理员",
        password=PASSWORD,
        role_id=role.id,
        request_id=uuid.uuid4(),
    )
    permission.status = AdminPermission.Status.INACTIVE
    permission.save(update_fields=["status"])

    context = resolve_admin_context(profile.user)
    assert context is not None
    assert "users.list" not in context.permission_keys
    client = APIClient()
    client.force_authenticate(profile.user)
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/api/v1/admin/admins").status_code == 403

    profile.role = None
    profile.save(update_fields=["role"])
    assert resolve_admin_context(profile.user) is None
    assert client.get("/api/v1/admin/me").status_code == 403


@pytest.mark.django_db
def test_exact_phone_filter_and_object_lookup_never_escape_own_scope():
    actor = create_superuser()
    role = AdminRole.objects.create(name="本人客户", data_scope=AdminRole.DataScope.OWN)
    list_permission = AdminPermission.objects.get(key="users.list")
    view_permission = AdminPermission.objects.get(key="users.view")
    AdminRolePermission.objects.bulk_create(
        [
            AdminRolePermission(role=role, permission=list_permission),
            AdminRolePermission(role=role, permission=view_permission),
        ]
    )
    profile = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="客户经理",
        password=PASSWORD,
        role_id=role.id,
        request_id=uuid.uuid4(),
    )
    visible = User.objects.create_user(phone="13800138000", nickname="可见", password=PASSWORD)
    hidden = User.objects.create_user(phone="13600136000", nickname="隐藏", password=PASSWORD)
    CustomerAssignment.objects.create(customer=visible, owner_admin=profile)

    client = APIClient()
    client.force_authenticate(profile.user)
    filtered = client.get("/api/v1/admin/users", {"phone": hidden.phone})

    assert filtered.status_code == 200
    assert filtered.json()["data"]["results"] == []
    assert client.get(f"/api/v1/admin/users/{hidden.id}").status_code == 404
    assert client.get(f"/api/v1/admin/users/{visible.id}").status_code == 200


@pytest.mark.django_db
def test_admin_api_never_returns_complete_phone_or_password_fields():
    actor = create_superuser()
    client = APIClient()
    client.force_authenticate(actor)

    response = client.get("/api/v1/admin/me")
    serialized = response.json()

    assert response.status_code == 200
    assert actor.phone not in str(serialized)
    assert "phone_masked" in serialized["data"]
    assert "password" not in str(serialized).lower()
    assert "session" not in str(serialized).lower()


@pytest.mark.django_db
def test_catalog_drift_reports_unknown_key_without_deleting_it(capsys):
    unknown = AdminPermission.objects.create(
        key="unknown.permission",
        name="未知权限",
        module="unknown",
        permission_type=AdminPermission.PermissionType.ACTION,
        status=AdminPermission.Status.INACTIVE,
    )

    call_command("sync_admin_rbac")

    assert "catalog drift" in capsys.readouterr().out
    assert AdminPermission.objects.filter(pk=unknown.pk).exists()
