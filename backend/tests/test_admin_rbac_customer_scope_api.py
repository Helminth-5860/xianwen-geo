import uuid
from dataclasses import dataclass

import pytest
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminPermission,
    AdminProfile,
    AdminRole,
    AdminRolePermission,
    CustomerAssignment,
)
from apps.admin_rbac.services import create_admin
from apps.users.models import User

PASSWORD = "Correct-Horse-Battery-2026!"


@dataclass
class ScopeFixture:
    own_client: APIClient
    role_client: APIClient
    all_client: APIClient
    own_admin: AdminProfile
    role_admin: AdminProfile
    role_owner: AdminProfile
    own_customer: User
    role_customer: User
    other_customer: User
    unassigned: User


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def scope_fixture():
    actor = User.objects.create_superuser(
        phone="13900139000", nickname="超级管理员", password=PASSWORD
    )
    own_role = AdminRole.objects.create(name="本人范围", data_scope=AdminRole.DataScope.OWN)
    shared_role = AdminRole.objects.create(name="角色范围", data_scope=AdminRole.DataScope.ROLE)
    other_role = AdminRole.objects.create(name="其他角色", data_scope=AdminRole.DataScope.OWN)
    all_role = AdminRole.objects.create(name="全部范围", data_scope=AdminRole.DataScope.ALL)
    permission_keys = [
        "users.list",
        "users.view",
        "users.history.view",
        "users.review",
        "users.freeze",
    ]
    permissions = list(AdminPermission.objects.filter(key__in=permission_keys))
    AdminRolePermission.objects.bulk_create(
        AdminRolePermission(role=role, permission=permission)
        for role in (own_role, shared_role, other_role, all_role)
        for permission in permissions
    )

    def admin(phone, nickname, role):
        return create_admin(
            actor_id=actor.id,
            phone=phone,
            nickname=nickname,
            password=PASSWORD,
            role_id=role.id,
            request_id=uuid.uuid4(),
        )

    own_admin = admin("13700137000", "本人管理员", own_role)
    role_admin = admin("13600136000", "角色管理员", shared_role)
    role_owner = admin("13500135000", "同角色负责人", shared_role)
    other_owner = admin("13400134000", "其他负责人", other_role)
    all_admin = admin("13300133000", "全部管理员", all_role)

    own_customer = User.objects.create_user(
        phone="13800138000", nickname="本人客户", password=PASSWORD
    )
    role_customer = User.objects.create_user(
        phone="13200132000", nickname="角色客户", password=PASSWORD
    )
    other_customer = User.objects.create_user(
        phone="13100131000", nickname="其他客户", password=PASSWORD
    )
    unassigned = User.objects.create_user(
        phone="13000130000", nickname="未分配客户", password=PASSWORD
    )
    CustomerAssignment.objects.create(customer=own_customer, owner_admin=own_admin)
    CustomerAssignment.objects.create(customer=role_customer, owner_admin=role_owner)
    CustomerAssignment.objects.create(customer=other_customer, owner_admin=other_owner)

    return ScopeFixture(
        own_client=client_for(own_admin.user),
        role_client=client_for(role_admin.user),
        all_client=client_for(all_admin.user),
        own_admin=own_admin,
        role_admin=role_admin,
        role_owner=role_owner,
        own_customer=own_customer,
        role_customer=role_customer,
        other_customer=other_customer,
        unassigned=unassigned,
    )


def result_ids(response):
    assert response.status_code == 200, response.json()
    return {item["id"] for item in response.json()["data"]["results"]}


@pytest.mark.django_db
def test_users_list_own_role_all_unassigned_and_exact_phone_scope(scope_fixture):
    data = scope_fixture
    own_ids = result_ids(data.own_client.get("/api/v1/admin/users"))
    role_ids = result_ids(data.role_client.get("/api/v1/admin/users"))
    all_ids = result_ids(data.all_client.get("/api/v1/admin/users"))

    assert own_ids == {str(data.own_customer.id)}
    assert role_ids == {str(data.role_customer.id)}
    assert {
        str(data.own_customer.id),
        str(data.role_customer.id),
        str(data.other_customer.id),
        str(data.unassigned.id),
    }.issubset(all_ids)
    filtered = data.own_client.get("/api/v1/admin/users", {"phone": data.role_customer.phone})
    assert result_ids(filtered) == set()


@pytest.mark.django_db
def test_user_detail_uses_same_scope_and_returns_404(scope_fixture):
    data = scope_fixture
    assert data.own_client.get(f"/api/v1/admin/users/{data.own_customer.id}").status_code == 200
    assert data.own_client.get(f"/api/v1/admin/users/{data.role_customer.id}").status_code == 404
    assert data.role_client.get(f"/api/v1/admin/users/{data.role_customer.id}").status_code == 200
    assert data.role_client.get(f"/api/v1/admin/users/{data.unassigned.id}").status_code == 404
    assert data.all_client.get(f"/api/v1/admin/users/{data.unassigned.id}").status_code == 200


@pytest.mark.django_db
def test_user_history_cannot_bypass_scoped_queryset(scope_fixture):
    data = scope_fixture
    assert (
        data.own_client.get(f"/api/v1/admin/users/{data.own_customer.id}/history").status_code
        == 200
    )
    assert (
        data.own_client.get(f"/api/v1/admin/users/{data.role_customer.id}/history").status_code
        == 404
    )


@pytest.mark.django_db
def test_user_review_uses_role_scope_and_separate_permission(scope_fixture):
    data = scope_fixture
    visible = data.role_client.post(
        f"/api/v1/admin/users/{data.role_customer.id}/review",
        {"decision": "approve"},
        format="json",
    )
    hidden = data.role_client.post(
        f"/api/v1/admin/users/{data.other_customer.id}/review",
        {"decision": "approve"},
        format="json",
    )
    assert visible.status_code == 200
    assert hidden.status_code == 404

    permission = AdminPermission.objects.get(key="users.review")
    AdminRolePermission.objects.filter(role=data.role_admin.role, permission=permission).delete()
    denied = data.role_client.post(
        f"/api/v1/admin/users/{data.role_customer.id}/review",
        {"decision": "approve"},
        format="json",
    )
    assert denied.status_code == 403


@pytest.mark.django_db
def test_user_freeze_uses_own_scope_and_freeze_permission(scope_fixture):
    data = scope_fixture
    hidden = data.own_client.post(
        f"/api/v1/admin/users/{data.role_customer.id}/freeze", {}, format="json"
    )
    visible = data.own_client.post(
        f"/api/v1/admin/users/{data.own_customer.id}/freeze", {}, format="json"
    )
    assert hidden.status_code == 404
    assert visible.status_code == 200

    permission = AdminPermission.objects.get(key="users.freeze")
    AdminRolePermission.objects.filter(role=data.own_admin.role, permission=permission).delete()
    denied = data.own_client.post(
        f"/api/v1/admin/users/{data.own_customer.id}/freeze", {}, format="json"
    )
    assert denied.status_code == 403


@pytest.mark.django_db
def test_user_unfreeze_uses_scope_and_never_exposes_unassigned_to_role(scope_fixture):
    data = scope_fixture
    data.role_customer.account_status = User.AccountStatus.FROZEN
    data.role_customer.is_active = False
    data.role_customer.save(update_fields=["account_status", "is_active", "updated_at"])
    visible = data.role_client.post(
        f"/api/v1/admin/users/{data.role_customer.id}/unfreeze", {}, format="json"
    )
    hidden = data.role_client.post(
        f"/api/v1/admin/users/{data.unassigned.id}/unfreeze", {}, format="json"
    )
    assert visible.status_code == 200
    assert hidden.status_code == 404
