import hashlib
import json
import uuid
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db import transaction
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminProfile, AdminRole, CustomerAssignment
from apps.media_inquiries.catalog import (
    clear_paid_media_catalog_cache,
    paid_media_catalog,
)
from apps.media_inquiries.models import PaidMediaInquiry
from apps.subjects.models import Subject, SubjectName, SubjectType, SubjectVersion
from apps.subjects.schema_snapshots import (
    build_schema_snapshot,
    materialize_defaults,
    values_digest,
)
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def subject_catalog():
    call_command("sync_subject_catalog", "--apply", verbosity=0)


@pytest.fixture
def media_catalog(tmp_path, settings):
    payload = {
        "version": 7,
        "currency": "CNY",
        "items": [
            {
                "id": "media-one",
                "name": "人民媒体",
                "url": "https://news.example.cn/article/1",
                "domain": "news.example.cn",
                "logo_path": "/paid-media-logos/one.png",
                "price_cents": 12345,
            },
            {
                "id": "media-two",
                "name": "广州商业观察",
                "url": "https://business.example.com/guangzhou",
                "domain": "business.example.com",
                "logo_path": None,
                "price_cents": 5500,
            },
            {
                "id": "media-no-link",
                "name": "待核实媒体",
                "url": None,
                "domain": "",
                "logo_path": None,
                "price_cents": 800,
            },
        ],
    }
    path = tmp_path / "paid-media-catalog.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    settings.PAID_MEDIA_CATALOG_PATH = str(path)
    clear_paid_media_catalog_cache()
    yield payload
    clear_paid_media_catalog_cache()


def _make_subject(*, phone=None, name="示例企业"):
    user = User.objects.create_user(
        phone=phone or f"139{uuid.uuid4().int % 100000000:08d}",
        nickname="媒体服务用户",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
    )
    subject_type = SubjectType.objects.get(key="enterprise")
    snapshot, digest = build_schema_snapshot(subject_type)
    values = materialize_defaults(snapshot)
    values["name"] = name
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
        subject_version = SubjectVersion.objects.create(
            subject=subject,
            version_no=1,
            field_values=values,
            schema_version=subject.schema_version,
            schema_snapshot_format_version=1,
            schema_snapshot=snapshot,
            schema_digest=digest,
            field_values_digest=values_digest(values),
            semantic_digest=hashlib.sha256(f"media-{subject.pk}".encode()).hexdigest(),
            official_name=name,
            created_by=user,
        )
        SubjectName.objects.create(
            subject_version=subject_version,
            role=SubjectName.Role.OFFICIAL_NAME,
            display_value=name,
            matching_value=name.casefold(),
            source_field_key="name",
        )
        subject.current_version = subject_version
        subject.version += 1
        subject.save(update_fields=("current_version", "version", "updated_at"))
    return user, subject


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _create(client, subject, *, media_ids=None, key="paid-media-request-1"):
    return client.post(
        f"/api/v1/subjects/{subject.pk}/paid-media-inquiries",
        {"media_ids": media_ids or ["media-one", "media-two"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_catalog_search_is_authenticated_paginated_and_supports_missing_links(media_catalog):
    user, _subject = _make_subject()
    response = _client(user).get(
        "/api/v1/paid-media-catalog", {"search": "example.com", "page_size": 1}
    )
    assert response.status_code == 200
    assert response.data["pagination"] == {
        "page": 1,
        "page_size": 1,
        "count": 1,
        "total_pages": 1,
    }
    assert response.data["items"][0]["id"] == "media-two"

    missing_link = _client(user).get("/api/v1/paid-media-catalog", {"search": "待核实"})
    assert missing_link.status_code == 200
    assert missing_link.data["items"][0]["url"] is None
    assert missing_link.data["items"][0]["domain"] is None
    assert APIClient().get("/api/v1/paid-media-catalog").status_code in {401, 403}


def test_inquiry_uses_trusted_catalog_price_and_is_idempotent(media_catalog):
    user, subject = _make_subject()
    client = _client(user)
    created = _create(client, subject)
    assert created.status_code == 201
    inquiry = created.data["inquiry"]
    assert inquiry["subject_id"] == str(subject.pk)
    assert inquiry["subject_name"] == "示例企业"
    assert inquiry["item_count"] == 2
    assert inquiry["total_price"] == "178.45"
    assert inquiry["selected_media"][0]["price_cents"] == 12345
    assert inquiry["selected_media"][0]["price"] == "123.45"

    replay = _create(client, subject)
    assert replay.status_code == 200
    assert replay.data["inquiry"]["id"] == inquiry["id"]
    assert PaidMediaInquiry.objects.count() == 1

    conflict = _create(client, subject, media_ids=["media-one"], key="paid-media-request-1")
    assert conflict.status_code == 409
    assert conflict.data["error"]["message"] == "请求内容已发生变化，请刷新页面后重试。"


def test_inquiry_rejects_client_price_and_stale_catalog_ids(media_catalog):
    user, subject = _make_subject()
    client = _client(user)
    manipulated = client.post(
        f"/api/v1/subjects/{subject.pk}/paid-media-inquiries",
        {"media_ids": ["media-one"], "total_price": "0.01"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="manipulated-price",
    )
    assert manipulated.status_code == 422
    assert PaidMediaInquiry.objects.count() == 0

    stale = _create(
        client,
        subject,
        media_ids=["media-does-not-exist"],
        key="stale-selection",
    )
    assert stale.status_code == 422
    assert stale.data["error"]["message"] == "所选媒体信息已发生变化，请刷新目录后重新选择。"


def test_user_list_and_cancel_are_subject_and_owner_scoped(media_catalog):
    owner, subject = _make_subject(name="甲企业")
    other, other_subject = _make_subject(name="乙企业")
    created = _create(_client(owner), subject)
    inquiry_id = created.data["inquiry"]["id"]

    own_list = _client(owner).get(f"/api/v1/subjects/{subject.pk}/paid-media-inquiries")
    assert own_list.status_code == 200
    assert own_list.data["pagination"]["count"] == 1
    assert own_list.data["items"][0]["id"] == inquiry_id

    assert (
        _client(other).get(f"/api/v1/subjects/{subject.pk}/paid-media-inquiries").status_code == 404
    )
    assert (
        _client(other)
        .delete(f"/api/v1/subjects/{other_subject.pk}/paid-media-inquiries/{inquiry_id}")
        .status_code
        == 404
    )
    cancelled = _client(owner).delete(f"/api/v1/paid-media-inquiries/{inquiry_id}")
    assert cancelled.status_code == 200
    assert cancelled.data["status"] == "cancelled"
    repeated = _client(owner).delete(f"/api/v1/paid-media-inquiries/{inquiry_id}")
    assert repeated.status_code == 409


def test_admin_can_list_view_and_update_with_version_check(media_catalog):
    user, subject = _make_subject()
    created = _create(_client(user), subject)
    inquiry_id = created.data["inquiry"]["id"]
    admin_user = User.objects.create_superuser(
        phone="13900139091",
        nickname="媒体服务管理员",
        password="Correct-Horse-Battery-2026!",
    )
    AdminProfile.objects.get_or_create(user=admin_user)
    admin = authenticate_admin_client(APIClient(), admin_user)

    listed = admin.get("/api/v1/admin/paid-media-inquiries")
    assert listed.status_code == 200
    assert listed.data["pagination"]["count"] == 1
    row = listed.data["items"][0]
    assert row["user"]["phone"] == user.phone
    assert row["subject"]["id"] == str(subject.pk)

    detail = admin.get(f"/api/v1/admin/paid-media-inquiries/{inquiry_id}")
    assert detail.status_code == 200
    changed = admin.patch(
        f"/api/v1/admin/paid-media-inquiries/{inquiry_id}",
        {"status": "contacted", "expected_version": detail.data["version"]},
        format="json",
    )
    assert changed.status_code == 200
    assert changed.data["status"] == "contacted"
    stale = admin.patch(
        f"/api/v1/admin/paid-media-inquiries/{inquiry_id}",
        {"status": "completed", "expected_version": detail.data["version"]},
        format="json",
    )
    assert stale.status_code == 409


def test_non_super_admin_only_sees_assigned_customers(media_catalog):
    assigned_user, assigned_subject = _make_subject(name="已分配企业")
    other_user, other_subject = _make_subject(name="其他企业")
    assigned_inquiry = _create(
        _client(assigned_user), assigned_subject, key="assigned-inquiry"
    ).data["inquiry"]
    other_inquiry = _create(_client(other_user), other_subject, key="other-inquiry").data["inquiry"]
    role = AdminRole.objects.create(
        name="媒体服务专员",
        description="处理已分配客户的媒体服务申请",
        status=AdminRole.Status.ACTIVE,
        data_scope=AdminRole.DataScope.OWN,
    )
    admin_user = User.objects.create_user(
        phone="13900139092",
        nickname="媒体服务专员",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
        is_staff=True,
    )
    profile = AdminProfile.objects.create(user=admin_user, role=role)
    CustomerAssignment.objects.create(
        customer=assigned_user,
        owner_admin=profile,
        assigned_by=admin_user,
    )
    admin = authenticate_admin_client(APIClient(), admin_user)

    listed = admin.get("/api/v1/admin/paid-media-inquiries")
    assert listed.status_code == 200
    assert listed.data["pagination"]["count"] == 1
    assert listed.data["items"][0]["id"] == assigned_inquiry["id"]
    assert admin.get(f"/api/v1/admin/paid-media-inquiries/{other_inquiry['id']}").status_code == 404


def test_repository_catalog_loads_all_items_and_null_links(settings, media_catalog):
    repository_catalog = Path(__file__).resolve().parents[2] / "config" / "paid-media-catalog.json"
    settings.PAID_MEDIA_CATALOG_PATH = str(repository_catalog)
    clear_paid_media_catalog_cache()
    catalog = paid_media_catalog()
    assert len(catalog.items) == 12465
    assert any(item.url is None and item.domain is None for item in catalog.items)
