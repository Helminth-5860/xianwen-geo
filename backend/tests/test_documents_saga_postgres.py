import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.test import override_settings
from django.utils import timezone
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.permissions import resolve_admin_context
from apps.documents.exceptions import (
    FileContentInvalid,
    FileIdempotencyConflict,
    FileStateConflict,
    FileStorageUnavailable,
)
from apps.documents.models import (
    DocumentVersion,
    FileStorageAllocation,
    FileUploadIntent,
    SubjectVersionDocumentReference,
    UserDocument,
)
from apps.documents.services import (
    complete_upload_intent,
    create_download_intent,
    create_upload_intent,
    expire_upload_intent,
    validate_document_references,
    verify_upload_intent,
)
from apps.documents.storage import S3CompatibleStorageProvider
from apps.plans.lifecycle import expire_subscription
from apps.plans.services import (
    create_plan,
    create_plan_version,
    publish_plan_version,
    update_plan_version,
)
from apps.plans.subscription_services import activate_application, grant_trial
from apps.quotas.models import (
    QuotaAccount,
    QuotaHoldGroup,
    QuotaLedgerEntry,
)
from apps.subjects.models import (
    SubjectEvent,
    SubjectFieldDefinition,
    SubjectName,
    SubjectProduct,
    SubjectReview,
    SubjectRiskAssessment,
    SubjectType,
    SubjectVersion,
)
from apps.subjects.risk_services import decide_review
from apps.subjects.services import create_custom_field
from apps.subjects.subject_services import create_subject, update_subject_draft
from apps.subjects.version_services import commit_subject_version
from apps.users.models import User
from tests.subject_risk_helpers import install_empty_published_risk_catalog
from tests.test_subscriptions import PASSWORD, _plan_limit_value, application_for

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def real_dependencies():
    if connection.vendor != "postgresql":
        pytest.skip("run with scripts/test-files.* against PostgreSQL, Redis and MinIO")
    for command in ("sync_plan_catalog", "sync_subject_catalog", "sync_admin_rbac"):
        call_command(command, "--apply", verbosity=0)
    install_empty_published_risk_catalog()
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    provider = S3CompatibleStorageProvider()
    provider.client.head_bucket(Bucket=provider.bucket)
    yield
    redis.flushdb()


def _request(user):
    return SimpleNamespace(user=user, request_id=str(uuid.uuid4()), META={})


def _provision(*, storage_bytes=4096, file_field=False, trial=True):
    suffix = uuid.uuid4().hex[:8]
    admin = User.objects.create_superuser(
        phone=f"139{uuid.uuid4().int % 100000000:08d}",
        nickname="File administrator",
        password=PASSWORD,
    )
    user = User.objects.create_user(
        phone=f"138{uuid.uuid4().int % 100000000:08d}",
        nickname="File customer",
        password=PASSWORD,
    )
    plan = create_plan(
        plan_id=uuid.uuid4(),
        actor=admin,
        data={
            "code": f"file-trial-{suffix}",
            "name": "File trial",
            "description": "File Saga acceptance plan",
            "price_display_mode": "fixed",
            "display_price": "0.00",
            "is_trial": trial,
            "sort_order": 1,
        },
    )
    version = create_plan_version(
        plan_id=plan.pk,
        actor=admin,
        expected_plan_version=plan.version,
    )
    limits = [
        {
            "key": item.limit_key,
            "value": storage_bytes
            if item.limit_key == "storage_bytes"
            else _plan_limit_value(item),
        }
        for item in version.limits.all()
    ]
    version = update_plan_version(
        version_id=version.pk,
        actor=admin,
        expected_version=version.version,
        valid_days=version.valid_days,
        queue_priority=version.queue_priority,
        limits=limits,
        model_permissions=[
            {
                "model_key": item.model_key,
                "sort_order": item.sort_order,
                "selected_by_default": item.selected_by_default,
            }
            for item in version.model_permissions.all()
        ],
    )
    publish_plan_version(
        version_id=version.pk,
        actor=admin,
        expected_version=version.version,
        confirm_informal_composite=True,
    )
    plan.refresh_from_db()
    if trial:
        subscription = grant_trial(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            user_id=user.pk,
            expected_status_version=user.status_version,
            plan_id=plan.pk,
            opening_note="",
            request_id=uuid.uuid4(),
        )
    else:
        application = application_for(user, plan, version)
        subscription, _, _ = activate_application(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            application_id=application.pk,
            expected_version=application.version,
            selected_plan_version_id=None,
            confirm_unavailable=False,
            unavailable_reason="",
            confirm_version_override=False,
            override_reason="",
            opening_note="",
            request_id=uuid.uuid4(),
        )
    subject_type = SubjectType.objects.get(key="enterprise")
    if file_field:
        create_custom_field(
            request=_request(admin),
            subject_type_id=subject_type.pk,
            data={
                "expected_schema_version": subject_type.schema_version,
                "field_key": "supporting_file",
                "field_type": SubjectFieldDefinition.FieldType.FILE,
                "label": "Supporting file",
                "enabled": True,
                "required": False,
                "used_for_ai": False,
                "name_role": "none",
            },
        )
        subject_type.refresh_from_db()
    subject = create_subject(
        user_id=user.pk,
        subject_type_id=subject_type.pk,
        expected_schema_version=subject_type.schema_version,
        initial_values={"name": "File subject"},
        request_id=uuid.uuid4(),
    )
    account = QuotaAccount.objects.get(
        subscription=subscription,
        quota_type="storage_bytes",
        batch_type=QuotaAccount.BatchType.PRIMARY,
    )
    return admin, user, subject, account


def _new_intent(user, subject, data=b"safe text", *, key=None):
    created = create_upload_intent(
        user_id=user.pk,
        subject_id=subject.pk,
        filename="evidence.txt",
        content_type="text/plain",
        declared_size=max(len(data), 1),
        idempotency_key=key or f"file-intent-{uuid.uuid4()}",
        request_id=uuid.uuid4(),
    )
    provider = S3CompatibleStorageProvider()
    provider.client.put_object(
        Bucket=provider.bucket,
        Key=created.intent.staging_key,
        Body=data,
        ContentType="text/plain",
    )
    return created.intent, provider


def _complete_and_verify(user, intent):
    with patch("apps.documents.tasks.verify_upload_intent.apply_async") as enqueue:
        accepted = complete_upload_intent(
            user=user,
            intent_id=intent.pk,
            expected_version=intent.version,
            request_id=uuid.uuid4(),
        )
    assert accepted.status == FileUploadIntent.Status.VERIFYING
    assert enqueue.call_count == 1
    assert enqueue.call_args.kwargs["headers"].keys() == {"request_id", "correlation_id"}
    return verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4())


def _parallel(*operations):
    barrier = threading.Barrier(len(operations))

    def run(operation):
        close_old_connections()
        barrier.wait()
        try:
            return operation()
        except Exception as exc:  # evidence records both racing outcomes
            return exc
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(operations)) as executor:
        return [future.result(timeout=30) for future in map(executor.submit, operations)]


def test_real_minio_saga_completes_once_and_settles_declared_hold():
    _, user, subject, account = _provision()
    intent, provider = _new_intent(user, subject, b"safe text")
    account.refresh_from_db()
    assert account.frozen == intent.declared_size

    assert _complete_and_verify(user, intent) == FileUploadIntent.Status.COMPLETED
    intent.refresh_from_db()
    account.refresh_from_db()
    group = QuotaHoldGroup.objects.get(pk=intent.quota_hold_group_id)
    assert group.status == QuotaHoldGroup.Status.SETTLED
    assert group.consumed_amount == intent.declared_size
    assert group.released_amount == 0
    assert account.frozen == 0
    assert (
        FileStorageAllocation.objects.filter(document_version=intent.completed_version).count() == 1
    )
    assert (
        QuotaLedgerEntry.objects.filter(
            business_type="file_upload", business_id=intent.pk, action="consume"
        ).count()
        == 1
    )

    assert verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()) == "completed"
    assert UserDocument.objects.count() == 1
    assert DocumentVersion.objects.count() == 1
    assert FileStorageAllocation.objects.count() == 1
    url, expires_in = create_download_intent(
        user=user, document_id=intent.completed_version.document_id
    )
    assert url.startswith(("http://", "https://"))
    assert expires_in > 0
    assert "response-cache-control" in url.lower()
    provider.client.head_object(Bucket=provider.bucket, Key=intent.final_key)


def test_complete_concurrency_dispatches_and_materializes_exactly_once():
    _, user, subject, _ = _provision()
    intent, _ = _new_intent(user, subject)
    with patch("apps.documents.tasks.verify_upload_intent.apply_async") as enqueue:
        results = _parallel(
            lambda: complete_upload_intent(
                user=User.objects.get(pk=user.pk),
                intent_id=intent.pk,
                expected_version=1,
                request_id=uuid.uuid4(),
            ),
            lambda: complete_upload_intent(
                user=User.objects.get(pk=user.pk),
                intent_id=intent.pk,
                expected_version=1,
                request_id=uuid.uuid4(),
            ),
        )
    assert all(isinstance(item, FileUploadIntent) for item in results)
    assert enqueue.call_count == 1
    verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4())
    assert UserDocument.objects.count() == 1
    assert FileStorageAllocation.objects.count() == 1


def test_final_object_survives_db_failure_and_retry_does_not_double_consume():
    _, user, subject, account = _provision()
    intent, provider = _new_intent(user, subject)
    with patch("apps.documents.tasks.verify_upload_intent.apply_async"):
        complete_upload_intent(
            user=user,
            intent_id=intent.pk,
            expected_version=1,
            request_id=uuid.uuid4(),
        )
    with (
        patch(
            "apps.documents.services.UserDocument.objects.create",
            side_effect=DatabaseError("injected final transaction failure"),
        ),
        pytest.raises(DatabaseError),
    ):
        verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4())
    intent.refresh_from_db()
    account.refresh_from_db()
    assert intent.status == FileUploadIntent.Status.VERIFYING
    assert account.frozen == intent.declared_size
    assert not UserDocument.objects.exists()
    assert not FileStorageAllocation.objects.exists()
    provider.client.head_object(Bucket=provider.bucket, Key=intent.final_key)

    assert verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()) == "completed"
    assert UserDocument.objects.count() == 1
    assert FileStorageAllocation.objects.count() == 1
    assert (
        QuotaLedgerEntry.objects.filter(
            business_type="file_upload", business_id=intent.pk, action="consume"
        ).count()
        == 1
    )


def test_temporary_scanner_failure_stays_verifying_without_file_facts():
    _, user, subject, account = _provision()
    payload = b"XW-SCANNER-UNAVAILABLE safe text"
    intent, _ = _new_intent(user, subject, payload)
    with patch("apps.documents.tasks.verify_upload_intent.apply_async"):
        complete_upload_intent(
            user=user,
            intent_id=intent.pk,
            expected_version=1,
            request_id=uuid.uuid4(),
        )
    assert verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()) == "verifying"
    intent.refresh_from_db()
    account.refresh_from_db()
    assert intent.status == FileUploadIntent.Status.VERIFYING
    assert intent.next_attempt_at is not None
    assert intent.stable_error_code == "SCANNER_UNAVAILABLE"
    assert account.frozen == len(payload)
    assert not UserDocument.objects.exists()
    assert not FileStorageAllocation.objects.exists()


@override_settings(FILE_STAGING_RETENTION_SECONDS=1)
def test_expiry_releases_hold_once_and_cannot_race_back_to_verifying():
    _, user, subject, account = _provision()
    intent, _ = _new_intent(user, subject)
    time.sleep(1.1)
    assert expire_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()) is True
    assert expire_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()) is False
    intent.refresh_from_db()
    account.refresh_from_db()
    group = QuotaHoldGroup.objects.get(pk=intent.quota_hold_group_id)
    assert intent.status == FileUploadIntent.Status.EXPIRED
    assert group.status == QuotaHoldGroup.Status.SETTLED
    assert group.released_amount == intent.declared_size
    assert account.frozen == 0
    with patch("apps.documents.tasks.verify_upload_intent.apply_async") as enqueue:
        completed = complete_upload_intent(
            user=user,
            intent_id=intent.pk,
            expected_version=intent.version,
            request_id=uuid.uuid4(),
        )
    assert completed.status == FileUploadIntent.Status.EXPIRED
    enqueue.assert_not_called()


def test_upload_idempotency_replays_without_raw_key_and_conflicts_on_payload():
    _, user, subject, _ = _provision()
    raw_key = f"raw-file-key-{uuid.uuid4()}"
    first = create_upload_intent(
        user_id=user.pk,
        subject_id=subject.pk,
        filename="safe.txt",
        content_type="text/plain",
        declared_size=10,
        idempotency_key=raw_key,
        request_id=uuid.uuid4(),
    )
    second = create_upload_intent(
        user_id=user.pk,
        subject_id=subject.pk,
        filename="safe.txt",
        content_type="text/plain",
        declared_size=10,
        idempotency_key=raw_key,
        request_id=uuid.uuid4(),
    )
    assert first.intent.pk == second.intent.pk
    assert raw_key not in first.intent.idempotency_key_digest
    assert raw_key not in first.intent.request_digest
    with pytest.raises(FileIdempotencyConflict):
        create_upload_intent(
            user_id=user.pk,
            subject_id=subject.pk,
            filename="different.txt",
            content_type="text/plain",
            declared_size=10,
            idempotency_key=raw_key,
            request_id=uuid.uuid4(),
        )


def test_subject_version_creates_immutable_file_reference_and_raw_guards():
    _, user, subject, _ = _provision(file_field=True)
    intent, _ = _new_intent(user, subject)
    _complete_and_verify(user, intent)
    intent.refresh_from_db()
    subject = update_subject_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=subject.version,
        values={"supporting_file": {"document_version_id": str(intent.completed_version_id)}},
    )
    subject, version = commit_subject_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=subject.version,
        product_confirmations=[],
        request_id=uuid.uuid4(),
    )
    reference = SubjectVersionDocumentReference.objects.get(subject_version=version)
    assert reference.field_key == "supporting_file"
    assert reference.document_version_id == intent.completed_version_id

    guarded = (
        (
            "document_versions",
            intent.completed_version_id,
            "UPDATE document_versions SET size_bytes=size_bytes+1 WHERE id=%s",
        ),
        (
            "file_storage_allocations",
            intent.completed_version.storage_allocation.pk,
            "DELETE FROM file_storage_allocations WHERE id=%s",
        ),
        (
            "subject_version_document_references",
            reference.pk,
            "UPDATE subject_version_document_references SET field_key='changed' WHERE id=%s",
        ),
        (
            "subject_version_document_references",
            reference.pk,
            "DELETE FROM subject_version_document_references WHERE id=%s",
        ),
    )
    for _table, row_id, sql in guarded:
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, [row_id])

    second_subject = create_subject(
        user_id=user.pk,
        subject_type_id=subject.subject_type_id,
        expected_schema_version=subject.schema_version,
        initial_values={"name": "Second file subject"},
        request_id=uuid.uuid4(),
    )
    second_intent, _ = _new_intent(user, second_subject, b"second subject file")
    _complete_and_verify(user, second_intent)
    second_intent.refresh_from_db()
    second_subject = update_subject_draft(
        user_id=user.pk,
        subject_id=second_subject.pk,
        expected_version=second_subject.version,
        values={
            "supporting_file": {"document_version_id": str(second_intent.completed_version_id)}
        },
    )
    _, second_version = commit_subject_version(
        user_id=user.pk,
        subject_id=second_subject.pk,
        expected_version=second_subject.version,
        product_confirmations=[],
        request_id=uuid.uuid4(),
    )
    assert SubjectVersionDocumentReference.objects.filter(
        subject_version=second_version,
        document_version_id=second_intent.completed_version_id,
    ).exists()
    insert_sql = (
        "INSERT INTO subject_version_document_references "
        "(id, subject_version_id, field_key, document_version_id, created_at) "
        "VALUES (%s, %s, %s, %s, %s)"
    )
    for document_version_id in (
        intent.completed_version_id,
        second_intent.completed_version_id,
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    insert_sql,
                    [
                        uuid.uuid4(),
                        version.pk,
                        "supporting_file",
                        document_version_id,
                        timezone.now(),
                    ],
                )


@pytest.mark.parametrize(
    "failure_point",
    ("document_version", "allocation", "quota_consume", "intent_completed_save"),
)
def test_final_copy_database_failure_points_retry_exactly_once(failure_point):
    _, user, subject, account = _provision()
    payload = b"safe retry evidence"
    intent, provider = _new_intent(user, subject, payload)
    with patch("apps.documents.tasks.verify_upload_intent.apply_async"):
        complete_upload_intent(
            user=user,
            intent_id=intent.pk,
            expected_version=1,
            request_id=uuid.uuid4(),
        )

    original_intent_save = FileUploadIntent.save

    def fail_completed_save(instance, *args, **kwargs):
        if instance.status == FileUploadIntent.Status.COMPLETED:
            raise DatabaseError("injected intent completion failure")
        return original_intent_save(instance, *args, **kwargs)

    targets = {
        "document_version": patch.object(
            DocumentVersion.objects,
            "create",
            side_effect=DatabaseError("injected document version failure"),
        ),
        "allocation": patch.object(
            FileStorageAllocation.objects,
            "create",
            side_effect=DatabaseError("injected allocation failure"),
        ),
        "quota_consume": patch(
            "apps.documents.services.consume_hold",
            side_effect=DatabaseError("injected quota consume failure"),
        ),
        "intent_completed_save": patch.object(
            FileUploadIntent,
            "save",
            new=fail_completed_save,
        ),
    }
    with targets.get(failure_point, nullcontext()), pytest.raises(DatabaseError):
        verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4())

    intent.refresh_from_db()
    account.refresh_from_db()
    group = QuotaHoldGroup.objects.get(pk=intent.quota_hold_group_id)
    assert intent.status == FileUploadIntent.Status.VERIFYING
    assert group.status != QuotaHoldGroup.Status.SETTLED
    assert account.frozen == intent.declared_size
    assert not UserDocument.objects.exists()
    assert not DocumentVersion.objects.exists()
    assert not FileStorageAllocation.objects.exists()
    assert not QuotaLedgerEntry.objects.filter(
        business_type="file_upload", business_id=intent.pk, action="consume"
    ).exists()
    provider.client.head_object(Bucket=provider.bucket, Key=intent.final_key)

    assert verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()) == "completed"
    intent.refresh_from_db()
    account.refresh_from_db()
    group.refresh_from_db()
    assert group.status == QuotaHoldGroup.Status.SETTLED
    assert account.frozen == 0
    assert UserDocument.objects.count() == 1
    assert DocumentVersion.objects.count() == 1
    assert FileStorageAllocation.objects.count() == 1
    assert (
        QuotaLedgerEntry.objects.filter(
            business_type="file_upload", business_id=intent.pk, action="consume"
        ).count()
        == 1
    )


@pytest.mark.parametrize("mismatch", ("size", "sha256", "content_type"))
def test_existing_final_object_mismatch_fails_closed_without_formal_facts(mismatch):
    _, user, subject, account = _provision()
    payload = b"safe mismatch evidence"
    intent, provider = _new_intent(user, subject, payload)
    with patch("apps.documents.tasks.verify_upload_intent.apply_async"):
        complete_upload_intent(
            user=user,
            intent_id=intent.pk,
            expected_version=1,
            request_id=uuid.uuid4(),
        )
    final_payload = b"wrong-size" if mismatch == "size" else payload
    expected_sha = hashlib.sha256(payload).hexdigest()
    metadata_sha = "0" * 64 if mismatch == "sha256" else expected_sha
    content_type = "application/pdf" if mismatch == "content_type" else "text/plain"
    provider.client.put_object(
        Bucket=provider.bucket,
        Key=intent.final_key,
        Body=final_payload,
        ContentType=content_type,
        Metadata={"sha256": metadata_sha},
    )

    assert verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()) == "verifying"
    intent.refresh_from_db()
    account.refresh_from_db()
    assert intent.status == FileUploadIntent.Status.VERIFYING
    assert intent.stable_error_code == "FILE_STORAGE_UNAVAILABLE"
    assert account.frozen == intent.declared_size
    assert not UserDocument.objects.exists()
    assert not DocumentVersion.objects.exists()
    assert not FileStorageAllocation.objects.exists()
    assert not QuotaLedgerEntry.objects.filter(
        business_type="file_upload", business_id=intent.pk, action="consume"
    ).exists()


@override_settings(FILE_STAGING_RETENTION_SECONDS=1)
def test_complete_and_expiry_scanner_real_race_has_one_legal_terminal_path():
    _, user, subject, account = _provision()
    intent, _ = _new_intent(user, subject)
    time.sleep(1.1)

    def complete_or_conflict():
        try:
            return complete_upload_intent(
                user=User.objects.get(pk=user.pk),
                intent_id=intent.pk,
                expected_version=1,
                request_id=uuid.uuid4(),
            )
        except FileStateConflict as exc:
            return exc

    with patch("apps.documents.tasks.verify_upload_intent.apply_async") as enqueue:
        results = _parallel(
            complete_or_conflict,
            lambda: expire_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()),
        )
    intent.refresh_from_db()
    account.refresh_from_db()
    group = QuotaHoldGroup.objects.get(pk=intent.quota_hold_group_id)
    assert intent.status == FileUploadIntent.Status.EXPIRED
    assert sum(item is True for item in results) == 1
    assert any(isinstance(item, FileStateConflict) for item in results)
    assert enqueue.call_count == 0
    assert group.status == QuotaHoldGroup.Status.SETTLED
    assert account.frozen == 0


@override_settings(FILE_STAGING_RETENTION_SECONDS=1)
@pytest.mark.parametrize("terminal_status", ("completed", "rejected", "expired"))
def test_terminal_upload_intent_cannot_be_restored_by_raw_sql(terminal_status):
    _, user, subject, _ = _provision()
    payload = b"XW-MALWARE-TEST unsafe" if terminal_status == "rejected" else b"safe terminal"
    intent, _ = _new_intent(user, subject, payload)
    if terminal_status == "expired":
        time.sleep(1.1)
        assert expire_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()) is True
    else:
        with patch("apps.documents.tasks.verify_upload_intent.apply_async"):
            complete_upload_intent(
                user=user,
                intent_id=intent.pk,
                expected_version=1,
                request_id=uuid.uuid4(),
            )
        verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4())
    intent.refresh_from_db()
    assert intent.status == terminal_status
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE file_upload_intents SET status='pending_upload', "
                "version=version+1 WHERE id=%s",
                [intent.pk],
            )


@pytest.mark.parametrize(
    ("declared_size", "payload", "expected_status", "consumed", "released"),
    ((10, b"safe", "completed", 4, 6), (4, b"12345", "rejected", 0, 4)),
)
def test_actual_size_settles_declared_hold_without_expanding_freeze(
    declared_size, payload, expected_status, consumed, released
):
    _, user, subject, account = _provision()
    created = create_upload_intent(
        user_id=user.pk,
        subject_id=subject.pk,
        filename="evidence.txt",
        content_type="text/plain",
        declared_size=declared_size,
        idempotency_key=f"file-size-delta-{uuid.uuid4()}",
        request_id=uuid.uuid4(),
    )
    intent = created.intent
    provider = S3CompatibleStorageProvider()
    provider.client.put_object(
        Bucket=provider.bucket,
        Key=intent.staging_key,
        Body=payload,
        ContentType="text/plain",
    )
    with patch("apps.documents.tasks.verify_upload_intent.apply_async"):
        complete_upload_intent(
            user=user,
            intent_id=intent.pk,
            expected_version=1,
            request_id=uuid.uuid4(),
        )
    assert verify_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()) == expected_status
    intent.refresh_from_db()
    account.refresh_from_db()
    group = QuotaHoldGroup.objects.get(pk=intent.quota_hold_group_id)
    assert intent.status == expected_status
    assert group.status == QuotaHoldGroup.Status.SETTLED
    assert group.consumed_amount == consumed
    assert group.released_amount == released
    assert account.frozen == 0
    assert UserDocument.objects.count() == (1 if expected_status == "completed" else 0)
    assert FileStorageAllocation.objects.count() == (1 if expected_status == "completed" else 0)


def test_private_download_owner_scope_survives_subscription_expiry_and_hides_internal_facts():
    _, user, subject, account = _provision()
    intent, _ = _new_intent(user, subject)
    _complete_and_verify(user, intent)
    intent.refresh_from_db()
    document_id = intent.completed_version.document_id
    owner = APIClient()
    owner.force_authenticate(user)
    allowed = owner.post(f"/api/v1/documents/{document_id}/download-intents", {}, format="json")
    assert allowed.status_code == 200
    assert allowed["Cache-Control"] == "no-store"
    data = allowed.json()["data"]
    assert set(data) == {"url", "expires_in"}
    serialized = allowed.content.decode()
    for hidden in (
        intent.staging_key,
        intent.completed_version.sha256,
        "etag",
        "scanner",
    ):
        assert hidden not in serialized

    outsider = User.objects.create_user(
        phone=f"136{uuid.uuid4().int % 100000000:08d}",
        nickname="Download outsider",
        password=PASSWORD,
    )
    denied = APIClient()
    denied.force_authenticate(outsider)
    assert (
        denied.post(
            f"/api/v1/documents/{document_id}/download-intents", {}, format="json"
        ).status_code
        == 404
    )

    subscription = account.subscription
    expire_subscription(
        subscription_id=subscription.pk,
        request_id=uuid.uuid4(),
        now=subscription.ends_at + timedelta(seconds=1),
    )
    assert (
        owner.post(
            f"/api/v1/documents/{document_id}/download-intents", {}, format="json"
        ).status_code
        == 200
    )
    assert owner.get(f"/api/v1/subjects/{subject.pk}/documents").status_code == 200


def test_noncompleted_intent_never_has_downloadable_document_identity():
    _, user, subject, _ = _provision()
    pending, _ = _new_intent(user, subject)
    rejected, _ = _new_intent(user, subject, b"XW-MALWARE-TEST unsafe")
    with patch("apps.documents.tasks.verify_upload_intent.apply_async"):
        complete_upload_intent(
            user=user,
            intent_id=rejected.pk,
            expected_version=1,
            request_id=uuid.uuid4(),
        )
    assert verify_upload_intent(intent_id=rejected.pk, request_id=uuid.uuid4()) == "rejected"
    client = APIClient()
    client.force_authenticate(user)
    for intent in (pending, rejected):
        intent.refresh_from_db()
        assert intent.completed_version_id is None
        assert (
            client.post(
                f"/api/v1/documents/{intent.pk}/download-intents", {}, format="json"
            ).status_code
            == 404
        )


@override_settings(FILE_STAGING_RETENTION_SECONDS=1, FILE_UPLOAD_URL_TTL=1)
def test_cleanup_retry_does_not_roll_back_or_repeat_expiry_quota_release(monkeypatch):
    _, user, subject, account = _provision()
    intent, provider = _new_intent(user, subject)
    time.sleep(1.1)
    assert expire_upload_intent(intent_id=intent.pk, request_id=uuid.uuid4()) is True
    intent.refresh_from_db()
    account.refresh_from_db()
    group = QuotaHoldGroup.objects.get(pk=intent.quota_hold_group_id)
    assert group.status == QuotaHoldGroup.Status.SETTLED
    assert group.released_amount == intent.declared_size
    assert account.frozen == 0

    original_delete = provider.delete_temporary_object
    calls = 0

    def fail_once(key):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FileStorageUnavailable
        return original_delete(key)

    monkeypatch.setattr(provider, "delete_temporary_object", fail_once)
    monkeypatch.setattr(
        "apps.documents.management.commands.reconcile_file_objects.storage_provider",
        lambda: provider,
    )
    with pytest.raises(FileStorageUnavailable):
        call_command(
            "reconcile_file_objects", "--apply", "--batch-size=1", "--minimum-age-seconds=1"
        )
    intent.refresh_from_db()
    group.refresh_from_db()
    assert intent.staging_cleanup_pending is True
    assert group.released_amount == intent.declared_size
    call_command("reconcile_file_objects", "--apply", "--batch-size=1", "--minimum-age-seconds=1")
    intent.refresh_from_db()
    group.refresh_from_db()
    assert intent.staging_cleanup_pending is False
    assert group.released_amount == intent.declared_size


@override_settings(FILE_UPLOAD_URL_TTL=1)
def test_orphan_cleanup_preserves_referenced_and_retrying_final_objects(monkeypatch):
    _, user, subject, _ = _provision()
    completed, provider = _new_intent(user, subject, b"completed safe")
    _complete_and_verify(user, completed)
    retrying, _ = _new_intent(user, subject, b"retry candidate")
    with patch("apps.documents.tasks.verify_upload_intent.apply_async"):
        complete_upload_intent(
            user=user,
            intent_id=retrying.pk,
            expected_version=1,
            request_id=uuid.uuid4(),
        )
    with (
        patch.object(
            UserDocument.objects, "create", side_effect=DatabaseError("retry candidate failure")
        ),
        pytest.raises(DatabaseError),
    ):
        verify_upload_intent(intent_id=retrying.pk, request_id=uuid.uuid4())
    time.sleep(1.1)
    monkeypatch.setattr(
        "apps.documents.management.commands.reconcile_file_objects.storage_provider",
        lambda: provider,
    )
    call_command("reconcile_file_objects", "--apply", "--batch-size=10", "--minimum-age-seconds=1")
    provider.client.head_object(Bucket=provider.bucket, Key=completed.final_key)
    provider.client.head_object(Bucket=provider.bucket, Key=retrying.final_key)


def test_dynamic_file_reference_rejects_shape_owner_subject_and_image_kind():
    _, user, subject, _ = _provision()
    intent, _ = _new_intent(user, subject, b"safe file")
    _complete_and_verify(user, intent)
    intent.refresh_from_db()
    version = intent.completed_version
    file_schema = {"fields": [{"field_key": "proof", "field_type": "file"}]}
    image_schema = {"fields": [{"field_key": "photo", "field_type": "image"}]}
    assert validate_document_references(
        user_id=user.pk,
        subject_id=subject.pk,
        schema_snapshot=file_schema,
        field_values={"proof": {"document_version_id": str(version.pk)}},
    ) == [("proof", version)]
    for invalid in (
        {"proof": "https://files.example/object"},
        {"proof": {"bucket": "private", "key": "objects/opaque"}},
        {"proof": {"document_version_id": str(version.document_id)}},
    ):
        with pytest.raises(FileContentInvalid):
            validate_document_references(
                user_id=user.pk,
                subject_id=subject.pk,
                schema_snapshot=file_schema,
                field_values=invalid,
            )
    with pytest.raises(FileContentInvalid):
        validate_document_references(
            user_id=user.pk,
            subject_id=subject.pk,
            schema_snapshot=image_schema,
            field_values={"photo": {"document_version_id": str(version.pk)}},
        )

    _, foreign_user, foreign_subject, _ = _provision()
    foreign_intent, _ = _new_intent(foreign_user, foreign_subject, b"foreign safe")
    _complete_and_verify(foreign_user, foreign_intent)
    foreign_intent.refresh_from_db()
    with pytest.raises(FileContentInvalid):
        validate_document_references(
            user_id=user.pk,
            subject_id=subject.pk,
            schema_snapshot=file_schema,
            field_values={
                "proof": {"document_version_id": str(foreign_intent.completed_version_id)}
            },
        )
    with pytest.raises(FileContentInvalid):
        validate_document_references(
            user_id=foreign_user.pk,
            subject_id=subject.pk,
            schema_snapshot=file_schema,
            field_values={"proof": {"document_version_id": str(version.pk)}},
        )


def test_reference_failure_rolls_back_entire_subject_version_commit():
    _, user, subject, _ = _provision(file_field=True)
    intent, _ = _new_intent(user, subject)
    _complete_and_verify(user, intent)
    intent.refresh_from_db()
    subject = update_subject_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=subject.version,
        values={"supporting_file": {"document_version_id": str(intent.completed_version_id)}},
    )
    before = {
        "version": SubjectVersion.objects.count(),
        "name": SubjectName.objects.count(),
        "product": SubjectProduct.objects.count(),
        "event": SubjectEvent.objects.count(),
        "risk": SubjectRiskAssessment.objects.count(),
    }
    with (
        patch(
            "apps.subjects.version_services.create_subject_version_references",
            side_effect=DatabaseError("injected reference failure"),
        ),
        pytest.raises(DatabaseError),
    ):
        commit_subject_version(
            user_id=user.pk,
            subject_id=subject.pk,
            expected_version=subject.version,
            product_confirmations=[],
            request_id=uuid.uuid4(),
        )
    subject.refresh_from_db()
    assert subject.current_version_id is None
    assert SubjectVersion.objects.count() == before["version"]
    assert SubjectName.objects.count() == before["name"]
    assert SubjectProduct.objects.count() == before["product"]
    assert SubjectEvent.objects.count() == before["event"]
    assert SubjectRiskAssessment.objects.count() == before["risk"]


def test_private_download_remains_available_during_pending_and_rejected_subject_review():
    admin, user, subject, _ = _provision(file_field=True)
    intent, _ = _new_intent(user, subject, b"review-independent file")
    _complete_and_verify(user, intent)
    intent.refresh_from_db()
    subject = update_subject_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=subject.version,
        values={"supporting_file": {"document_version_id": str(intent.completed_version_id)}},
    )
    subject, version = commit_subject_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=subject.version,
        product_confirmations=[],
        request_id=uuid.uuid4(),
    )
    assessment = SubjectRiskAssessment.objects.get(subject_version=version)
    review = SubjectReview.objects.create(
        assessment=assessment,
        subject=subject,
        subject_version=version,
        status=SubjectReview.Status.PENDING,
    )
    client = APIClient()
    client.force_authenticate(user)
    path = f"/api/v1/documents/{intent.completed_version.document_id}/download-intents"
    pending = client.post(path, {}, format="json")
    assert pending.status_code == 200
    assert pending["Cache-Control"] == "no-store"

    request = SimpleNamespace(
        user=admin,
        admin_context=resolve_admin_context(admin),
        request_id=str(uuid.uuid4()),
        META={"REMOTE_ADDR": "127.0.0.1", "HTTP_USER_AGENT": "XW-0205 test"},
    )
    decide_review(
        request=request,
        review_id=review.pk,
        decision=SubjectReview.Status.REJECTED,
        expected_version=review.version,
        public_reason="Test-only rejection evidence.",
        internal_note="",
    )
    rejected = client.post(path, {}, format="json")
    assert rejected.status_code == 200
    assert rejected["Cache-Control"] == "no-store"
