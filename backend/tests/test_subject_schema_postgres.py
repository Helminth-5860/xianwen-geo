import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import RequestFactory
from django_redis import get_redis_connection

from apps.subjects.catalog import COMMON_FIELD_CATALOG
from apps.subjects.models import (
    SubjectFieldDefinition,
    SubjectFieldOption,
    SubjectType,
    SubjectTypeFieldConfig,
)
from apps.subjects.services import SubjectSchemaVersionConflict, update_field_config
from apps.users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_postgres_and_redis():
    if connection.vendor != "postgresql":
        pytest.skip("Run through scripts/test-subject-schema.* with PostgreSQL and Redis.")
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


def set_constraints_immediate():
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def create_inactive_type(*, key=None):
    return SubjectType.objects.create(
        key=key or f"custom_{uuid.uuid4().hex[:12]}",
        name="数据库约束测试",
        status=SubjectType.Status.INACTIVE,
    )


def create_choice_config(*, subject_type=None):
    subject_type = subject_type or create_inactive_type()
    definition = SubjectFieldDefinition.objects.create(
        owner_subject_type=subject_type,
        field_key=f"choice_{uuid.uuid4().hex[:10]}",
        field_type=SubjectFieldDefinition.FieldType.SELECT,
        scope=SubjectFieldDefinition.Scope.CUSTOM,
    )
    config = SubjectTypeFieldConfig.objects.create(
        subject_type=subject_type,
        field_definition=definition,
        label="选项字段",
        enabled=False,
    )
    option = SubjectFieldOption.objects.create(
        field_config=config,
        option_key="first",
        label="第一项",
    )
    return subject_type, definition, config, option


def admin_request(user):
    request = RequestFactory().patch("/api/v1/admin/subject-type-fields/test")
    request.user = user
    request.request_id = str(uuid.uuid4())
    return request


def create_admin():
    return User.objects.create_superuser(
        phone=f"139{uuid.uuid4().int % 100000000:08d}",
        nickname="并发测试管理员",
        password="Correct-Horse-Battery-2026!",
    )


def test_subject_schema_postgresql_guards_are_installed():
    expected = {
        "subjects_type_guard",
        "subjects_definition_guard",
        "subjects_config_guard",
        "subjects_option_guard",
        "subjects_type_no_delete",
        "subjects_definition_no_delete",
        "subjects_config_no_delete",
        "subjects_option_no_delete",
        "subjects_type_schema_consistency",
        "subjects_config_schema_consistency",
        "subjects_option_schema_consistency",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(%s)",
            [list(expected)],
        )
        installed = {row[0] for row in cursor.fetchall()}
    assert installed == expected


@pytest.mark.parametrize(
    ("table", "factory"),
    [
        ("subject_types", lambda: create_inactive_type().pk),
        (
            "subject_field_definitions",
            lambda: (
                SubjectFieldDefinition.objects.create(
                    owner_subject_type=create_inactive_type(),
                    field_key=f"field_{uuid.uuid4().hex[:8]}",
                    field_type="text",
                    scope="custom",
                ).pk
            ),
        ),
        ("subject_type_field_configs", lambda: create_choice_config()[2].pk),
        ("subject_field_options", lambda: create_choice_config()[3].pk),
    ],
)
def test_catalog_rows_reject_raw_sql_delete(table, factory):
    row_id = factory()
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table} WHERE id=%s", [row_id])


@pytest.mark.parametrize(
    ("table", "column", "value", "factory"),
    [
        ("subject_types", "key", "changed_key", lambda: create_inactive_type().pk),
        ("subject_types", "is_builtin", True, lambda: create_inactive_type().pk),
        (
            "subject_field_definitions",
            "field_key",
            "changed_field",
            lambda: create_choice_config()[1].pk,
        ),
        (
            "subject_field_definitions",
            "field_type",
            "multi",
            lambda: create_choice_config()[1].pk,
        ),
        (
            "subject_field_definitions",
            "scope",
            "common",
            lambda: create_choice_config()[1].pk,
        ),
        (
            "subject_field_options",
            "option_key",
            "changed_option",
            lambda: create_choice_config()[3].pk,
        ),
    ],
)
def test_machine_semantics_reject_raw_sql_updates(table, column, value, factory):
    row_id = factory()
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {table} SET {column}=%s WHERE id=%s", [value, row_id])


def test_common_custom_key_conflict_is_rejected_at_commit():
    subject_type = SubjectType.objects.get(key="enterprise")
    with pytest.raises(DatabaseError), transaction.atomic():
        definition = SubjectFieldDefinition.objects.create(
            owner_subject_type=subject_type,
            field_key="name",
            field_type="text",
            scope="custom",
        )
        SubjectTypeFieldConfig.objects.create(
            subject_type=subject_type,
            field_definition=definition,
            label="冲突名称",
            enabled=False,
        )
        set_constraints_immediate()


def test_active_schema_cannot_lose_unique_required_official_name():
    config = SubjectTypeFieldConfig.objects.get(
        subject_type__key="enterprise", field_definition__field_key="name"
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subject_type_field_configs SET required=false WHERE id=%s", [config.pk]
            )
        set_constraints_immediate()


def test_non_choice_options_and_invalid_json_defaults_are_rejected():
    text_config = SubjectTypeFieldConfig.objects.get(
        subject_type__key="enterprise", field_definition__field_key="summary"
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        SubjectFieldOption.objects.create(
            field_config=text_config,
            option_key="invalid",
            label="无效选项",
        )
        set_constraints_immediate()

    cases = [
        ("summary", True),
        ("official_url", "javascript:alert(1)"),
    ]
    for field_key, value in cases:
        config = SubjectTypeFieldConfig.objects.get(
            subject_type__key="enterprise", field_definition__field_key=field_key
        )
        with pytest.raises(DatabaseError), transaction.atomic():
            SubjectTypeFieldConfig.objects.filter(pk=config.pk).update(default_value=value)
            set_constraints_immediate()

    subject_type = create_inactive_type()
    for index, field_type in enumerate(("number", "image", "file")):
        definition = SubjectFieldDefinition.objects.create(
            owner_subject_type=subject_type,
            field_key=f"{field_type}_{index}",
            field_type=field_type,
            scope="custom",
        )
        invalid = True if field_type == "number" else "not-null"
        with pytest.raises(DatabaseError), transaction.atomic():
            SubjectTypeFieldConfig.objects.create(
                subject_type=subject_type,
                field_definition=definition,
                label="无效默认值",
                enabled=False,
                default_value=invalid,
            )
            set_constraints_immediate()


def test_option_key_is_immutable_and_unique_within_field():
    _subject_type, _definition, config, option = create_choice_config()
    with pytest.raises(DatabaseError), transaction.atomic():
        SubjectFieldOption.objects.create(
            field_config=config,
            option_key=option.option_key,
            label="重复选项",
        )

    with pytest.raises(DatabaseError), transaction.atomic():
        SubjectFieldOption.objects.filter(pk=option.pk).update(option_key="second")


def test_new_subject_type_service_creates_complete_common_schema_atomically():
    from apps.subjects.services import create_subject_type

    actor = create_admin()
    subject_type = create_subject_type(
        request=admin_request(actor),
        data={
            "key": f"new_{uuid.uuid4().hex[:10]}",
            "name": "新主体类型",
            "description": "完整公共字段",
            "icon_key": "subject",
            "sort_order": 999,
        },
    )
    assert subject_type.status == SubjectType.Status.ACTIVE
    assert subject_type.field_configs.count() == len(COMMON_FIELD_CATALOG)
    assert (
        subject_type.field_configs.filter(
            enabled=True, required=True, name_role="official_name"
        ).count()
        == 1
    )


def test_two_concurrent_field_updates_serialize_on_schema_version():
    subject_type = SubjectType.objects.get(key="enterprise")
    configs = list(subject_type.field_configs.order_by("sort_order")[:2])
    actor = create_admin()
    expected_schema = subject_type.schema_version

    def mutate(config):
        close_old_connections()
        try:
            update_field_config(
                request=admin_request(User.objects.get(pk=actor.pk)),
                config_id=config.pk,
                data={
                    "expected_schema_version": expected_schema,
                    "expected_version": config.version,
                    "label": f"并发更新-{config.pk}",
                },
            )
            return "updated"
        except SubjectSchemaVersionConflict:
            return "stale"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(mutate, configs))
    assert sorted(results) == ["stale", "updated"]
    subject_type.refresh_from_db()
    assert subject_type.schema_version == expected_schema + 1


def test_schema_mutation_and_audit_event_roll_back_together():
    config = SubjectTypeFieldConfig.objects.select_related("subject_type").get(
        subject_type__key="enterprise", field_definition__field_key="summary"
    )
    original = (config.label, config.version, config.subject_type.schema_version)
    with patch("apps.subjects.services.record_audit_event", side_effect=RuntimeError("audit")):
        with pytest.raises(RuntimeError, match="audit"):
            update_field_config(
                request=admin_request(create_admin()),
                config_id=config.pk,
                data={
                    "expected_schema_version": config.subject_type.schema_version,
                    "expected_version": config.version,
                    "label": "必须回滚",
                },
            )
    config.refresh_from_db()
    config.subject_type.refresh_from_db()
    assert (config.label, config.version, config.subject_type.schema_version) == original


def test_redis_is_connectivity_only_and_not_subject_schema_fact_source():
    redis = get_redis_connection("default")
    redis.set("xw0201:probe", "present", ex=30)
    redis.flushdb()
    assert SubjectType.objects.filter(key="enterprise", status="active").exists()
    assert SubjectTypeFieldConfig.objects.filter(subject_type__key="enterprise").count() == len(
        COMMON_FIELD_CATALOG
    )


def test_all_catalog_bindings_and_owner_semantics_are_raw_sql_immutable():
    subject_type, definition, config, option = create_choice_config()
    other_type, other_definition, other_config, _other_option = create_choice_config()

    immutable_updates = (
        (
            "subject_field_definitions",
            "owner_subject_type_id",
            other_type.pk,
            definition.pk,
        ),
        ("subject_field_definitions", "is_builtin", True, definition.pk),
        ("subject_type_field_configs", "subject_type_id", other_type.pk, config.pk),
        (
            "subject_type_field_configs",
            "field_definition_id",
            other_definition.pk,
            config.pk,
        ),
        ("subject_field_options", "field_config_id", other_config.pk, option.pk),
    )
    for table, column, value, row_id in immutable_updates:
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE {table} SET {column}=%s WHERE id=%s", [value, row_id])

    subject_type.refresh_from_db()
    definition.refresh_from_db()
    config.refresh_from_db()
    option.refresh_from_db()
    assert definition.owner_subject_type_id == subject_type.pk
    assert definition.is_builtin is False
    assert config.subject_type_id == subject_type.pk
    assert config.field_definition_id == definition.pk
    assert option.field_config_id == config.pk


def test_uppercase_option_key_cannot_bypass_case_insensitive_uniqueness():
    _subject_type, _definition, config, _option = create_choice_config()
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO subject_field_options "
                "(id, field_config_id, option_key, label, enabled, sort_order, version, "
                "created_at, updated_at) VALUES (%s, %s, %s, %s, true, 0, 1, now(), now())",
                [uuid.uuid4(), config.pk, "FIRST", "重复选项"],
            )
