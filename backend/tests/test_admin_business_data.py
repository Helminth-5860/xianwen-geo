import uuid

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.admin_rbac.business_data_views import RESOURCE_HANDLERS, RESOURCE_TYPES
from apps.admin_rbac.models import AdminRole
from apps.admin_rbac.services import create_admin
from apps.subjects.models import Subject, SubjectType
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def seed_admin_catalog(db):
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def make_superuser():
    return User.objects.create_superuser(
        phone="13900139000",
        nickname="超级管理员",
        password=PASSWORD,
    )


def make_subject_type():
    return SubjectType.objects.get(key="enterprise")


def make_subject(*, user, subject_type, name, index):
    return Subject.objects.create(
        user=user,
        tenant=user.tenant,
        subject_type=subject_type,
        status=Subject.Status.DRAFT,
        draft_values={},
        schema_version=1,
        schema_snapshot_format_version=1,
        schema_snapshot={},
        schema_digest=f"{index:064x}",
        bound_official_name=name,
    )


@pytest.mark.django_db
def test_business_data_subject_search_is_superuser_only_and_fixed_to_twenty_per_page():
    admin = make_superuser()
    customer = User.objects.create_user(
        phone="13800138000",
        nickname="排障客户",
        password=PASSWORD,
    )
    subject_type = make_subject_type()
    for index in range(21):
        make_subject(
            user=customer,
            subject_type=subject_type,
            name=f"显问排障企业 {index + 1:02d}",
            index=index + 1,
        )

    client = authenticate_admin_client(APIClient(), admin)
    response = client.get(
        "/api/v1/admin/business-data",
        {"resource": "subjects", "q": "显问排障企业", "page": 1},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["resource"] == "subjects"
    assert payload["page_size"] == 20
    assert payload["total"] == 21
    assert payload["total_pages"] == 2
    assert len(payload["items"]) == 20
    assert payload["items"][0]["user_name"] == "排障客户"
    assert payload["items"][0]["user_phone_masked"] == "+86 138****8000"
    assert "13800138000" not in str(payload)

    second_page = client.get(
        "/api/v1/admin/business-data",
        {"resource": "subjects", "q": str(customer.pk), "page": 2},
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["data"]["items"]) == 1


@pytest.mark.django_db
def test_business_data_rejects_ordinary_admin_even_with_valid_admin_session():
    superuser = make_superuser()
    role = AdminRole.objects.create(name="运营管理员", data_scope=AdminRole.DataScope.ALL)
    profile = create_admin(
        actor_id=superuser.pk,
        phone="13700137000",
        nickname="普通管理员",
        password=PASSWORD,
        role_id=role.pk,
        request_id=uuid.uuid4(),
    )

    response = authenticate_admin_client(APIClient(), profile.user).get(
        "/api/v1/admin/business-data",
        {"resource": "subjects"},
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_business_data_all_six_resource_queries_compile_and_validate_inputs():
    admin = make_superuser()
    client = authenticate_admin_client(APIClient(), admin)

    assert set(RESOURCE_HANDLERS) == set(RESOURCE_TYPES)
    for resource, (queryset_factory, _) in RESOURCE_HANDLERS.items():
        assert queryset_factory("no-match-probe").count() == 0, resource
        response = client.get(
            "/api/v1/admin/business-data",
            {"resource": resource, "q": "no-match-probe"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["items"] == []

    invalid_resource = client.get(
        "/api/v1/admin/business-data",
        {"resource": "unknown"},
    )
    assert invalid_resource.status_code == 422

    invalid_page = client.get(
        "/api/v1/admin/business-data",
        {"resource": "subjects", "page": 0},
    )
    assert invalid_page.status_code == 422
