import hashlib
import uuid

import pytest
from django.core.management import call_command
from django.db import transaction
from rest_framework.test import APIClient

from apps.geo.models import SubjectCompetitor
from apps.subjects.models import Subject, SubjectName, SubjectType, SubjectVersion
from apps.subjects.schema_snapshots import (
    build_schema_snapshot,
    materialize_defaults,
    values_digest,
)
from apps.users.models import Tenant, User

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def subject_catalog():
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def _make_subject(*, tenant_key: str, name: str, official_url: str):
    tenant = Tenant.objects.create(
        key=tenant_key,
        display_name=f"{name}租户",
        brand_name=name,
    )
    user = User.objects.create_user(
        phone=f"139{uuid.uuid4().int % 100000000:08d}",
        nickname=f"{name}用户",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
        tenant=tenant,
    )
    subject_type = SubjectType.objects.get(key="enterprise")
    snapshot, digest = build_schema_snapshot(subject_type)
    values = materialize_defaults(snapshot)
    values["name"] = name
    values["official_url"] = official_url
    subject = Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=Subject.Status.ACTIVE,
        draft_values=values,
        schema_version=subject_type.schema_version,
        schema_snapshot_format_version=1,
        schema_snapshot=snapshot,
        schema_digest=digest,
    )
    with transaction.atomic():
        version = SubjectVersion.objects.create(
            subject=subject,
            version_no=1,
            field_values=values,
            schema_version=subject.schema_version,
            schema_snapshot_format_version=1,
            schema_snapshot=snapshot,
            schema_digest=digest,
            field_values_digest=values_digest(values),
            semantic_digest=hashlib.sha256(f"competitor-{subject.pk}".encode()).hexdigest(),
            official_name=name,
            created_by=user,
        )
        SubjectName.objects.create(
            subject_version=version,
            role=SubjectName.Role.OFFICIAL_NAME,
            display_value=name,
            matching_value=name.casefold(),
            source_field_key="name",
        )
        subject.current_version = version
        subject.version += 1
        subject.save(update_fields=("current_version", "version", "updated_at"))
    return user, subject


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _list_path(subject):
    return f"/api/v1/subjects/{subject.pk}/competitors"


def _create(client, subject, name, website=""):
    return client.post(
        _list_path(subject),
        {"name": name, "website": website},
        format="json",
    )


def test_adds_first_second_and_third_competitor_and_persists_order():
    user, subject = _make_subject(
        tenant_key="competitor-limit",
        name="显问科技",
        official_url="https://xianwen.example.com",
    )
    client = _client(user)
    for index in range(1, 4):
        response = _create(
            client,
            subject,
            f"竞品{index}",
            f"https://competitor-{index}-example.com",
        )
        assert response.status_code == 201
        assert response.data["competitor"]["position"] == index

    listed = client.get(_list_path(subject))
    assert listed.status_code == 200
    assert listed.data["subject"]["name"] == "显问科技"
    assert listed.data["count"] == 3
    assert listed.data["max_count"] == 3
    assert [item["name"] for item in listed.data["items"]] == ["竞品1", "竞品2", "竞品3"]
    assert SubjectCompetitor.objects.filter(status="active").count() == 3


def test_fourth_competitor_is_rejected_by_backend():
    user, subject = _make_subject(
        tenant_key="competitor-fourth",
        name="甲公司",
        official_url="https://alpha.example.com",
    )
    client = _client(user)
    for index in range(1, 4):
        assert _create(client, subject, f"竞品{index}").status_code == 201
    response = _create(client, subject, "第四家")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "COMPETITOR_LIMIT_REACHED"
    assert SubjectCompetitor.objects.filter(status="active").count() == 3


def test_duplicate_normalized_name_is_rejected():
    user, subject = _make_subject(
        tenant_key="competitor-name-duplicate",
        name="甲公司",
        official_url="https://alpha.example.com",
    )
    client = _client(user)
    assert _create(client, subject, "Beta  Brand").status_code == 201
    response = _create(client, subject, "ＢＥＴＡ brand")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "COMPETITOR_DUPLICATE"


def test_duplicate_root_domain_is_rejected():
    user, subject = _make_subject(
        tenant_key="competitor-domain-duplicate",
        name="甲公司",
        official_url="https://alpha.example.com",
    )
    client = _client(user)
    first = _create(client, subject, "乙公司", "www.beta-example.com")
    assert first.status_code == 201
    response = _create(client, subject, "乙公司集团", "https://news.beta-example.com/about")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "COMPETITOR_DUPLICATE"


@pytest.mark.parametrize(
    ("name", "website"),
    ((" 显问科技 ", ""), ("其他名称", "https://www.xianwen.example.com/about")),
)
def test_subject_cannot_be_added_as_its_own_competitor(name, website):
    user, subject = _make_subject(
        tenant_key=f"competitor-self-{uuid.uuid4().hex[:8]}",
        name="显问科技",
        official_url="https://xianwen.example.com",
    )
    response = _create(_client(user), subject, name, website)
    assert response.status_code == 409
    assert response.data["error"]["code"] == "COMPETITOR_IS_SUBJECT"


def test_subject_alias_cannot_be_added_as_competitor():
    user, subject = _make_subject(
        tenant_key="competitor-self-alias",
        name="显问科技",
        official_url="https://xianwen.example.com",
    )
    SubjectName.objects.create(
        subject_version=subject.current_version,
        role=SubjectName.Role.ALIAS,
        display_value="显问 GEO",
        matching_value="显问 geo",
        source_field_key="alias",
    )
    response = _create(_client(user), subject, "显问 ＧＥＯ")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "COMPETITOR_IS_SUBJECT"


def test_tenant_and_owner_scope_fail_closed():
    owner, subject = _make_subject(
        tenant_key="competitor-tenant-owner",
        name="甲公司",
        official_url="https://alpha.example.com",
    )
    outsider, _other_subject = _make_subject(
        tenant_key="competitor-tenant-outsider",
        name="乙公司",
        official_url="https://beta.example.com",
    )
    assert _create(_client(owner), subject, "核心竞品").status_code == 201

    response = _client(outsider).get(_list_path(subject))
    assert response.status_code == 404
    assert response.data["error"]["code"] == "RESOURCE_NOT_FOUND"

    same_tenant_outsider = User.objects.create_user(
        phone=f"137{uuid.uuid4().int % 100000000:08d}",
        nickname="同租户其他用户",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
        tenant=owner.tenant,
    )
    assert _client(same_tenant_outsider).get(_list_path(subject)).status_code == 404


def test_subjects_do_not_share_competitors_even_for_same_user():
    user, first_subject = _make_subject(
        tenant_key="competitor-subject-scope",
        name="甲公司",
        official_url="https://alpha.example.com",
    )
    subject_type = first_subject.subject_type
    snapshot, digest = build_schema_snapshot(subject_type)
    values = materialize_defaults(snapshot)
    values["name"] = "甲公司第二品牌"
    second = Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=Subject.Status.ACTIVE,
        draft_values=values,
        schema_version=subject_type.schema_version,
        schema_snapshot_format_version=1,
        schema_snapshot=snapshot,
        schema_digest=digest,
    )
    version = SubjectVersion.objects.create(
        subject=second,
        version_no=1,
        field_values=values,
        schema_version=second.schema_version,
        schema_snapshot_format_version=1,
        schema_snapshot=snapshot,
        schema_digest=digest,
        field_values_digest=values_digest(values),
        semantic_digest=hashlib.sha256(f"competitor-{second.pk}".encode()).hexdigest(),
        official_name="甲公司第二品牌",
        created_by=user,
    )
    second.current_version = version
    second.save(update_fields=("current_version", "updated_at"))

    client = _client(user)
    created = _create(client, first_subject, "核心竞品")
    assert created.status_code == 201
    listed = client.get(_list_path(second))
    assert listed.status_code == 200
    assert listed.data["count"] == 0
    competitor_id = created.data["competitor"]["id"]
    wrong_subject_path = f"{_list_path(second)}/{competitor_id}"
    assert (
        client.patch(
            wrong_subject_path,
            {"name": "越权修改", "expected_version": 1},
            format="json",
        ).status_code
        == 404
    )
    assert client.delete(wrong_subject_path).status_code == 404
    assert SubjectCompetitor.objects.get(pk=competitor_id).status == "active"


def test_edit_updates_name_and_website_and_checks_version():
    user, subject = _make_subject(
        tenant_key="competitor-edit",
        name="甲公司",
        official_url="https://alpha.example.com",
    )
    client = _client(user)
    created = _create(client, subject, "旧名称", "old-example.com")
    item = created.data["competitor"]
    path = f"{_list_path(subject)}/{item['id']}"
    updated = client.patch(
        path,
        {"name": "新名称", "website": "https://www.new-example.com/", "expected_version": 1},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.data["competitor"]["name"] == "新名称"
    assert updated.data["competitor"]["domain"] == "new-example.com"
    assert updated.data["competitor"]["version"] == 2

    name_only = client.patch(
        path,
        {"name": "只改名称", "expected_version": 2},
        format="json",
    )
    assert name_only.status_code == 200
    assert name_only.data["competitor"]["name"] == "只改名称"
    assert name_only.data["competitor"]["domain"] == "new-example.com"

    website_only = client.patch(
        path,
        {"website": "final-example.com", "expected_version": 3},
        format="json",
    )
    assert website_only.status_code == 200
    assert website_only.data["competitor"]["name"] == "只改名称"
    assert website_only.data["competitor"]["domain"] == "final-example.com"

    stale = client.patch(
        path,
        {"name": "再次修改", "expected_version": 1},
        format="json",
    )
    assert stale.status_code == 409
    assert stale.data["error"]["code"] == "COMPETITOR_VERSION_CONFLICT"


def test_remove_is_soft_delete_compacts_positions_and_allows_replacement():
    user, subject = _make_subject(
        tenant_key="competitor-remove",
        name="甲公司",
        official_url="https://alpha.example.com",
    )
    client = _client(user)
    items = [
        _create(client, subject, name).data["competitor"] for name in ("竞品一", "竞品二", "竞品三")
    ]
    removed = client.delete(f"{_list_path(subject)}/{items[1]['id']}")
    assert removed.status_code == 204

    removed_row = SubjectCompetitor.objects.get(pk=items[1]["id"])
    assert removed_row.status == SubjectCompetitor.Status.REMOVED
    assert removed_row.removed_at is not None
    listed = client.get(_list_path(subject))
    assert [item["name"] for item in listed.data["items"]] == ["竞品一", "竞品三"]
    assert [item["position"] for item in listed.data["items"]] == [1, 2]

    replacement = _create(client, subject, "竞品二")
    assert replacement.status_code == 201
    assert replacement.data["competitor"]["position"] == 3


def test_anonymous_requests_are_rejected():
    _user, subject = _make_subject(
        tenant_key="competitor-anonymous",
        name="甲公司",
        official_url="https://alpha.example.com",
    )
    assert APIClient().get(_list_path(subject)).status_code in {401, 403}


@pytest.mark.parametrize(
    "website",
    (
        "javascript:alert(1)",
        "https://user:password@example.com",
        "https://example.com:abc",
        "localhost",
        "https://exa mple.com",
        "https://-bad-.com",
        f"https://{'a' * 128}.{'b' * 128}",
        f"{'a' * 490}.com",
    ),
)
def test_invalid_websites_return_safe_validation_error(website):
    user, subject = _make_subject(
        tenant_key=f"competitor-invalid-url-{uuid.uuid4().hex[:8]}",
        name="甲公司",
        official_url="https://alpha.example.com",
    )
    response = _create(_client(user), subject, "乙公司", website)
    assert response.status_code == 422
    assert response.data["error"]["code"] == "COMPETITOR_VALUES_INVALID"


def test_historical_subject_url_with_invalid_port_does_not_break_competitor_addition():
    user, subject = _make_subject(
        tenant_key=f"competitor-historical-url-{uuid.uuid4().hex[:8]}",
        name="甲公司",
        official_url="https://alpha.example.com:invalid",
    )

    response = _create(_client(user), subject, "乙公司", "https://beta.example.com")

    assert response.status_code == 201
    assert response.data["competitor"]["domain"] == "example.com"
