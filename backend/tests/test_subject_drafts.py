import json
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.subjects.models import (
    Subject,
    SubjectBusinessProfile,
    SubjectContext,
    SubjectEvent,
    SubjectType,
    SubjectVersion,
)
from apps.subjects.schema_snapshots import snapshot_digest
from apps.subjects.subject_services import (
    SubjectEntitlementIntegrityError,
    SubjectLimitReconciliationRequired,
    subject_limit_preview,
)
from apps.users.models import User
from tests.subject_risk_helpers import install_empty_published_risk_catalog

PASSWORD = "Correct-Horse-Battery-2026!"
BUSINESS_ADDRESS = json.dumps(
    {
        "version": 1,
        "path": [
            {"code": "440000", "name": "广东省"},
            {"code": "440300", "name": "深圳市"},
            {"code": "440305", "name": "南山区"},
        ],
        "detail": "示例路 1 号",
    },
    ensure_ascii=False,
)
NATIONWIDE_SERVICE_REGIONS = json.dumps(
    {"version": 1, "nationwide": True, "areas": []},
    ensure_ascii=False,
)


@pytest.fixture(autouse=True)
def seed_subject_catalog():
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def make_user(*, phone="13800138000", account_status=User.AccountStatus.ACTIVE):
    return User.objects.create_user(
        phone=phone,
        nickname="Subject user",
        password=PASSWORD,
        account_status=account_status,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def data(response):
    return response.json()["data"]


def create_payload(subject_type, values=None):
    return {
        "subject_type_id": str(subject_type.pk),
        "expected_schema_version": subject_type.schema_version,
        "initial_values": values or {},
    }


def complete_values(created, **updates):
    return {
        **created["draft_values"],
        "target_audience": "企业客户",
        "service_regions": NATIONWIDE_SERVICE_REGIONS,
        **updates,
    }


@pytest.mark.django_db
def test_create_materializes_defaults_without_selecting_unsaved_subject():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    response = client_for(user).post(
        "/api/v1/subjects",
        create_payload(subject_type, {"name": "Example enterprise"}),
        format="json",
    )

    assert response.status_code == 201
    payload = data(response)
    subject = Subject.objects.get(pk=payload["id"])
    assert subject.draft_values["name"] == "Example enterprise"
    assert set(subject.draft_values) == {
        field["field_key"] for field in subject.schema_snapshot["fields"]
    }
    assert subject.schema_snapshot_format_version == 1
    assert subject.schema_digest == snapshot_digest(subject.schema_snapshot)
    assert not SubjectVersion.objects.filter(subject=subject).exists()
    assert SubjectContext.objects.get(user=user).current_subject is None
    assert set(subject.events.values_list("event_type", flat=True)) == {
        SubjectEvent.EventType.CREATED,
    }
    assert payload["form_schema"]["schema_version"] == subject.schema_version
    assert "schema_snapshot" not in payload
    assert "schema_digest" not in payload


@pytest.mark.django_db
def test_stale_schema_rejected_and_unknown_field_returns_422():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    client = client_for(user)
    stale_version = subject_type.schema_version
    subject_type.schema_version += 1
    subject_type.save(update_fields=["schema_version", "updated_at"])

    stale = client.post(
        "/api/v1/subjects",
        {
            **create_payload(subject_type),
            "expected_schema_version": stale_version,
        },
        format="json",
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "SUBJECT_SCHEMA_MISMATCH"

    invalid = client.post(
        "/api/v1/subjects",
        create_payload(subject_type, {"unknown_field": "not accepted"}),
        format="json",
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "SUBJECT_FIELD_VALUES_INVALID"
    assert invalid.json()["error"]["details"]["fields"]["unknown_field"]


@pytest.mark.django_db
def test_existing_subject_uses_frozen_schema_after_catalog_changes():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    client = client_for(user)
    created = client.post(
        "/api/v1/subjects",
        create_payload(subject_type, {"name": "Before"}),
        format="json",
    )
    subject = Subject.objects.get(pk=data(created)["id"])
    frozen_label = next(
        field["label"]
        for field in subject.schema_snapshot["fields"]
        if field["field_key"] == "name"
    )
    config = subject_type.field_configs.get(field_definition__field_key="name")
    config.label = "Changed current label"
    config.version += 1
    config.save(update_fields=["label", "version", "updated_at"])
    subject_type.schema_version += 1
    subject_type.save(update_fields=["schema_version", "updated_at"])

    updated = client.patch(
        f"/api/v1/subjects/{subject.pk}/draft",
        {"expected_version": subject.version, "values": {"name": "After"}},
        format="json",
    )
    assert updated.status_code == 200
    payload = data(updated)
    assert payload["draft_values"]["name"] == "After"
    returned_label = next(
        field["label"] for field in payload["form_schema"]["fields"] if field["field_key"] == "name"
    )
    assert returned_label == frozen_label
    assert returned_label != "Changed current label"


@pytest.mark.django_db
def test_business_profile_persists_round_trips_and_keeps_old_subjects_compatible():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    client = client_for(user)
    created = client.post(
        "/api/v1/subjects",
        create_payload(
            subject_type,
            {
                "name": "示例企业",
                "service_regions": '{"version":1,"nationwide":true,"areas":[]}',
            },
        ),
        format="json",
    )
    subject_id = data(created)["id"]

    old_detail = client.get(f"/api/v1/subjects/{subject_id}")
    assert old_detail.status_code == 200
    assert data(old_detail)["business_profile"] == {
        "legal_entity_type": "",
        "contact_name": "",
        "contact_phone": "",
        "business_address": "",
        "industry": "",
        "primary_business": "",
        "brand_name": "",
        "subject_aliases": "",
        "unified_social_credit_code": "",
        "social_channels": {
            "douyin": "",
            "wechat_channels": "",
            "wechat_official_account": "",
            "xiaohongshu": "",
            "kuaishou": "",
            "ecommerce_urls": "",
            "other_public_urls": "",
        },
    }
    assert not SubjectBusinessProfile.objects.filter(subject_id=subject_id).exists()

    profile = {
        "legal_entity_type": "company",
        "contact_name": "张三",
        "contact_phone": "0755-12345678",
        "business_address": BUSINESS_ADDRESS,
        "industry": "企业服务",
        "primary_business": "企业 GEO 咨询与内容服务",
        "brand_name": "示例品牌",
        "social_channels": {
            "douyin": "示例品牌",
            "wechat_official_account": "示例公众号",
            "ecommerce_urls": "https://shop.example.com",
        },
    }
    saved = client.patch(
        f"/api/v1/subjects/{subject_id}/draft",
        {
            "expected_version": data(old_detail)["version"],
            "values": data(old_detail)["draft_values"],
            "profile_values": profile,
        },
        format="json",
    )
    assert saved.status_code == 200
    assert data(saved)["business_profile"]["contact_name"] == "张三"
    assert data(saved)["business_profile"]["social_channels"]["xiaohongshu"] == ""

    persisted = SubjectBusinessProfile.objects.get(subject_id=subject_id)
    assert persisted.primary_business == "企业 GEO 咨询与内容服务"
    assert persisted.social_channels["douyin"] == "示例品牌"
    subject = Subject.objects.get(pk=subject_id)
    assert subject.draft_values["service_regions"] == ('{"version":1,"nationwide":true,"areas":[]}')
    assert "contact_name" not in subject.draft_values
    assert "contact_phone" not in subject.draft_values

    edited_profile = {
        **data(saved)["business_profile"],
        "contact_name": "李四",
        "social_channels": {
            **data(saved)["business_profile"]["social_channels"],
            "xiaohongshu": "示例小红书主页",
        },
    }
    edited = client.patch(
        f"/api/v1/subjects/{subject_id}/draft",
        {
            "expected_version": data(saved)["version"],
            "values": data(saved)["draft_values"],
            "profile_values": edited_profile,
        },
        format="json",
    )
    assert edited.status_code == 200
    refreshed = client.get(f"/api/v1/subjects/{subject_id}")
    assert data(refreshed)["business_profile"]["contact_name"] == "李四"
    assert data(refreshed)["business_profile"]["social_channels"]["xiaohongshu"] == "示例小红书主页"
    assert SubjectBusinessProfile.objects.filter(subject_id=subject_id).count() == 1


@pytest.mark.django_db
def test_deleted_legacy_subject_without_business_profile_remains_readable():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    client = client_for(user)
    created = client.post(
        "/api/v1/subjects",
        create_payload(subject_type, {"name": "历史主体"}),
        format="json",
    )
    subject = Subject.objects.get(pk=data(created)["id"])
    subject.status = Subject.Status.ARCHIVED
    subject.save(update_fields=["status", "updated_at"])

    response = client.get(f"/api/v1/subjects/{subject.pk}")

    assert response.status_code == 200
    assert data(response)["status"] == "archived"
    assert data(response)["business_profile"]["contact_name"] == ""
    assert not SubjectBusinessProfile.objects.filter(subject=subject).exists()


@pytest.mark.django_db
def test_single_save_persists_profile_and_makes_subject_values_effective():
    install_empty_published_risk_catalog()
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    client = client_for(user)
    created = client.post(
        "/api/v1/subjects",
        create_payload(subject_type, {"name": "保存即生效企业"}),
        format="json",
    )
    subject_id = data(created)["id"]
    profile = {
        "legal_entity_type": "company",
        "contact_name": "张三",
        "contact_phone": "0755-12345678",
        "business_address": BUSINESS_ADDRESS,
        "industry": "企业服务",
        "primary_business": "企业 GEO 服务",
        "brand_name": "显问示例",
        "social_channels": {},
    }

    saved = client.put(
        f"/api/v1/subjects/{subject_id}",
        {
            "expected_version": data(created)["version"],
            "values": complete_values(data(created), summary="已保存的企业简介"),
            "profile_values": profile,
        },
        format="json",
    )

    assert saved.status_code == 200
    result = data(saved)
    assert result["version_created"] is True
    assert result["subject"]["status"] == "active"
    assert result["subject"]["is_current"] is True
    assert result["subject"]["current_version_no"] == 1
    assert result["version"]["field_values"]["summary"] == "已保存的企业简介"
    assert result["subject"]["business_profile"]["contact_name"] == "张三"
    assert SubjectVersion.objects.filter(subject_id=subject_id).count() == 1
    assert str(SubjectContext.objects.get(user=user).current_subject_id) == subject_id

    profile_only = client.put(
        f"/api/v1/subjects/{subject_id}",
        {
            "expected_version": result["subject"]["version"],
            "values": result["subject"]["draft_values"],
            "profile_values": {**profile, "contact_name": "李四"},
        },
        format="json",
    )
    assert profile_only.status_code == 200
    assert data(profile_only)["version_created"] is False
    assert data(profile_only)["subject"]["business_profile"]["contact_name"] == "李四"
    assert SubjectVersion.objects.filter(subject_id=subject_id).count() == 1


@pytest.mark.django_db
def test_invalid_profile_field_returns_exact_nested_validation_response():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    client = client_for(user)
    created = client.post(
        "/api/v1/subjects",
        create_payload(subject_type, {"name": "校验示例企业"}),
        format="json",
    )

    response = client.put(
        f"/api/v1/subjects/{data(created)['id']}",
        {
            "expected_version": data(created)["version"],
            "values": complete_values(data(created)),
            "profile_values": {
                "legal_entity_type": "company",
                "contact_name": "张三",
                "contact_phone": "不是电话号码",
                "business_address": "广东省广州市天河区",
                "primary_business": "企业 GEO 服务",
                "brand_name": "",
                "social_channels": {},
            },
        },
        format="json",
    )

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "请求参数不正确",
        "details": {
            "fields": {
                "profile_values": {
                    "contact_phone": [{"message": "输入值不匹配要求的模式。", "code": "invalid"}]
                }
            }
        },
    }


@pytest.mark.django_db
def test_no_plan_allows_only_one_subject_but_deleted_subject_does_not_count():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    client = client_for(user)
    first = client.post("/api/v1/subjects", create_payload(subject_type), format="json")
    first_id = data(first)["id"]

    rejected = client.post("/api/v1/subjects", create_payload(subject_type), format="json")
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "SUBJECT_LIMIT_REACHED"

    archived = client.post(
        f"/api/v1/subjects/{first_id}/archive",
        {"expected_version": data(first)["version"]},
        format="json",
    )
    assert archived.status_code == 200
    assert data(archived)["status"] == "archived"
    assert SubjectContext.objects.get(user=user).current_subject is None
    assert data(client.get("/api/v1/subjects"))["subjects"] == []
    archived_rows = data(client.get("/api/v1/subjects?status=archived"))["subjects"]
    assert [row["id"] for row in archived_rows] == [first_id]

    replacement = client.post("/api/v1/subjects", create_payload(subject_type), format="json")
    assert replacement.status_code == 201


@pytest.mark.django_db
def test_cancel_pending_is_read_only_and_inactive_type_keeps_existing_detail_editable():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    client = client_for(user)
    created = client.post(
        "/api/v1/subjects",
        create_payload(subject_type, {"name": "Before"}),
        format="json",
    )
    subject_id = data(created)["id"]
    subject_type.status = SubjectType.Status.INACTIVE
    subject_type.save(update_fields=["status", "updated_at"])

    readable = client.get(f"/api/v1/subjects/{subject_id}")
    editable = client.patch(
        f"/api/v1/subjects/{subject_id}/draft",
        {"expected_version": data(created)["version"], "values": {"name": "After"}},
        format="json",
    )
    with (
        patch(
            "apps.subjects.subject_services._effective_subscription_locked",
            return_value=object(),
        ),
        patch("apps.subjects.subject_services.effective_subject_activation_limit", return_value=5),
    ):
        activate = client.post(
            f"/api/v1/subjects/{subject_id}/activate",
            {"expected_version": data(editable)["version"]},
            format="json",
        )
    assert readable.status_code == editable.status_code == 200
    assert activate.status_code == 409

    user.account_status = User.AccountStatus.CANCEL_PENDING
    user.save(update_fields=["account_status", "updated_at"])
    client = client_for(user)
    assert client.get(f"/api/v1/subjects/{subject_id}").status_code == 200
    denied = client.patch(
        f"/api/v1/subjects/{subject_id}/draft",
        {"expected_version": data(editable)["version"], "values": {"name": "Denied"}},
        format="json",
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"


@pytest.mark.django_db
def test_current_same_subject_is_noop_and_detail_get_is_read_only():
    install_empty_published_risk_catalog()
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    client = client_for(user)
    created = client.post(
        "/api/v1/subjects",
        create_payload(subject_type, {"name": "当前主体"}),
        format="json",
    )
    subject_id = data(created)["id"]
    context = SubjectContext.objects.get(user=user)

    unsaved = client.put(
        "/api/v1/subjects/current",
        {"subject_id": subject_id, "expected_version": context.version},
        format="json",
    )
    assert unsaved.status_code == 409
    assert unsaved.json()["error"]["code"] == "SUBJECT_STATE_CONFLICT"

    saved = client.put(
        f"/api/v1/subjects/{subject_id}",
        {
            "expected_version": data(created)["version"],
            "values": complete_values(data(created)),
            "profile_values": {
                "legal_entity_type": "company",
                "contact_name": "张三",
                "contact_phone": "0755-12345678",
                "business_address": BUSINESS_ADDRESS,
                "industry": "企业服务",
                "primary_business": "企业 GEO 服务",
                "brand_name": "",
                "social_channels": {},
            },
        },
        format="json",
    )
    assert saved.status_code == 200
    context.refresh_from_db()
    event_count = SubjectEvent.objects.count()

    response = client.put(
        "/api/v1/subjects/current",
        {"subject_id": subject_id, "expected_version": context.version},
        format="json",
    )
    assert response.status_code == 200
    assert data(response)["version"] == context.version
    assert SubjectEvent.objects.count() == event_count

    with CaptureQueriesContext(connection) as queries:
        detail = client.get(f"/api/v1/subjects/{subject_id}")
    assert detail.status_code == 200
    assert not any(
        query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for query in queries
    )


@pytest.mark.django_db
def test_deleting_current_subject_selects_another_saved_subject():
    install_empty_published_risk_catalog()
    user = make_user()
    user.is_test_account = True
    user.save(update_fields=["is_test_account", "updated_at"])
    subject_type = SubjectType.objects.get(key="enterprise")
    client = client_for(user)
    profile = {
        "legal_entity_type": "company",
        "contact_name": "张三",
        "contact_phone": "0755-12345678",
        "business_address": BUSINESS_ADDRESS,
        "industry": "企业服务",
        "primary_business": "企业 GEO 服务",
        "brand_name": "",
        "social_channels": {},
    }

    saved_ids = []
    for name in ("第一主体", "第二主体"):
        created = client.post(
            "/api/v1/subjects",
            create_payload(subject_type, {"name": name}),
            format="json",
        )
        saved = client.put(
            f"/api/v1/subjects/{data(created)['id']}",
            {
                "expected_version": data(created)["version"],
                "values": complete_values(data(created)),
                "profile_values": profile,
            },
            format="json",
        )
        assert saved.status_code == 200
        saved_ids.append(data(saved)["subject"]["id"])

    context = SubjectContext.objects.get(user=user)
    switched = client.put(
        "/api/v1/subjects/current",
        {"subject_id": saved_ids[1], "expected_version": context.version},
        format="json",
    )
    assert switched.status_code == 200
    second = Subject.objects.get(pk=saved_ids[1])
    deleted = client.post(
        f"/api/v1/subjects/{second.pk}/archive",
        {"expected_version": second.version},
        format="json",
    )

    assert deleted.status_code == 200
    context.refresh_from_db()
    assert str(context.current_subject_id) == saved_ids[0]
    rows = data(client.get("/api/v1/subjects"))["subjects"]
    assert [row["id"] for row in rows] == [saved_ids[0]]


@pytest.mark.django_db
@pytest.mark.parametrize("invalid", [None, True, -1, 1_000_001, "2"])
def test_subject_limit_snapshot_integrity_is_strict(invalid):
    user = make_user()
    with pytest.raises(SubjectEntitlementIntegrityError):
        subject_limit_preview(
            user=user, target_snapshot={"limits": {"subject_active_limit": invalid}}
        )


@pytest.mark.django_db
def test_subject_limit_preview_reports_required_archive_count():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    for index in range(2):
        subject = Subject.objects.create(
            user=user,
            subject_type=subject_type,
            status=Subject.Status.ACTIVE,
            draft_values={"name": f"Subject {index}"},
            schema_version=subject_type.schema_version,
            schema_snapshot_format_version=1,
            schema_snapshot={"format_version": 1},
            schema_digest="0" * 64,
        )
        assert subject.pk
    preview = subject_limit_preview(
        user=user,
        target_snapshot={"limits": {"subject_active_limit": 1}},
    )
    assert (preview.active_count, preview.target_limit, preview.required_archive_count) == (2, 1, 1)
    with pytest.raises(SubjectLimitReconciliationRequired):
        from apps.subjects.subject_services import assert_target_subject_limit_locked

        assert_target_subject_limit_locked(
            user=user,
            target_snapshot={"limits": {"subject_active_limit": 1}},
        )


@pytest.mark.django_db
def test_subject_writes_require_csrf_and_cross_user_objects_are_404():
    owner = make_user()
    outsider = make_user(phone="13700137000")
    subject_type = SubjectType.objects.get(key="enterprise")
    created = client_for(owner).post(
        "/api/v1/subjects",
        create_payload(subject_type),
        format="json",
    )
    subject_id = data(created)["id"]

    outsider_client = client_for(outsider)
    assert outsider_client.get(f"/api/v1/subjects/{subject_id}").status_code == 404
    hidden_write = outsider_client.patch(
        f"/api/v1/subjects/{subject_id}/draft",
        {"expected_version": 1, "values": {"name": "not allowed"}},
        format="json",
    )
    assert hidden_write.status_code == 404

    csrf_client = APIClient(enforce_csrf_checks=True)
    csrf_client.force_authenticate(owner)
    blocked = csrf_client.patch(
        f"/api/v1/subjects/{subject_id}/draft",
        {"expected_version": data(created)["version"], "values": {"name": "blocked"}},
        format="json",
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "CSRF_FAILED"
