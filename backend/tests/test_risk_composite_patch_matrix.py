import uuid

import pytest
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminRole
from apps.admin_rbac.services import create_admin
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


def superuser(phone):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def client(user):
    return authenticate_admin_client(APIClient(), user)


@pytest.mark.django_db
def test_admin_and_role_ordinary_profile_fields_still_update():
    actor = superuser("13900139000")
    role = AdminRole.objects.create(name="原角色", data_scope=AdminRole.DataScope.ALL)
    target = create_admin(
        actor_id=actor.pk,
        phone="13700137000",
        nickname="原昵称",
        password=PASSWORD,
        role_id=role.pk,
        request_id=uuid.uuid4(),
    )
    api = client(actor)

    admin_response = api.patch(
        f"/api/v1/admin/admins/{target.id}",
        {"expected_version": target.version, "nickname": "新昵称"},
        format="json",
    )
    assert admin_response.status_code == 200
    target.refresh_from_db()
    role.refresh_from_db()
    role_response = api.patch(
        f"/api/v1/admin/roles/{role.id}",
        {
            "expected_version": role.version,
            "name": "新角色",
            "description": "仅修改普通描述",
        },
        format="json",
    )
    assert role_response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"role_id": str(uuid.uuid4())},
        {"admin_status": "disabled"},
        {"is_staff": False},
        {"is_superuser": True},
        {"require_sms_2fa": True},
        {"ip_allowlist_enabled": True},
        {"security_version": 99},
        {"security": {"require_sms_2fa": True}},
        {"roleId": str(uuid.uuid4())},
        {"nickname": "不应更新", "admin_status": "disabled"},
    ],
)
def test_admin_composite_patch_rejects_high_risk_nested_alias_and_mixed_fields(payload):
    actor = superuser("13900139000")
    role = AdminRole.objects.create(name="角色", data_scope=AdminRole.DataScope.ALL)
    target = create_admin(
        actor_id=actor.pk,
        phone="13700137000",
        nickname="原昵称",
        password=PASSWORD,
        role_id=role.pk,
        request_id=uuid.uuid4(),
    )
    before = (
        target.user.nickname,
        target.role_id,
        target.admin_status,
        target.user.is_staff,
        target.user.is_superuser,
        target.version,
    )

    response = client(actor).patch(
        f"/api/v1/admin/admins/{target.id}",
        {"expected_version": target.version, **payload},
        format="json",
    )

    assert response.status_code == 422
    target.refresh_from_db()
    target.user.refresh_from_db()
    assert (
        target.user.nickname,
        target.role_id,
        target.admin_status,
        target.user.is_staff,
        target.user.is_superuser,
        target.version,
    ) == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"permission_keys": ["users.list"]},
        {"data_scope": "all"},
        {"status": "inactive"},
        {"require_sms_2fa": True},
        {"ip_allowlist_enabled": True},
        {"security_version": 99},
        {"ip_allowlist": [{"network_cidr": "203.0.113.0/24"}]},
        {"security": {"require_sms_2fa": True}},
        {"permissionKeys": ["users.list"]},
        {"name": "不应更新", "permission_keys": ["users.list"]},
    ],
)
def test_role_composite_patch_rejects_high_risk_nested_alias_and_mixed_fields(payload):
    actor = superuser("13900139000")
    role = AdminRole.objects.create(name="原角色", data_scope=AdminRole.DataScope.OWN)
    before = (
        role.name,
        role.description,
        role.data_scope,
        role.status,
        role.security_version,
        role.version,
    )

    response = client(actor).patch(
        f"/api/v1/admin/roles/{role.id}",
        {"expected_version": role.version, **payload},
        format="json",
    )

    assert response.status_code == 422
    role.refresh_from_db()
    assert (
        role.name,
        role.description,
        role.data_scope,
        role.status,
        role.security_version,
        role.version,
    ) == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"owner_admin": str(uuid.uuid4())},
        {"owner_admin_id": str(uuid.uuid4())},
        {"account_status": "frozen"},
        {"assignment": {"owner_admin_id": str(uuid.uuid4())}},
        {"ownerAdmin": str(uuid.uuid4())},
        {"nickname": "混合字段", "account_status": "frozen"},
    ],
)
def test_customer_detail_has_no_generic_patch_bypass(payload):
    actor = superuser("13900139000")
    customer = User.objects.create_user(phone="13800138000", nickname="客户", password=PASSWORD)
    before = (
        customer.nickname,
        customer.account_status,
        customer.status_version,
    )

    response = client(actor).patch(f"/api/v1/admin/users/{customer.id}", payload, format="json")

    assert response.status_code == 405
    customer.refresh_from_db()
    assert (
        customer.nickname,
        customer.account_status,
        customer.status_version,
    ) == before
