import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.plans.models import Subscription
from apps.quotas.models import QuotaAccount, QuotaHold, QuotaHoldGroup, QuotaLedgerEntry
from apps.quotas.services import consume_hold, freeze_quota, release_hold
from apps.subjects.models import Subject
from apps.users.models import User

from .exceptions import (
    FileContentInvalid,
    FileIdempotencyConflict,
    FileSecurityRejected,
    FileSizeInvalid,
    FileStateConflict,
    FileStorageUnavailable,
    FileVersionConflict,
)
from .idempotency import derive_file_digests
from .models import (
    DocumentVersion,
    FileStorageAllocation,
    FileUploadIntent,
    SubjectVersionDocumentReference,
    UserDocument,
)
from .scanners import file_scanner
from .storage import UploadRequest, storage_provider
from .validators import content_disposition_filename, declared_kind, safe_filename, validate_stream

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreatedIntent:
    intent: FileUploadIntent
    upload: UploadRequest | None


def _ensure_available() -> None:
    if (
        settings.FILE_STORAGE_PROVIDER == "unavailable"
        or settings.FILE_SCANNER_PROVIDER == "unavailable"
    ):
        raise FileStorageUnavailable
    if settings.APP_ENV == "production" and (
        settings.FILE_STORAGE_PROVIDER == "mock" or settings.FILE_SCANNER_PROVIDER == "mock"
    ):
        raise FileStorageUnavailable


def _effective_subscription_locked(user: User, now):
    return (
        Subscription.objects.select_for_update()
        .filter(user=user, status=Subscription.Status.ACTIVE, starts_at__lte=now, ends_at__gt=now)
        .order_by("starts_at", "id")
        .first()
    )


def _storage_account_locked(subscription: Subscription):
    return (
        QuotaAccount.objects.select_for_update()
        .filter(
            subscription=subscription,
            quota_type="storage_bytes",
            batch_type=QuotaAccount.BatchType.PRIMARY,
            cycle_started_at__isnull=True,
        )
        .order_by("id")
        .first()
    )


def _opaque_keys(intent_id: uuid.UUID) -> tuple[str, str]:
    return f"staging/{uuid.uuid4().hex}", f"objects/{intent_id.hex}/{uuid.uuid4().hex}"


def create_upload_intent(
    *,
    user_id,
    subject_id,
    filename: str,
    content_type: str,
    declared_size: int,
    idempotency_key: str,
    request_id,
) -> CreatedIntent:
    _ensure_available()
    normalized_name = safe_filename(filename)
    kind = declared_kind(normalized_name, content_type)
    if type(declared_size) is not int or not 0 < declared_size <= settings.FILE_UPLOAD_MAX_BYTES:
        raise FileSizeInvalid
    normalized_content_type = content_type.split(";", 1)[0].strip().casefold()
    payload = {
        "subject_id": str(subject_id),
        "purpose": FileUploadIntent.Purpose.SUBJECT_LIBRARY,
        "filename": normalized_name,
        "content_type": normalized_content_type,
        "declared_size": declared_size,
    }
    digests = derive_file_digests(idempotency_key, user_id=user_id, payload=payload)
    existing = FileUploadIntent.objects.filter(idempotency_key_digest=digests.key_digest).first()
    if existing is not None:
        if existing.request_digest != digests.request_digest:
            raise FileIdempotencyConflict
        upload = None
        if (
            existing.status == FileUploadIntent.Status.PENDING_UPLOAD
            and existing.expires_at > timezone.now()
        ):
            upload = storage_provider().create_upload_request(
                key=existing.staging_key,
                content_type=existing.declared_content_type,
                max_bytes=existing.declared_size,
            )
        return CreatedIntent(existing, upload)

    intent_id = uuid.uuid4()
    staging_key, final_key = _opaque_keys(intent_id)
    upload = storage_provider().create_upload_request(
        key=staging_key,
        content_type=normalized_content_type,
        max_bytes=declared_size,
    )
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        raced = FileUploadIntent.objects.filter(idempotency_key_digest=digests.key_digest).first()
        if raced is not None:
            if raced.request_digest != digests.request_digest:
                raise FileIdempotencyConflict
            raced_upload = None
            if (
                raced.status == FileUploadIntent.Status.PENDING_UPLOAD
                and raced.expires_at > timezone.now()
            ):
                raced_upload = storage_provider().create_upload_request(
                    key=raced.staging_key,
                    content_type=raced.declared_content_type,
                    max_bytes=raced.declared_size,
                )
            return CreatedIntent(raced, raced_upload)
        subscription = _effective_subscription_locked(user, timezone.now())
        if subscription is None:
            raise FileStorageUnavailable
        account = _storage_account_locked(subscription)
        if account is None:
            raise FileStorageUnavailable
        try:
            subject = Subject.objects.select_for_update().get(pk=subject_id, user=user)
        except Subject.DoesNotExist as exc:
            raise NotFound from exc
        if subject.status == Subject.Status.ARCHIVED:
            raise FileStateConflict
        hold_group = freeze_quota(
            account_id=account.pk,
            amount=declared_size,
            business_type="file_upload",
            business_id=intent_id,
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
        try:
            intent = FileUploadIntent.objects.create(
                id=intent_id,
                user=user,
                subject=subject,
                purpose=FileUploadIntent.Purpose.SUBJECT_LIBRARY,
                declared_filename=normalized_name,
                declared_content_type=normalized_content_type,
                declared_size=declared_size,
                declared_file_kind=kind,
                staging_key=staging_key,
                final_key=final_key,
                quota_hold_group=hold_group,
                idempotency_key_version=digests.key_version,
                idempotency_key_digest=digests.key_digest,
                request_digest=digests.request_digest,
                expires_at=timezone.now()
                + timedelta(seconds=settings.FILE_STAGING_RETENTION_SECONDS),
            )
        except Exception:
            raise
    return CreatedIntent(intent, upload)


def intent_for_user_or_404(*, user, intent_id, lock=False):
    query = FileUploadIntent.objects.filter(user=user)
    if lock:
        query = query.select_for_update(of=("self",))
    else:
        query = query.select_related("completed_version")
    try:
        return query.get(pk=intent_id)
    except FileUploadIntent.DoesNotExist as exc:
        raise NotFound from exc


def complete_upload_intent(
    *, user, intent_id, expected_version: int, request_id
) -> FileUploadIntent:
    binding = intent_for_user_or_404(user=user, intent_id=intent_id)
    if binding.status != FileUploadIntent.Status.PENDING_UPLOAD:
        if expected_version not in {binding.version, binding.version - 1}:
            raise FileVersionConflict
        return binding
    metadata = storage_provider().head_object(binding.staging_key)
    if metadata.size <= 0:
        raise FileSizeInvalid
    with transaction.atomic():
        intent = intent_for_user_or_404(user=user, intent_id=intent_id, lock=True)
        if intent.status != FileUploadIntent.Status.PENDING_UPLOAD:
            if expected_version not in {intent.version, intent.version - 1}:
                raise FileVersionConflict
            return intent
        if intent.version != expected_version:
            raise FileVersionConflict
        if intent.expires_at <= timezone.now():
            raise FileStateConflict
        intent.status = FileUploadIntent.Status.VERIFYING
        intent.verification_generation = uuid.uuid4()
        intent.next_attempt_at = timezone.now()
        intent.version += 1
        intent.save(
            update_fields=[
                "status",
                "verification_generation",
                "next_attempt_at",
                "version",
                "updated_at",
            ]
        )
        transaction.on_commit(
            lambda: __import__(
                "apps.documents.tasks", fromlist=["verify_upload_intent"]
            ).verify_upload_intent.apply_async(
                args=[str(intent.pk)],
                headers={"request_id": str(request_id), "correlation_id": str(request_id)},
            )
        )
        return intent


def _settlement_key(prefix: str, intent_id) -> str:
    return f"xianwen-file-{prefix}-{intent_id}"


def _release_remaining_locked(intent: FileUploadIntent, amount: int, request_id) -> None:
    if amount > 0:
        release_hold(
            hold_id=intent.quota_hold_group_id,
            amount=amount,
            idempotency_key=_settlement_key("release", intent.pk),
            request_id=request_id,
        )


def _lock_intent_settlement_context(intent_id) -> FileUploadIntent:
    binding = FileUploadIntent.objects.values("user_id", "quota_hold_group_id").get(pk=intent_id)
    allocations = list(
        QuotaHold.objects.filter(group_id=binding["quota_hold_group_id"]).values(
            "account_id", "subscription_id"
        )
    )
    User.objects.select_for_update().get(pk=binding["user_id"])
    subscription_ids = sorted({row["subscription_id"] for row in allocations}, key=str)
    list(Subscription.objects.select_for_update().filter(pk__in=subscription_ids).order_by("id"))
    account_ids = sorted({row["account_id"] for row in allocations}, key=str)
    list(QuotaAccount.objects.select_for_update().filter(pk__in=account_ids).order_by("id"))
    return FileUploadIntent.objects.select_for_update().select_related("subject").get(pk=intent_id)


def _reject_intent(intent_id, generation, code: str, request_id) -> None:
    with transaction.atomic():
        intent = _lock_intent_settlement_context(intent_id)
        if (
            intent.status != FileUploadIntent.Status.VERIFYING
            or intent.verification_generation != generation
        ):
            return
        group = QuotaHoldGroup.objects.select_for_update().get(pk=intent.quota_hold_group_id)
        remaining = group.requested_amount - group.consumed_amount - group.released_amount
        _release_remaining_locked(intent, remaining, request_id)
        intent.status = FileUploadIntent.Status.REJECTED
        intent.stable_error_code = code
        intent.next_attempt_at = None
        intent.staging_cleanup_pending = True
        intent.version += 1
        intent.save(
            update_fields=[
                "status",
                "stable_error_code",
                "next_attempt_at",
                "staging_cleanup_pending",
                "version",
                "updated_at",
            ]
        )


def _temporary_failure(intent_id, generation, code: str) -> None:
    with transaction.atomic():
        intent = FileUploadIntent.objects.select_for_update().get(pk=intent_id)
        if (
            intent.status != FileUploadIntent.Status.VERIFYING
            or intent.verification_generation != generation
        ):
            return
        intent.retry_count += 1
        intent.stable_error_code = code
        intent.next_attempt_at = timezone.now() + timedelta(
            seconds=min(900, 2 ** min(intent.retry_count, 9))
        )
        intent.version += 1
        intent.save(
            update_fields=[
                "retry_count",
                "stable_error_code",
                "next_attempt_at",
                "version",
                "updated_at",
            ]
        )


def verify_upload_intent(*, intent_id, request_id) -> str:
    with transaction.atomic():
        intent = FileUploadIntent.objects.select_for_update().get(pk=intent_id)
        if intent.status != FileUploadIntent.Status.VERIFYING:
            return intent.status
        if intent.next_attempt_at and intent.next_attempt_at > timezone.now():
            return intent.status
        generation = intent.verification_generation
        if generation is None:
            generation = uuid.uuid4()
            intent.verification_generation = generation
        intent.retry_count += 1
        intent.next_attempt_at = None
        intent.version += 1
        intent.save(
            update_fields=[
                "verification_generation",
                "retry_count",
                "next_attempt_at",
                "version",
                "updated_at",
            ]
        )
        snapshot: dict[str, Any] = {
            "staging_key": intent.staging_key,
            "final_key": intent.final_key,
            "declared_size": intent.declared_size,
            "kind": intent.declared_file_kind,
            "content_type": intent.declared_content_type,
        }

    provider = storage_provider()
    validated = None
    try:
        metadata = provider.head_object(snapshot["staging_key"])
        if metadata.size > snapshot["declared_size"]:
            raise FileSizeInvalid
        source = provider.open_object(snapshot["staging_key"])
        try:
            validated = validate_stream(
                source, expected_kind=snapshot["kind"], maximum=snapshot["declared_size"]
            )
        finally:
            source.close()
        result = file_scanner().scan(validated.stream)
        if result.status == "temporarily_unavailable":
            _temporary_failure(intent_id, generation, result.reason_code)
            return FileUploadIntent.Status.VERIFYING
        if result.status != "clean":
            _reject_intent(intent_id, generation, "FILE_SECURITY_REJECTED", request_id)
            return FileUploadIntent.Status.REJECTED
        provider.copy_verified_object(
            source_key=snapshot["staging_key"],
            final_key=snapshot["final_key"],
            source_etag=metadata.etag,
            size=validated.size,
            sha256=validated.sha256,
            content_type=validated.mime,
        )
        with transaction.atomic():
            intent = _lock_intent_settlement_context(intent_id)
            user = User.objects.get(pk=intent.user_id)
            if intent.status == FileUploadIntent.Status.COMPLETED:
                return intent.status
            if (
                intent.status != FileUploadIntent.Status.VERIFYING
                or intent.verification_generation != generation
            ):
                return intent.status
            consume_hold(
                hold_id=intent.quota_hold_group_id,
                amount=validated.size,
                idempotency_key=_settlement_key("consume", intent.pk),
                request_id=request_id,
            )
            remainder = intent.declared_size - validated.size
            _release_remaining_locked(intent, remainder, request_id)
            consume_entry = (
                QuotaLedgerEntry.objects.filter(
                    business_type="file_upload",
                    business_id=intent.pk,
                    action=QuotaLedgerEntry.Action.CONSUME,
                )
                .order_by("created_at", "id")
                .first()
            )
            if consume_entry is None:
                raise FileStateConflict
            document = UserDocument.objects.create(
                user=user,
                subject=intent.subject,
                purpose=intent.purpose,
                display_name=intent.declared_filename,
            )
            version = DocumentVersion.objects.create(
                document=document,
                version_no=1,
                object_key=intent.final_key,
                size_bytes=validated.size,
                sha256=validated.sha256,
                detected_file_kind=validated.kind,
                detected_mime=validated.mime,
                scanner_engine_version=result.engine_version,
            )
            UserDocument.objects.filter(pk=document.pk).update(current_version=version)
            FileStorageAllocation.objects.create(
                user=user,
                document_version=version,
                quota_account=consume_entry.account,
                consume_ledger=consume_entry,
                size_bytes=validated.size,
            )
            intent.status = FileUploadIntent.Status.COMPLETED
            intent.completed_version = version
            intent.stable_error_code = ""
            intent.next_attempt_at = None
            intent.staging_cleanup_pending = True
            intent.version += 1
            intent.save(
                update_fields=[
                    "status",
                    "completed_version",
                    "stable_error_code",
                    "next_attempt_at",
                    "staging_cleanup_pending",
                    "version",
                    "updated_at",
                ]
            )
        try:
            provider.delete_temporary_object(snapshot["staging_key"])
            FileUploadIntent.objects.filter(pk=intent_id).update(staging_cleanup_pending=False)
        except FileStorageUnavailable:
            pass
        return FileUploadIntent.Status.COMPLETED
    except (FileContentInvalid, FileSizeInvalid, FileSecurityRejected) as exc:
        _reject_intent(
            intent_id, generation, getattr(exc, "code", "FILE_CONTENT_INVALID"), request_id
        )
        return FileUploadIntent.Status.REJECTED
    except FileStorageUnavailable:
        _temporary_failure(intent_id, generation, "FILE_STORAGE_UNAVAILABLE")
        return FileUploadIntent.Status.VERIFYING
    finally:
        if validated is not None:
            validated.stream.close()


def expire_upload_intent(*, intent_id, request_id) -> bool:
    with transaction.atomic():
        intent = _lock_intent_settlement_context(intent_id)
        if (
            intent.status != FileUploadIntent.Status.PENDING_UPLOAD
            or intent.expires_at > timezone.now()
        ):
            return False
        group = QuotaHoldGroup.objects.select_for_update().get(pk=intent.quota_hold_group_id)
        remaining = group.requested_amount - group.consumed_amount - group.released_amount
        _release_remaining_locked(intent, remaining, request_id)
        intent.status = FileUploadIntent.Status.EXPIRED
        intent.staging_cleanup_pending = True
        intent.version += 1
        intent.save(update_fields=["status", "staging_cleanup_pending", "version", "updated_at"])
        return True


def due_expired_intent_ids(limit=100):
    return list(
        FileUploadIntent.objects.filter(
            status=FileUploadIntent.Status.PENDING_UPLOAD, expires_at__lte=timezone.now()
        )
        .order_by("expires_at", "id")
        .values_list("id", flat=True)[:limit]
    )


def due_verification_intent_ids(limit=100):
    return list(
        FileUploadIntent.objects.filter(
            status=FileUploadIntent.Status.VERIFYING, next_attempt_at__lte=timezone.now()
        )
        .order_by("next_attempt_at", "id")
        .values_list("id", flat=True)[:limit]
    )


def documents_for_subject(*, user, subject_id):
    if not Subject.objects.filter(pk=subject_id, user=user).exists():
        raise NotFound
    return (
        UserDocument.objects.filter(user=user, subject_id=subject_id)
        .select_related("current_version")
        .order_by("-created_at", "id")
    )


def document_for_user_or_404(*, user, document_id):
    try:
        return UserDocument.objects.select_related("current_version").get(pk=document_id, user=user)
    except UserDocument.DoesNotExist as exc:
        raise NotFound from exc


def create_download_intent(*, user, document_id) -> tuple[str, int]:
    document = document_for_user_or_404(user=user, document_id=document_id)
    version = document.current_version
    if version is None:
        raise FileStateConflict
    filename = content_disposition_filename(document.display_name)
    url = storage_provider().create_download_url(
        key=version.object_key, filename=filename, content_type=version.detected_mime
    )
    return url, settings.FILE_DOWNLOAD_URL_TTL


def storage_usage_bytes(user_id) -> int:
    return int(
        FileStorageAllocation.objects.filter(user_id=user_id).aggregate(total=Sum("size_bytes"))[
            "total"
        ]
        or 0
    )


def validate_document_references(
    *, user_id, subject_id, schema_snapshot, field_values
) -> list[tuple[str, DocumentVersion]]:
    references = []
    for field in schema_snapshot.get("fields", []):
        if field.get("field_type") not in {"image", "file"}:
            continue
        value = field_values.get(field["field_key"])
        if value is None:
            continue
        try:
            version_id = value["document_version_id"]
            version = DocumentVersion.objects.select_related("document", "completed_intent").get(
                pk=version_id,
                document__user_id=user_id,
                document__subject_id=subject_id,
                completed_intent__status=FileUploadIntent.Status.COMPLETED,
            )
        except (KeyError, TypeError, DocumentVersion.DoesNotExist) as exc:
            raise FileContentInvalid from exc
        if field["field_type"] == "image" and version.detected_file_kind not in {
            "jpeg",
            "png",
            "webp",
        }:
            raise FileContentInvalid
        references.append((field["field_key"], version))
    return references


def create_subject_version_references(*, subject_version, references) -> None:
    SubjectVersionDocumentReference.objects.bulk_create(
        [
            SubjectVersionDocumentReference(
                subject_version=subject_version, field_key=field_key, document_version=version
            )
            for field_key, version in references
        ]
    )
