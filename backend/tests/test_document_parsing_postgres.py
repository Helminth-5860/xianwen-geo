import time
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from django_redis import get_redis_connection

from apps.documents.parse_exceptions import DocumentParseStateConflict
from apps.documents.parse_models import (
    DocumentParsedVersion,
    DocumentParseEvent,
    DocumentParseJob,
    DocumentParseState,
)
from apps.documents.parse_services import (
    claim_parse_job,
    confirm_parsed_text,
    create_parse_job,
    due_parse_job_ids,
    execute_parse,
)
from apps.documents.storage import S3CompatibleStorageProvider
from apps.documents.tasks import execute_parse_job
from tests.subject_risk_helpers import install_empty_published_risk_catalog
from tests.test_documents_saga_postgres import (
    _complete_and_verify,
    _new_intent,
    _parallel,
    _provision,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def real_parse_dependencies():
    if connection.vendor != "postgresql":
        pytest.skip("run with scripts/test-files.* against PostgreSQL, Redis, MinIO and Celery")
    for command in ("sync_plan_catalog", "sync_subject_catalog", "sync_admin_rbac"):
        call_command(command, "--apply", verbosity=0)
    install_empty_published_risk_catalog()
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    S3CompatibleStorageProvider().client.head_bucket(Bucket=S3CompatibleStorageProvider().bucket)
    yield
    redis.flushdb()


def _completed_document(data=b"real parser worker text"):
    _, user, subject, _ = _provision(storage_bytes=16_384)
    intent, _ = _new_intent(user, subject, data)
    _complete_and_verify(user, intent)
    intent.refresh_from_db()
    return user, subject, intent.completed_version.document, intent.completed_version


def _job(data=b"real parser worker text"):
    user, subject, document, version = _completed_document(data)
    job, created = create_parse_job(
        user_id=user.pk,
        document_id=document.pk,
        document_version_id=version.pk,
        idempotency_key=f"parse-postgres-{uuid.uuid4()}",
        request_id=uuid.uuid4(),
    )
    assert created
    return user, subject, document, version, job


def _capture(operation):
    try:
        return operation()
    except Exception as exc:
        return exc


def test_file_processing_worker_consumes_real_private_object_task():
    _, _, _, version, job = _job()
    execute_parse_job.apply_async(
        args=[str(job.pk)],
        queue="file_processing",
        headers={"request_id": str(uuid.uuid4()), "correlation_id": str(uuid.uuid4())},
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job.refresh_from_db()
        if job.status == DocumentParseJob.Status.SUCCEEDED:
            break
        time.sleep(0.25)
    assert job.status == DocumentParseJob.Status.SUCCEEDED
    state = DocumentParseState.objects.get(document_version=version)
    assert state.latest_parsed_version.version_no == 1
    assert state.latest_parsed_version.extracted_text == "real parser worker text"


def test_concurrent_parse_requests_create_one_machine_chain():
    user, _, document, version = _completed_document()
    outcomes = _parallel(
        lambda: _capture(
            lambda: create_parse_job(
                user_id=user.pk,
                document_id=document.pk,
                document_version_id=version.pk,
                idempotency_key="parse-concurrent-key-0001",
                request_id=uuid.uuid4(),
            )
        ),
        lambda: _capture(
            lambda: create_parse_job(
                user_id=user.pk,
                document_id=document.pk,
                document_version_id=version.pk,
                idempotency_key="parse-concurrent-key-0002",
                request_id=uuid.uuid4(),
            )
        ),
    )
    assert DocumentParseJob.objects.filter(document_version=version).count() == 1
    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1
    assert any(isinstance(outcome, DocumentParseStateConflict) for outcome in outcomes)


def test_concurrent_confirmation_is_continuous_and_exactly_once():
    user, _, document, version, job = _job()
    assert execute_parse(job_id=job.pk)["status"] == "succeeded"
    state = DocumentParseState.objects.get(document_version=version)
    source_id = state.latest_parsed_version_id
    outcomes = _parallel(
        lambda: confirm_parsed_text(
            user_id=user.pk,
            document_id=document.pk,
            expected_parse_state_version=state.version,
            source_parsed_version_id=source_id,
            confirmed_text="same confirmation",
            request_id=uuid.uuid4(),
        ),
        lambda: confirm_parsed_text(
            user_id=user.pk,
            document_id=document.pk,
            expected_parse_state_version=state.version,
            source_parsed_version_id=source_id,
            confirmed_text="same confirmation",
            request_id=uuid.uuid4(),
        ),
    )
    assert DocumentParsedVersion.objects.filter(source="user_confirmation").count() == 1
    assert DocumentParseEvent.objects.filter(event_type="confirmed").count() == 1
    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) >= 1


def test_raw_sql_rejects_history_mutation_delete_gap_and_pointer_rollback():
    _, _, _, version, job = _job()
    assert execute_parse(job_id=job.pk)["status"] == "succeeded"
    state = DocumentParseState.objects.get(document_version=version)
    parsed = state.latest_parsed_version
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE document_parsed_versions SET extracted_text = %s WHERE id = %s",
            ["tampered", parsed.pk],
        )
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM document_parsed_versions WHERE id = %s", [parsed.pk])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO document_parsed_versions
            (id, user_id, subject_id, document_id, document_version_id, version_no,
             source, extracted_text, tables_json, warning_codes, parser_key,
             parser_version, ocr_provider_key, ocr_engine_version, content_digest, created_at)
            VALUES (%s,%s,%s,%s,%s,3,'parser','gap','[]','[]','txt','1','','',%s,now())
            """,
            [
                uuid.uuid4(),
                parsed.user_id,
                parsed.subject_id,
                parsed.document_id,
                parsed.document_version_id,
                "a" * 64,
            ],
        )
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE document_parse_states SET latest_parsed_version_id = NULL WHERE id = %s",
            [state.pk],
        )


def test_event_notification_or_state_failure_rolls_back_machine_finalization():
    _, _, _, version, job = _job()
    create_event = DocumentParseEvent.objects.create

    def fail_succeeded_event(**kwargs):
        if kwargs.get("event_type") == DocumentParseEvent.EventType.SUCCEEDED:
            raise RuntimeError("injected")
        return create_event(**kwargs)

    with patch.object(DocumentParseEvent.objects, "create", side_effect=fail_succeeded_event):
        with pytest.raises(RuntimeError):
            execute_parse(job_id=job.pk)
    job.refresh_from_db()
    state = DocumentParseState.objects.get(document_version=version)
    assert job.status == DocumentParseJob.Status.RUNNING
    assert state.latest_parsed_version_id is None
    assert not DocumentParsedVersion.objects.filter(document_version=version).exists()


def test_redelivery_reads_postgresql_terminal_fact_and_is_noop():
    _, _, _, version, job = _job()
    assert execute_parse(job_id=job.pk)["status"] == "succeeded"
    counts = (
        DocumentParsedVersion.objects.filter(document_version=version).count(),
        DocumentParseEvent.objects.filter(document_version=version).count(),
    )
    assert execute_parse(job_id=job.pk)["status"] == "not_due_or_terminal"
    assert counts == (
        DocumentParsedVersion.objects.filter(document_version=version).count(),
        DocumentParseEvent.objects.filter(document_version=version).count(),
    )


def test_stale_running_job_is_reclaimed_with_new_generation():
    _, _, _, _, job = _job()
    first_claim = claim_parse_job(job_id=job.pk)
    assert first_claim is not None
    job.refresh_from_db()
    first_generation = job.generation

    job.started_at = timezone.now() - timedelta(
        seconds=settings.DOCUMENT_PARSE_RUNNING_STALE_SECONDS + 1
    )
    job.save(update_fields=("started_at", "updated_at"))
    assert job.pk in due_parse_job_ids()

    second_claim = claim_parse_job(job_id=job.pk)
    assert second_claim is not None
    job.refresh_from_db()
    assert job.status == DocumentParseJob.Status.RUNNING
    assert job.attempts == 2
    assert job.generation != first_generation
