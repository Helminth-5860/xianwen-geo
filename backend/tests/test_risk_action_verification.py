import uuid

import pytest
from rest_framework.test import APIClient

from apps.admin_rbac.models import AuditEvent, RiskAction, RiskPolicy
from apps.admin_rbac.risk_catalog import RISK_ACTION_CATALOG
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


def superuser(phone):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def admin_client(user):
    return authenticate_admin_client(APIClient(), user)


@pytest.mark.django_db
def test_runtime_catalog_exposes_only_confirmation_or_password_modes():
    assert {mode for item in RISK_ACTION_CATALOG for mode in item.supported_modes} <= {
        "confirm",
        "password",
    }
    assert all("two_person" not in action.supported_modes for action in RiskAction.objects.all())
    assert not RiskPolicy.objects.filter(current_mode="two_person").exists()


@pytest.mark.django_db
def test_one_superuser_can_execute_password_action_without_creating_a_queue_item():
    requester = superuser("13900139000")
    target = superuser("13600136000")
    response = admin_client(requester).post(
        f"/api/v1/admin/admins/{target.admin_profile.id}/disable",
        {
            "expected_version": target.admin_profile.version,
            "current_password": PASSWORD,
            "confirmed": True,
        },
        format="json",
    )

    assert response.status_code == 200
    event = AuditEvent.objects.get(action_key="admin.disable", outcome="executed")
    assert event.actor_id == requester.id


@pytest.mark.django_db
def test_retired_workflow_endpoints_fail_closed():
    client = admin_client(superuser("13900139000"))
    request_id = uuid.uuid4()

    assert client.get("/api/v1/admin/approvals").status_code == 404
    for suffix in ("", "/approve", "/reject", "/cancel"):
        assert client.post(f"/api/v1/admin/approvals/{request_id}{suffix}", {}).status_code == 404
