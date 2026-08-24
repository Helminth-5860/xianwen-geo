import uuid

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.admin_rbac.models import AuditEvent
from apps.subjects.catalog import COMMON_FIELD_CATALOG, SUBJECT_TYPE_CATALOG
from apps.subjects.models import (
    SubjectFieldDefinition,
    SubjectFieldOption,
    SubjectType,
    SubjectTypeFieldConfig,
)
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def synchronize_catalogs():
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def make_user(*, phone="13800138000", account="active"):
    return User.objects.create_user(
        phone=phone,
        nickname="主体配置用户",
        password=PASSWORD,
        account_status=account,
    )


def make_admin():
    return User.objects.create_superuser(
        phone="13900139000",
        nickname="主体目录管理员",
        password=PASSWORD,
    )


def admin_client(*, csrf=False):
    client = APIClient(enforce_csrf_checks=csrf)
    return authenticate_admin_client(client, make_admin())


def api_data(response):
    return response.json()["data"]


@pytest.mark.django_db
def test_catalog_contains_only_frozen_types_and_common_fields():
    assert set(SubjectType.objects.values_list("key", flat=True)) == {
        item.key for item in SUBJECT_TYPE_CATALOG
    }
    assert set(
        SubjectFieldDefinition.objects.filter(scope="common").values_list("field_key", flat=True)
    ) == {item.key for item in COMMON_FIELD_CATALOG}
    assert not SubjectFieldDefinition.objects.filter(scope="custom").exists()
    for subject_type in SubjectType.objects.all():
        configs = subject_type.field_configs.select_related("field_definition")
        assert configs.count() == len(COMMON_FIELD_CATALOG)
        official = configs.get(field_definition__field_key="name")
        assert official.enabled and official.required
        assert official.name_role == "official_name"


@pytest.mark.django_db
def test_available_users_can_read_active_types_and_form_schema_without_writes():
    client = APIClient()
    client.force_authenticate(make_user())
    subject_type = SubjectType.objects.get(key="enterprise")
    before = (
        subject_type.schema_version,
        subject_type.version,
        SubjectTypeFieldConfig.objects.count(),
        AuditEvent.objects.count(),
    )

    listing = client.get("/api/v1/subject-types")
    schema = client.get(f"/api/v1/subject-types/{subject_type.id}/form-schema")

    assert listing.status_code == schema.status_code == 200
    assert len(api_data(listing)) == len(SUBJECT_TYPE_CATALOG)
    schema_data = api_data(schema)
    assert schema_data["schema_version"] == subject_type.schema_version
    assert {field["field_key"] for field in schema_data["fields"]} == {
        item.key for item in COMMON_FIELD_CATALOG
    }
    assert all("version" not in field for field in schema_data["fields"])
    assert all("is_builtin" not in field for field in schema_data["fields"])
    subject_type.refresh_from_db()
    assert before == (
        subject_type.schema_version,
        subject_type.version,
        SubjectTypeFieldConfig.objects.count(),
        AuditEvent.objects.count(),
    )


@pytest.mark.django_db
def test_inactive_type_is_hidden_and_unavailable_accounts_are_denied():
    subject_type = SubjectType.objects.get(key="enterprise")
    subject_type.status = "inactive"
    subject_type.save(update_fields=["status", "updated_at"])
    active = APIClient()
    active.force_authenticate(make_user())
    assert active.get(f"/api/v1/subject-types/{subject_type.id}/form-schema").status_code == 404
    assert all(
        item["id"] != str(subject_type.id) for item in api_data(active.get("/api/v1/subject-types"))
    )

    frozen = APIClient()
    frozen.force_authenticate(make_user(phone="13700137000", account="frozen"))
    denied = frozen.get("/api/v1/subject-types")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.django_db
def test_admin_create_type_atomically_adds_all_common_configs_and_audit():
    response = admin_client().post(
        "/api/v1/admin/subject-types",
        {
            "key": "exhibition",
            "name": "展会",
            "description": "展览活动主体",
            "icon_key": "calendar",
            "sort_order": 120,
        },
        format="json",
    )
    assert response.status_code == 201
    data = api_data(response)
    subject_type = SubjectType.objects.get(pk=data["id"])
    assert subject_type.field_configs.count() == len(COMMON_FIELD_CATALOG)
    assert {item["field_key"] for item in data["fields"]} == {
        item.key for item in COMMON_FIELD_CATALOG
    }
    assert (
        AuditEvent.objects.filter(
            category="subject_schema",
            action_key="subject_type.create",
            target_id=subject_type.id,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_custom_choice_field_options_and_every_mutation_bump_schema_version():
    subject_type = SubjectType.objects.get(key="enterprise")
    client = admin_client()
    start = subject_type.schema_version
    created = client.post(
        f"/api/v1/admin/subject-types/{subject_type.id}/fields",
        {
            "expected_schema_version": start,
            "field_key": "business_stage",
            "field_type": "select",
            "label": "发展阶段",
            "enabled": True,
            "options": [
                {"option_key": "startup", "label": "初创", "sort_order": 10},
                {"option_key": "growth", "label": "成长", "sort_order": 20},
            ],
        },
        format="json",
    )
    assert created.status_code == 201
    config_data = api_data(created)
    config = SubjectTypeFieldConfig.objects.get(pk=config_data["id"])
    subject_type.refresh_from_db()
    assert subject_type.schema_version == start + 1
    assert config.field_definition.scope == "custom"
    assert config.field_definition.owner_subject_type == subject_type
    assert list(config.options.values_list("option_key", flat=True)) == ["startup", "growth"]

    updated = client.patch(
        f"/api/v1/admin/subject-type-fields/{config.id}",
        {
            "expected_schema_version": subject_type.schema_version,
            "expected_version": config.version,
            "label": "企业发展阶段",
            "default_value": "startup",
            "used_for_ai": True,
        },
        format="json",
    )
    assert updated.status_code == 200
    subject_type.refresh_from_db()
    config.refresh_from_db()
    assert subject_type.schema_version == start + 2
    assert config.version == 2

    option = config.options.get(option_key="startup")
    changed = client.patch(
        f"/api/v1/admin/subject-field-options/{option.id}",
        {
            "expected_schema_version": subject_type.schema_version,
            "expected_version": option.version,
            "label": "初创期",
        },
        format="json",
    )
    assert changed.status_code == 200
    subject_type.refresh_from_db()
    config.refresh_from_db()
    assert subject_type.schema_version == start + 3
    assert config.version == 3


@pytest.mark.django_db
def test_stale_schema_version_blocks_different_field_mutation():
    subject_type = SubjectType.objects.get(key="enterprise")
    configs = list(subject_type.field_configs.order_by("sort_order")[:2])
    client = admin_client()
    first = client.patch(
        f"/api/v1/admin/subject-type-fields/{configs[0].id}",
        {
            "expected_schema_version": subject_type.schema_version,
            "expected_version": configs[0].version,
            "label": "新的主体名称",
        },
        format="json",
    )
    assert first.status_code == 200
    stale = client.patch(
        f"/api/v1/admin/subject-type-fields/{configs[1].id}",
        {
            "expected_schema_version": subject_type.schema_version,
            "expected_version": configs[1].version,
            "label": "不会保存",
        },
        format="json",
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "SUBJECT_SCHEMA_VERSION_CONFLICT"
    configs[1].refresh_from_db()
    assert configs[1].label != "不会保存"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field_type", "default_value"),
    [
        ("number", True),
        ("date", "2026-02-30"),
        ("url", "javascript:alert(1)"),
        ("image", "image-key"),
        ("file", {"id": "file-key"}),
    ],
)
def test_invalid_default_values_are_rejected(field_type, default_value):
    subject_type = SubjectType.objects.get(key="enterprise")
    response = admin_client().post(
        f"/api/v1/admin/subject-types/{subject_type.id}/fields",
        {
            "expected_schema_version": subject_type.schema_version,
            "field_key": f"invalid_{field_type}_{uuid.uuid4().hex[:8]}",
            "field_type": field_type,
            "label": "无效默认值",
            "enabled": False,
            "default_value": default_value,
        },
        format="json",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SUBJECT_FIELD_CONFIG_INVALID"


@pytest.mark.django_db
def test_immutable_machine_fields_are_not_patchable_and_html_is_rejected():
    config = SubjectTypeFieldConfig.objects.select_related("subject_type").get(
        subject_type__key="enterprise", field_definition__field_key="summary"
    )
    client = admin_client()
    machine = client.patch(
        f"/api/v1/admin/subject-type-fields/{config.id}",
        {
            "expected_schema_version": config.subject_type.schema_version,
            "expected_version": config.version,
            "field_type": "number",
        },
        format="json",
    )
    assert machine.status_code == 422
    unsafe = client.patch(
        f"/api/v1/admin/subject-type-fields/{config.id}",
        {
            "expected_schema_version": config.subject_type.schema_version,
            "expected_version": config.version,
            "label": "<img src=x onerror=alert(1)>",
        },
        format="json",
    )
    assert unsafe.status_code == 422


@pytest.mark.django_db
def test_full_field_order_is_required_and_invalid_order_rolls_back():
    subject_type = SubjectType.objects.get(key="enterprise")
    configs = list(subject_type.field_configs.order_by("sort_order", "id"))
    original = [(item.id, item.sort_order, item.version) for item in configs]
    response = admin_client().put(
        f"/api/v1/admin/subject-types/{subject_type.id}/field-order",
        {
            "expected_schema_version": subject_type.schema_version,
            "fields": [
                {"id": str(item.id), "expected_version": item.version}
                for item in reversed(configs[:-1])
            ],
        },
        format="json",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SUBJECT_FIELD_CONFIG_INVALID"
    assert (
        list(
            subject_type.field_configs.order_by("sort_order", "id").values_list(
                "id", "sort_order", "version"
            )
        )
        == original
    )


@pytest.mark.django_db
def test_schema_writes_require_real_csrf():
    client = admin_client(csrf=True)
    blocked = client.post(
        "/api/v1/admin/subject-types",
        {"key": "event", "name": "活动"},
        format="json",
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.django_db
def test_catalog_sync_is_idempotent_and_does_not_replace_mutable_config():
    config = SubjectTypeFieldConfig.objects.get(
        subject_type__key="enterprise", field_definition__field_key="summary"
    )
    config.label = "管理员自定义简介"
    config.used_for_ai = False
    config.save(update_fields=["label", "used_for_ai", "updated_at"])
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    config.refresh_from_db()
    assert config.label == "管理员自定义简介"
    assert config.used_for_ai is False
    assert SubjectFieldOption.objects.count() == 0


@pytest.mark.django_db
def test_type_option_and_reorder_mutations_each_increment_schema_version():
    subject_type = SubjectType.objects.get(key="enterprise")
    client = admin_client()

    updated = client.patch(
        f"/api/v1/admin/subject-types/{subject_type.id}",
        {
            "expected_version": subject_type.version,
            "expected_schema_version": subject_type.schema_version,
            "name": "企业主体目录",
        },
        format="json",
    )
    assert updated.status_code == 200
    subject_type.refresh_from_db()
    assert subject_type.schema_version == 2
    assert subject_type.version == 2

    disabled = client.post(
        f"/api/v1/admin/subject-types/{subject_type.id}/disable",
        {
            "expected_version": subject_type.version,
            "expected_schema_version": subject_type.schema_version,
        },
        format="json",
    )
    assert disabled.status_code == 200
    subject_type.refresh_from_db()
    assert subject_type.status == "inactive"
    assert subject_type.schema_version == 3

    enabled = client.post(
        f"/api/v1/admin/subject-types/{subject_type.id}/enable",
        {
            "expected_version": subject_type.version,
            "expected_schema_version": subject_type.schema_version,
        },
        format="json",
    )
    assert enabled.status_code == 200
    subject_type.refresh_from_db()
    assert subject_type.status == "active"
    assert subject_type.schema_version == 4

    created = client.post(
        f"/api/v1/admin/subject-types/{subject_type.id}/fields",
        {
            "expected_schema_version": subject_type.schema_version,
            "field_key": "customer_tier",
            "field_type": "select",
            "label": "客户层级",
            "enabled": False,
        },
        format="json",
    )
    assert created.status_code == 201
    config = SubjectTypeFieldConfig.objects.get(pk=api_data(created)["id"])
    subject_type.refresh_from_db()
    assert subject_type.schema_version == 5

    option = client.post(
        f"/api/v1/admin/subject-type-fields/{config.id}/options",
        {
            "expected_schema_version": subject_type.schema_version,
            "expected_config_version": config.version,
            "option_key": "strategic",
            "label": "战略客户",
        },
        format="json",
    )
    assert option.status_code == 201
    subject_type.refresh_from_db()
    config.refresh_from_db()
    assert subject_type.schema_version == 6
    assert config.version == 2

    configs = list(subject_type.field_configs.order_by("sort_order", "id"))
    reordered = client.put(
        f"/api/v1/admin/subject-types/{subject_type.id}/field-order",
        {
            "expected_schema_version": subject_type.schema_version,
            "fields": [
                {"id": str(item.id), "expected_version": item.version} for item in reversed(configs)
            ],
        },
        format="json",
    )
    assert reordered.status_code == 200
    subject_type.refresh_from_db()
    assert subject_type.schema_version == 7
    assert list(
        subject_type.field_configs.order_by("sort_order", "id").values_list("id", flat=True)
    ) == [item.id for item in reversed(configs)]
