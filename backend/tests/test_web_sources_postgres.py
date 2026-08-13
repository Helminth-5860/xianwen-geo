import time
import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from django_redis import get_redis_connection

from apps.web_sources.exceptions import WebSourceUnexpectedError
from apps.web_sources.models import (
    WebSourceEvent,
    WebSourceImport,
    WebSourceParsedVersion,
    WebSourceSnapshot,
)
from apps.web_sources.services import confirm_import
from apps.web_sources.tasks import execute_import_task
from tests.test_web_sources import _facts

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_real_dependencies():
    if connection.vendor != "postgresql":
        pytest.skip("run with scripts/test-web-import.* against PostgreSQL, Redis and web lab")
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


def _row(url="http://web-lab/"):
    user, subject = _facts()
    row = WebSourceImport.objects.create(
        user=user,
        subject=subject,
        canonical_url=url,
        display_url=url,
        has_query=False,
        hostname_fingerprint=uuid.uuid4().hex * 2,
        idempotency_key_digest=uuid.uuid4().hex * 2,
        request_digest=uuid.uuid4().hex * 2,
        request_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
    )
    return user, subject, row


def _wait(row, expected, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row.refresh_from_db()
        if row.status in expected:
            return row
        time.sleep(0.2)
    pytest.fail(f"web import remained {row.status}")


def test_real_isolated_worker_fetches_lab_with_postgres_and_redis():
    _, _, row = _row()
    execute_import_task.apply_async(
        args=[str(row.pk)],
        queue="web_fetch",
        headers={"request_id": str(uuid.uuid4()), "correlation_id": str(uuid.uuid4())},
    )
    _wait(row, {"succeeded", "failed"})
    assert row.status == "succeeded", row.stable_error_code
    assert row.snapshot.canonical_text == "Public lab page Safe public lab content"
    assert "must never execute" not in row.snapshot.canonical_text
    assert "metadata.invalid" not in row.snapshot.canonical_text


def test_commit_after_ack_redelivery_is_exactly_once():
    _, _, row = _row()
    execute_import_task.apply_async(args=[str(row.pk)], queue="web_fetch")
    _wait(row, {"succeeded"})
    execute_import_task.apply_async(args=[str(row.pk)], queue="web_fetch")
    time.sleep(1)
    row.refresh_from_db()
    assert row.status == "succeeded"
    assert WebSourceParsedVersion.objects.filter(import_record=row).count() == 1
    assert WebSourceEvent.objects.filter(import_record=row, event_type="succeeded").count() == 1


def test_database_rejects_terminal_recovery_delete_and_evidence_mutation():
    _, _, row = _row()
    execute_import_task.apply_async(args=[str(row.pk)], queue="web_fetch")
    _wait(row, {"succeeded"})
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("UPDATE web_source_imports SET status='queued' WHERE id=%s", [row.pk])
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM web_source_imports WHERE id=%s", [row.pk])
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE web_source_snapshots SET canonical_text='tampered' "
                "WHERE import_record_id=%s",
                [row.pk],
            )


def test_confirmation_pointer_is_monotonic_and_database_owned():
    user, _, row = _row()
    execute_import_task.apply_async(args=[str(row.pk)], queue="web_fetch")
    _wait(row, {"succeeded"})
    row.refresh_from_db()
    _, confirmed, created = confirm_import(
        user_id=user.pk,
        import_id=row.pk,
        expected_version=row.version,
        source_version_id=row.latest_parsed_version_id,
        confirmed_text="Reviewed public content",
        request_id=uuid.uuid4(),
    )
    assert created and confirmed.version_no == 2
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE web_source_imports SET latest_parsed_version_id=%s, "
                "version=version+1 WHERE id=%s",
                [confirmed.parent_version_id, row.pk],
            )


def test_finalization_failure_rolls_back_snapshot_version_event_and_notification(monkeypatch):
    from apps.web_sources import services

    _, _, row = _row()
    original = services.Notification.objects.create

    def fail_notification(*args, **kwargs):
        raise RuntimeError("safe injected failure")

    monkeypatch.setattr(services.Notification.objects, "create", fail_notification)
    with pytest.raises(WebSourceUnexpectedError):
        services.execute_import(import_id=row.pk)
    row.refresh_from_db()
    assert row.status == "fetching"
    assert not WebSourceSnapshot.objects.filter(import_record=row).exists()
    assert not WebSourceParsedVersion.objects.filter(import_record=row).exists()
    assert not WebSourceEvent.objects.filter(import_record=row, event_type="succeeded").exists()
    monkeypatch.setattr(services.Notification.objects, "create", original)


def test_guard_catalog_is_installed():
    expected = {
        "web_source_import_guard_trigger",
        "web_source_snapshot_guard_trigger",
        "web_source_parsed_guard_trigger",
        "web_source_event_guard_trigger",
        "web_source_import_pointer_constraint",
        "web_source_parsed_pointer_constraint",
        "web_source_snapshot_pointer_constraint",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(%s)",
            [list(expected)],
        )
        assert {row[0] for row in cursor.fetchall()} == expected
