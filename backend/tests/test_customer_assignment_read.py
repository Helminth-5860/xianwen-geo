import uuid

import pytest
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminRole, CustomerAssignment
from apps.admin_rbac.services import create_admin
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.mark.django_db
def test_customer_assignment_get_returns_current_owner_with_masked_phone_only():
    actor = User.objects.create_superuser(
        phone="13900139000", nickname="超级管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="客户经理", data_scope=AdminRole.DataScope.ALL)
    owner = create_admin(
        actor_id=actor.pk,
        phone="13700137000",
        nickname="负责人",
        password=PASSWORD,
        role_id=role.pk,
        request_id=uuid.uuid4(),
    )
    customer = User.objects.create_user(phone="13800138000", nickname="客户", password=PASSWORD)
    assignment = CustomerAssignment.objects.create(
        customer=customer,
        owner_admin=owner,
        assigned_by=actor,
    )

    response = authenticate_admin_client(APIClient(), actor).get(
        f"/api/v1/admin/users/{customer.id}/assignment"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "id": str(assignment.id),
        "customer_id": str(customer.id),
        "owner_admin_id": str(owner.id),
        "owner_nickname": "负责人",
        "owner_phone_masked": "+86 137****7000",
        "version": 1,
        "assigned_at": data["assigned_at"],
    }
    serialized = str(response.json())
    assert "13700137000" not in serialized
    assert "13800138000" not in serialized


@pytest.mark.django_db
def test_customer_assignment_get_fails_closed_when_legacy_user_is_unassigned():
    actor = User.objects.create_superuser(
        phone="13900139000", nickname="超级管理员", password=PASSWORD
    )
    customer = User.objects.create_user(phone="13800138000", nickname="客户", password=PASSWORD)

    response = authenticate_admin_client(APIClient(), actor).get(
        f"/api/v1/admin/users/{customer.id}/assignment"
    )

    assert response.status_code == 404
