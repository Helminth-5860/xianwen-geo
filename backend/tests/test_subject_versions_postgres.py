import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from unittest.mock import patch

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django_redis import get_redis_connection

from apps.subjects.models import (
    SubjectEvent,
    SubjectFieldDefinition,
    SubjectName,
    SubjectProduct,
    SubjectType,
    SubjectTypeFieldConfig,
    SubjectVersion,
)
from apps.subjects.schema_snapshots import derive_product_candidates
from apps.subjects.subject_services import create_subject, update_subject_draft
from apps.subjects.version_services import SubjectVersionConflict, commit_subject_version
from apps.users.models import User
from tests.subject_risk_helpers import install_empty_published_risk_catalog

reject_existing_subject_versions = import_module(
    "apps.subjects.migrations.0006_subject_versions_names_products"
).reject_existing_subject_versions

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_postgres_and_redis():
    if connection.vendor != "postgresql":
        pytest.skip("Run through scripts/test-subject-schema.* with PostgreSQL and Redis.")
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    redis = get_redis_connection("default")
    install_empty_published_risk_catalog()
    assert redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


def make_user():
    return User.objects.create_user(
        phone=f"138{uuid.uuid4().int % 100000000:08d}",
        nickname="Version PostgreSQL user",
        password="Correct-Horse-Battery-2026!",
        approval_status=User.ApprovalStatus.PENDING,
    )


def make_subject(user, *, name="Version subject", product=None):
    subject_type = SubjectType.objects.get(key="enterprise")
    initial_values = {"name": name}
    if product is not None:
        field_key = f"product_{uuid.uuid4().hex[:10]}"
        definition = SubjectFieldDefinition.objects.create(
            owner_subject_type=subject_type,
            field_key=field_key,
            field_type=SubjectFieldDefinition.FieldType.TEXT,
            scope=SubjectFieldDefinition.Scope.CUSTOM,
        )
        SubjectTypeFieldConfig.objects.create(
            subject_type=subject_type,
            field_definition=definition,
            label="Product",
            enabled=True,
            name_role=SubjectTypeFieldConfig.NameRole.PRODUCT,
        )
        initial_values[field_key] = product
    return create_subject(
        user_id=user.pk,
        subject_type_id=subject_type.pk,
        expected_schema_version=subject_type.schema_version,
        initial_values=initial_values,
        request_id=uuid.uuid4(),
    )


def commit(subject):
    candidates = derive_product_candidates(subject.schema_snapshot, subject.draft_values)
    confirmations = [
        {
            "candidate_key": candidate["candidate_key"],
            "uniqueness_confirmed": True,
            "include_in_mention": False,
        }
        for candidate in candidates
    ]
    return commit_subject_version(
        user_id=subject.user_id,
        subject_id=subject.pk,
        expected_version=subject.version,
        product_confirmations=confirmations,
        request_id=uuid.uuid4(),
    )


def parallel(*operations):
    barrier = threading.Barrier(len(operations))

    def run(operation):
        close_old_connections()
        barrier.wait()
        try:
            return operation()
        except Exception as exc:
            return exc
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        futures = [pool.submit(run, operation) for operation in operations]
        return [future.result(timeout=30) for future in futures]


def set_constraints_immediate():
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def raw_version_values(subject, version_no):
    return [
        str(uuid.uuid4()),
        str(subject.pk),
        version_no,
        json.dumps(subject.draft_values),
        subject.schema_version,
        subject.schema_snapshot_format_version,
        json.dumps(subject.schema_snapshot),
        subject.schema_digest,
        "a" * 64,
        "b" * 64,
        "Raw name",
        str(subject.user_id),
    ]


def insert_raw_version(subject, version_no, *, schema_digest=None):
    values = raw_version_values(subject, version_no)
    if schema_digest is not None:
        values[7] = schema_digest
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO subject_versions (
                id, subject_id, version_no, field_values, schema_version,
                schema_snapshot_format_version, schema_snapshot, schema_digest,
                field_values_digest, semantic_digest, official_name, created_by_id, created_at
            ) VALUES (
                %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, NOW()
            )
            """,
            values,
        )


def test_subject_version_postgresql_guards_are_installed():
    expected = {
        "subjects_version_guard",
        "subjects_name_guard",
        "subjects_product_guard",
        "subjects_config_name_role_type",
        "subjects_version_chain_subject",
        "subjects_version_chain_version",
        "subjects_version_chain_name",
        "subjects_version_chain_product",
        "subjects_version_chain_event",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(%s)",
            [list(expected)],
        )
        assert {row[0] for row in cursor.fetchall()} == expected


def test_concurrent_first_commit_is_exactly_once_and_strictly_starts_at_one():
    user = make_user()
    subject = make_subject(user)
    expected_version = subject.version

    def operation():
        result = commit_subject_version(
            user_id=user.pk,
            subject_id=subject.pk,
            expected_version=expected_version,
            product_confirmations=[],
            request_id=uuid.uuid4(),
        )
        return result[1].version_no

    results = parallel(operation, operation)
    assert results.count(1) == 1
    assert sum(isinstance(item, SubjectVersionConflict) for item in results) == 1
    assert list(
        SubjectVersion.objects.filter(subject=subject).values_list("version_no", flat=True)
    ) == [1]
    subject.refresh_from_db()
    assert subject.current_version.version_no == 1
    assert subject.events.filter(event_type=SubjectEvent.EventType.VERSION_COMMITTED).count() == 1


def test_draft_patch_and_commit_are_serialized_on_user_and_subject_locks():
    user = make_user()
    subject = make_subject(user, name="Original locked draft")
    expected_version = subject.version

    def patch_draft():
        updated = update_subject_draft(
            user_id=user.pk,
            subject_id=subject.pk,
            expected_version=expected_version,
            values={"name": "Concurrent patched draft"},
        )
        return ("patched", updated.version)

    def commit_draft():
        _, version = commit_subject_version(
            user_id=user.pk,
            subject_id=subject.pk,
            expected_version=expected_version,
            product_confirmations=[],
            request_id=uuid.uuid4(),
        )
        return ("committed", version.field_values["name"])

    results = parallel(patch_draft, commit_draft)
    successes = [item for item in results if isinstance(item, tuple)]
    conflicts = [item for item in results if isinstance(item, SubjectVersionConflict)]
    assert len(successes) == len(conflicts) == 1
    subject.refresh_from_db()
    if successes[0][0] == "patched":
        assert subject.draft_values["name"] == "Concurrent patched draft"
        assert subject.current_version_id is None
        assert not subject.versions.exists()
    else:
        assert successes[0] == ("committed", "Original locked draft")
        assert subject.current_version.field_values["name"] == "Original locked draft"
        assert subject.draft_values["name"] == "Original locked draft"
        assert list(subject.versions.values_list("version_no", flat=True)) == [1]


def test_raw_sql_rejects_gap_schema_mismatch_and_non_max_current_pointer():
    user = make_user()
    subject = make_subject(user)
    subject, first = commit(subject)
    with pytest.raises(DatabaseError), transaction.atomic():
        insert_raw_version(subject, 3)
    with pytest.raises(DatabaseError), transaction.atomic():
        insert_raw_version(subject, 2, schema_digest="f" * 64)

    subject = update_subject_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=subject.version,
        values={"name": "Version two"},
    )
    subject, second = commit(subject)
    assert second.version_no == 2
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subjects SET current_version_id=%s, version=version+1 WHERE id=%s",
                [str(first.pk), str(subject.pk)],
            )
            set_constraints_immediate()

    other = make_subject(make_user(), name="Other subject")
    other, other_version = commit(other)
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subjects SET current_version_id=%s, version=version+1 WHERE id=%s",
                [str(other_version.pk), str(subject.pk)],
            )
            set_constraints_immediate()


def test_deferred_chain_requires_official_name_current_max_and_bound_event():
    user = make_user()
    subject = make_subject(user)
    subject, _ = commit(subject)
    with pytest.raises(DatabaseError), transaction.atomic():
        insert_raw_version(subject, 2)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE subjects
                SET current_version_id=(
                    SELECT id FROM subject_versions WHERE subject_id=%s AND version_no=2
                ), retest_required=TRUE, version=version+1
                WHERE id=%s
                """,
                [str(subject.pk), str(subject.pk)],
            )
        set_constraints_immediate()
    assert list(subject.versions.values_list("version_no", flat=True)) == [1]


def test_version_name_product_and_event_evidence_is_immutable_by_raw_sql():
    user = make_user()
    subject = make_subject(user, product="Immutable product")
    _, version = commit(subject)
    name = version.names.get(role=SubjectName.Role.OFFICIAL_NAME)
    product = version.products.get()
    for table, row_id in (
        ("subject_versions", version.pk),
        ("subject_names", name.pk),
        ("subject_products", product.pk),
        ("subject_events", version.events.get().pk),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table} WHERE id=%s", [str(row_id)])
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subject_names SET display_value='tampered' WHERE id=%s", [str(name.pk)]
            )

    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subject_products SET display_value='tampered' WHERE id=%s",
                [str(product.pk)],
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subject_versions SET official_name='tampered' WHERE id=%s",
                [str(version.pk)],
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subject_events SET safe_summary='{}'::jsonb WHERE id=%s",
                [str(version.events.get().pk)],
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        SubjectProduct.objects.create(
            subject_version=version,
            candidate_key="f" * 64,
            display_value="Late product",
            matching_value="late product",
            source_field_key="late_product",
        )


def test_name_role_type_guard_rejects_invalid_machine_semantics():
    subject_type = SubjectType.objects.create(
        key=f"invalid_{uuid.uuid4().hex[:10]}",
        name="Invalid role type",
        status=SubjectType.Status.INACTIVE,
    )
    definition = SubjectFieldDefinition.objects.create(
        owner_subject_type=subject_type,
        field_key="invalid_official",
        field_type=SubjectFieldDefinition.FieldType.TEXTAREA,
        scope=SubjectFieldDefinition.Scope.CUSTOM,
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        SubjectTypeFieldConfig.objects.create(
            subject_type=subject_type,
            field_definition=definition,
            label="Invalid official",
            enabled=True,
            required=True,
            name_role=SubjectTypeFieldConfig.NameRole.OFFICIAL_NAME,
        )
        set_constraints_immediate()


@pytest.mark.parametrize(
    "failure_target",
    [
        "apps.subjects.version_services.SubjectVersion.objects.create",
        "apps.subjects.version_services.SubjectName.objects.bulk_create",
        "apps.subjects.version_services.SubjectProduct.objects.bulk_create",
        "apps.subjects.version_services.Subject.save",
        "apps.subjects.version_services.SubjectEvent.objects.create",
    ],
)
def test_commit_failure_injection_rolls_back_every_formal_fact(failure_target):
    user = make_user()
    subject = make_subject(user)
    with patch(failure_target, side_effect=RuntimeError("injected")):
        with pytest.raises(RuntimeError):
            commit(subject)
    subject.refresh_from_db()
    assert subject.current_version_id is None
    assert subject.retest_required is False
    assert not subject.versions.exists()
    assert not SubjectName.objects.exists()
    assert not SubjectProduct.objects.exists()
    assert not subject.events.filter(event_type=SubjectEvent.EventType.VERSION_COMMITTED).exists()


def test_migration_preflight_refuses_to_invent_semantics_for_existing_versions():
    user = make_user()
    subject = make_subject(user)
    commit(subject)
    with pytest.raises(RuntimeError, match="manual XW-0203 integrity review"):
        reject_existing_subject_versions(django_apps, None)
