import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.management import call_command
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminRole, CustomerAssignment
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.registration_links import (
    InvalidRegistrationReference,
    issue_registration_ref,
    resolve_registration_admin,
)
from apps.admin_rbac.scopes import scoped_customers
from apps.admin_rbac.services import assign_customer, change_admin_status, create_admin
from apps.users.models import User
from apps.users.services import create_registered_user
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def seed_standard_plans():
    call_command("sync_standard_plans", "--apply", verbosity=0)


def create_hierarchy():
    root = User.objects.create_superuser(
        phone="13900000100", nickname="平台管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="代理角色", data_scope=AdminRole.DataScope.ALL)

    def make_admin(phone, nickname):
        return create_admin(
            actor_id=root.pk,
            phone=phone,
            nickname=nickname,
            password=PASSWORD,
            role_id=role.pk,
            request_id=uuid.uuid4(),
        )

    return root, make_admin("13700000101", "代理甲"), make_admin("13700000102", "代理乙")


def register_user(phone, nickname, registration_ref):
    return create_registered_user(
        phone=phone,
        nickname=nickname,
        password=PASSWORD,
        registration_ref=registration_ref,
    )


@pytest.mark.django_db
def test_distinct_admin_links_create_deterministic_direct_ownership_and_isolation():
    root, first, second = create_hierarchy()
    first_ref = issue_registration_ref(first)
    second_ref = issue_registration_ref(second)
    assert first_ref != second_ref
    assert first.registration_channel_key != second.registration_channel_key

    first_user = register_user("+8613800000101", "甲客户", first_ref)
    second_user = register_user("+8613800000102", "乙客户", second_ref)

    assert first_user.customer_assignment.owner_admin == first
    assert second_user.customer_assignment.owner_admin == second
    first_visible = set(
        scoped_customers(first.user, resolve_admin_context(first.user)).values_list("pk", flat=True)
    )
    second_visible = set(
        scoped_customers(second.user, resolve_admin_context(second.user)).values_list(
            "pk", flat=True
        )
    )
    root_visible = set(
        scoped_customers(root, resolve_admin_context(root)).values_list("pk", flat=True)
    )
    assert first_visible == {first_user.pk}
    assert second_visible == {second_user.pk}
    assert {first_user.pk, second_user.pk} <= root_visible


@pytest.mark.django_db
def test_missing_invalid_tampered_expired_and_disabled_refs_fail_closed(settings):
    root, first, second = create_hierarchy()
    valid_ref = issue_registration_ref(first)
    tampered_ref = f"{valid_ref[:-1]}{'A' if valid_ref[-1] != 'A' else 'B'}"

    for invalid_ref in ("", "not-a-signed-channel", tampered_ref):
        with pytest.raises(InvalidRegistrationReference):
            resolve_registration_admin(invalid_ref)

    settings.REGISTRATION_REF_MAX_AGE_SECONDS = 10
    with patch("django.core.signing.time.time", return_value=1000):
        expiring_ref = issue_registration_ref(first)
    with patch("django.core.signing.time.time", return_value=1011):
        with pytest.raises(InvalidRegistrationReference):
            resolve_registration_admin(expiring_ref)

    disabled_ref = issue_registration_ref(second)
    change_admin_status(
        actor_id=root.pk,
        profile_id=second.pk,
        action="disable",
        expected_version=second.version,
        request_id=uuid.uuid4(),
    )
    with pytest.raises(InvalidRegistrationReference):
        resolve_registration_admin(disabled_ref)


@pytest.mark.django_db
def test_only_super_admin_can_read_admin_registration_link():
    root, first, second = create_hierarchy()
    root_client = authenticate_admin_client(APIClient(), root)
    response = root_client.get(f"/api/v1/admin/admins/{first.pk}/registration-link")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["registration_path"].startswith("/register?ref=")
    assert data["channel_name"] == "代理甲"
    assert data["usable"] is True
    assert str(first.pk) not in data["registration_path"]
    returned_ref = parse_qs(urlparse(data["registration_path"]).query)["ref"][0]
    assert resolve_registration_admin(returned_ref) == first

    admin_client = authenticate_admin_client(APIClient(), second.user)
    assert admin_client.get(f"/api/v1/admin/admins/{first.pk}/registration-link").status_code == 403

    customer = register_user("+8613800000103", "普通用户", issue_registration_ref(first))
    user_client = APIClient()
    user_client.force_authenticate(customer)
    assert user_client.get(f"/api/v1/admin/admins/{first.pk}/registration-link").status_code == 403


@pytest.mark.django_db
def test_registration_api_allows_optional_or_invalid_ref_and_rejects_admin_override(
    monkeypatch,
):
    _, first, second = create_hierarchy()
    first_ref = issue_registration_ref(first)
    consumed = 0

    def consume(*args, **kwargs):
        nonlocal consumed
        consumed += 1
        return True

    monkeypatch.setattr("apps.users.views.verify_and_consume", consume)

    def submit(phone, **extra):
        client = APIClient(enforce_csrf_checks=True)
        csrf = client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]
        return client.post(
            "/api/v1/auth/register",
            {
                "phone": phone,
                "nickname": "渠道客户",
                "sms_code": "438921",
                "password": PASSWORD,
                **extra,
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )

    public = submit("13800000110")
    assert public.status_code == 201
    public_user = User.objects.get(phone="+8613800000110")
    assert public_user.customer_assignment.owner_admin is None
    assert public.json()["data"]["home_route"] == "/workspace"

    invalid = submit("13800000111", ref="invalid")
    assert invalid.status_code == 201
    invalid_ref_user = User.objects.get(phone="+8613800000111")
    assert invalid_ref_user.customer_assignment.owner_admin is None

    assert submit("13800000112", ref=first_ref, admin_id=str(second.pk)).status_code == 422

    created = submit("13800000113", ref=first_ref)
    assert created.status_code == 201
    user = User.objects.get(phone="+8613800000113")
    assert user.customer_assignment.owner_admin == first
    assert consumed == 3


@pytest.mark.django_db
def test_admin_cannot_change_customer_owner_but_super_admin_can():
    root, first, second = create_hierarchy()
    customer = register_user("+8613800000120", "固定归属客户", issue_registration_ref(first))
    assignment = CustomerAssignment.objects.get(customer=customer)

    with pytest.raises(PermissionDenied):
        assign_customer(
            actor=first.user,
            context=resolve_admin_context(first.user),
            customer=customer,
            owner_admin_id=second.pk,
            expected_version=assignment.version,
            reason="越权变更",
            request_id=uuid.uuid4(),
        )

    independent = assign_customer(
        actor=root,
        context=resolve_admin_context(root),
        customer=customer,
        owner_admin_id=None,
        expected_version=assignment.version,
        reason="解除管理员关联",
        request_id=uuid.uuid4(),
    )
    assert independent.owner_admin is None
    assert customer.pk not in set(
        scoped_customers(first.user, resolve_admin_context(first.user)).values_list("pk", flat=True)
    )

    changed = assign_customer(
        actor=root,
        context=resolve_admin_context(root),
        customer=customer,
        owner_admin_id=second.pk,
        expected_version=independent.version,
        reason="平台重新分配",
        request_id=uuid.uuid4(),
    )
    assert changed.owner_admin == second


@pytest.mark.django_db
def test_super_admin_assignment_api_can_release_user_to_independent_status():
    root, first, _ = create_hierarchy()
    customer = register_user("+8613800000121", "待解除归属客户", issue_registration_ref(first))
    assignment = CustomerAssignment.objects.get(customer=customer)
    client = authenticate_admin_client(APIClient(), root, step_up=True)

    response = client.put(
        f"/api/v1/admin/users/{customer.pk}/assignment",
        {
            "owner_admin_id": None,
            "expected_version": assignment.version,
            "reason": "转为独立用户",
            "confirmed": True,
            "current_password": PASSWORD,
        },
        format="json",
    )

    assert response.status_code == 200
    assignment.refresh_from_db()
    assert assignment.owner_admin is None
    assert response.json()["data"]["owner_admin_id"] is None
