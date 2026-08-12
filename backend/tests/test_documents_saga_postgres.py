import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.test import override_settings
from django_redis import get_redis_connection

from apps.admin_rbac.permissions import resolve_admin_context
from apps.documents.exceptions import FileIdempotencyConflict
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
    verify_upload_intent,
)
from apps.documents.storage import S3CompatibleStorageProvider
from apps.plans.services import (
    create_plan,
    create_plan_version,
    publish_plan_version,
    update_plan_version,
)
from apps.plans.subscription_services import grant_trial
from apps.quotas.models import QuotaAccount, QuotaHoldGroup, QuotaLedgerEntry
from apps.subjects.models import SubjectFieldDefinition, SubjectType
from apps.subjects.services import create_custom_field
from apps.subjects.subject_services import create_subject, update_subject_draft
from apps.subjects.version_services import commit_subject_version
from apps.users.models import User
from tests.subject_risk_helpers import install_empty_published_risk_catalog
from tests.test_subscriptions import PASSWORD, _plan_limit_value

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


def _provision(*, storage_bytes=4096, file_field=False):
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
        approval_status=User.ApprovalStatus.APPROVED,
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
            "is_trial": True,
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
    subscription = grant_trial(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=plan.pk,
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
            "DELETE FROM subject_version_document_references WHERE id=%s",
        ),
    )
    for _table, row_id, sql in guarded:
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, [row_id])
