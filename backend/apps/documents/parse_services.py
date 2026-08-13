import hashlib
import hmac
import json
import logging
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, InterfaceError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.plans.models import Subscription
from apps.subjects.models import Subject
from apps.subjects.risk_services import ensure_subject_feature_allowed
from apps.users.models import Notification, User

from .exceptions import FileStorageUnavailable
from .models import DocumentVersion, UserDocument
from .ocr import get_ocr_provider
from .parse_exceptions import (
    DocumentOcrUnavailable,
    DocumentParseError,
    DocumentParseIdempotencyConflict,
    DocumentParseIdempotencyRequired,
    DocumentParseInfrastructureUnavailable,
    DocumentParseInternalError,
    DocumentParseSourceIntegrityFailed,
    DocumentParseStateConflict,
    DocumentParseUnexpectedError,
    DocumentParseVersionConflict,
)
from .parse_models import (
    DocumentParsedVersion,
    DocumentParseEvent,
    DocumentParseJob,
    DocumentParseState,
)
from .parsers import (
    PARSER_VERSION,
    canonicalize_text,
    confirmation_digest,
    machine_digest,
    parse_stream,
    parser_key_for,
)
from .storage import storage_provider

PARSE_KEY_VERSION = 1

PARSE_STREAM_CHUNK_BYTES = 64 * 1024
PARSE_SPOOL_MEMORY_BYTES = 4 * 1024 * 1024
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedParse:
    job_id: uuid.UUID
    generation: uuid.UUID
    document_version_id: uuid.UUID
    object_key: str
    file_kind: str
    expected_size_bytes: int
    expected_sha256: str
    expected_mime: str


def _claimed_parse(job) -> ClaimedParse:
    version = job.document_version
    return ClaimedParse(
        job.pk,
        job.generation,
        job.document_version_id,
        version.object_key,
        version.detected_file_kind,
        version.size_bytes,
        version.sha256,
        version.detected_mime,
    )


def _source_integrity_failed() -> DocumentParseSourceIntegrityFailed:
    return DocumentParseSourceIntegrityFailed()


@contextmanager
def _verified_parse_input(*, provider, claim: ClaimedParse):
    metadata = provider.head_object(claim.object_key)
    expected_sha = claim.expected_sha256.casefold()
    metadata_sha = metadata.metadata.get("sha256", "").strip().casefold()
    metadata_mime = metadata.content_type.split(";", 1)[0].strip().casefold()
    expected_mime = claim.expected_mime.split(";", 1)[0].strip().casefold()
    if (
        claim.expected_size_bytes <= 0
        or claim.expected_size_bytes > settings.FILE_UPLOAD_MAX_BYTES
        or len(expected_sha) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha)
        or metadata.size != claim.expected_size_bytes
        or metadata_sha != expected_sha
        or metadata_mime != expected_mime
    ):
        raise _source_integrity_failed()

    spool = tempfile.SpooledTemporaryFile(max_size=PARSE_SPOOL_MEMORY_BYTES, mode="w+b")
    digest = hashlib.sha256()
    actual_size = 0
    try:
        try:
            with provider.open_object(claim.object_key) as source:
                while True:
                    chunk = source.read(PARSE_STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise _source_integrity_failed()
                    actual_size += len(chunk)
                    if (
                        actual_size > claim.expected_size_bytes
                        or actual_size > settings.FILE_UPLOAD_MAX_BYTES
                    ):
                        raise _source_integrity_failed()
                    digest.update(chunk)
                    spool.write(chunk)
        except (DocumentParseSourceIntegrityFailed, FileStorageUnavailable):
            raise
        if actual_size != claim.expected_size_bytes or digest.hexdigest() != expected_sha:
            raise _source_integrity_failed()
        spool.seek(0)
        yield spool
    finally:
        spool.close()


def _canonical_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parse_digests(raw_key: str, *, user_id, document_id, document_version_id):
    key = (raw_key or "").strip()
    if not 16 <= len(key) <= 200 or any(ord(character) < 33 for character in key):
        raise DocumentParseIdempotencyRequired
    request_digest = _canonical_digest(
        {
            "document_id": str(document_id),
            "document_version_id": str(document_version_id),
        }
    )
    master = settings.FILE_IDEMPOTENCY_HMAC_KEY.encode()
    subkey = hmac.new(master, b"xianwen-file-v1:document-parse", hashlib.sha256).digest()
    scope = f"{PARSE_KEY_VERSION}|document-parse|{user_id}|{document_id}"
    key_digest = hmac.new(subkey, f"{scope}|{key}".encode(), hashlib.sha256).hexdigest()
    return key_digest, request_digest


def _effective_subscription_exists(user, moment) -> bool:
    return Subscription.objects.filter(
        user=user,
        status=Subscription.Status.ACTIVE,
        starts_at__lte=moment,
        ends_at__gt=moment,
    ).exists()


def _parse_write_allowed(user: User) -> bool:
    return (
        user.is_active
        and user.account_status == User.AccountStatus.ACTIVE
        and user.approval_status == User.ApprovalStatus.APPROVED
    )


def _confirm_write_allowed(user: User) -> bool:
    return user.is_active and user.account_status == User.AccountStatus.ACTIVE


def create_parse_job(
    *,
    user_id,
    document_id,
    document_version_id,
    idempotency_key: str,
    request_id,
) -> tuple[DocumentParseJob, bool]:
    key_digest, request_digest = _parse_digests(
        idempotency_key,
        user_id=user_id,
        document_id=document_id,
        document_version_id=document_version_id,
    )
    existing = DocumentParseJob.objects.filter(idempotency_key_digest=key_digest).first()
    if existing is not None:
        if existing.request_digest != request_digest:
            raise DocumentParseIdempotencyConflict
        return existing, False

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if not _parse_write_allowed(user):
            raise DocumentParseStateConflict
        try:
            subject_id = (
                UserDocument.objects.only("subject_id").get(pk=document_id, user=user).subject_id
            )
            subject = Subject.objects.select_for_update().get(pk=subject_id, user=user)
            document = UserDocument.objects.select_for_update().get(
                pk=document_id, user=user, subject=subject
            )
            version = DocumentVersion.objects.select_for_update().get(
                pk=document_version_id, document=document
            )
        except (
            UserDocument.DoesNotExist,
            Subject.DoesNotExist,
            DocumentVersion.DoesNotExist,
        ) as exc:
            raise NotFound from exc
        if subject.status not in {Subject.Status.DRAFT, Subject.Status.ACTIVE}:
            raise DocumentParseStateConflict
        if not _effective_subscription_exists(user, timezone.now()):
            raise DocumentParseStateConflict
        # PostgreSQL restricts current_version to a completed, clean, allocated file fact.
        if document.current_version_id != version.pk:
            raise DocumentParseStateConflict
        parser_key = parser_key_for(version.detected_file_kind)
        ocr = get_ocr_provider()
        if parser_key == "image_ocr" and not ocr.is_available():
            raise DocumentOcrUnavailable
        raced = DocumentParseJob.objects.filter(document_version=version).first()
        if raced is not None:
            if raced.idempotency_key_digest == key_digest:
                if raced.request_digest != request_digest:
                    raise DocumentParseIdempotencyConflict
                return raced, False
            raise DocumentParseStateConflict
        DocumentParseState.objects.get_or_create(
            document_version=version,
            defaults={
                "user": user,
                "subject": subject,
                "document": document,
            },
        )
        try:
            job = DocumentParseJob.objects.create(
                user=user,
                subject=subject,
                document=document,
                document_version=version,
                parser_key=parser_key,
                parser_version=PARSER_VERSION,
                ocr_provider_key=ocr.key if parser_key == "image_ocr" else "",
                idempotency_key_version=PARSE_KEY_VERSION,
                idempotency_key_digest=key_digest,
                request_digest=request_digest,
                request_id=request_id,
            )
        except IntegrityError as exc:
            raise DocumentParseStateConflict from exc
    return job, True


def claim_parse_job(
    *, job_id, request_id=None, correlation_id=None, expected_generation=None
) -> ClaimedParse | None:
    with transaction.atomic():
        job = (
            DocumentParseJob.objects.select_for_update()
            .select_related("document_version")
            .get(pk=job_id)
        )
        if expected_generation is not None:
            if job.status != DocumentParseJob.Status.RUNNING or str(job.generation) != str(
                expected_generation
            ):
                return None
            return _claimed_parse(job)
        if job.status in {DocumentParseJob.Status.SUCCEEDED, DocumentParseJob.Status.FAILED}:
            return None
        stale_before = timezone.now() - timedelta(
            seconds=settings.DOCUMENT_PARSE_RUNNING_STALE_SECONDS
        )
        if job.status == DocumentParseJob.Status.RUNNING and (
            job.started_at is None or job.started_at > stale_before
        ):
            return None
        if job.status == DocumentParseJob.Status.RETRY_WAIT and (
            job.next_attempt_at is None or job.next_attempt_at > timezone.now()
        ):
            return None
        generation = uuid.uuid4()
        job.status = DocumentParseJob.Status.RUNNING
        job.generation = generation
        job.attempts += 1
        job.started_at = timezone.now()
        job.next_attempt_at = None
        job.stable_error_code = ""
        job.request_id = request_id or job.request_id
        job.correlation_id = correlation_id or job.correlation_id
        job.save(
            update_fields=(
                "status",
                "generation",
                "attempts",
                "started_at",
                "next_attempt_at",
                "stable_error_code",
                "request_id",
                "correlation_id",
                "updated_at",
            )
        )
        DocumentParseEvent.objects.create(
            user_id=job.user_id,
            subject_id=job.subject_id,
            document_id=job.document_id,
            document_version_id=job.document_version_id,
            job=job,
            event_type=DocumentParseEvent.EventType.STARTED,
            safe_summary={"attempt": job.attempts},
            request_id=job.request_id,
        )
        return _claimed_parse(job)


def _schedule_retry(*, job_id, generation, code):
    with transaction.atomic():
        job = DocumentParseJob.objects.select_for_update().get(pk=job_id)
        if job.status != DocumentParseJob.Status.RUNNING or job.generation != generation:
            return
        job.retry_count += 1
        delay = min(
            3600,
            settings.DOCUMENT_PARSE_RETRY_BASE_SECONDS * (2 ** min(job.retry_count - 1, 7)),
        )
        job.status = DocumentParseJob.Status.RETRY_WAIT
        job.next_attempt_at = timezone.now() + timedelta(seconds=delay)
        job.stable_error_code = code
        job.save(
            update_fields=(
                "status",
                "retry_count",
                "next_attempt_at",
                "stable_error_code",
                "updated_at",
            )
        )
        DocumentParseEvent.objects.create(
            user_id=job.user_id,
            subject_id=job.subject_id,
            document_id=job.document_id,
            document_version_id=job.document_version_id,
            job=job,
            event_type=DocumentParseEvent.EventType.RETRY_SCHEDULED,
            stable_error_code=code,
            safe_summary={"retry_count": job.retry_count},
            request_id=job.request_id,
        )


def _permanent_failure(*, job_id, generation, code):
    with transaction.atomic():
        job = DocumentParseJob.objects.select_for_update().get(pk=job_id)
        if job.status != DocumentParseJob.Status.RUNNING or job.generation != generation:
            return False
        job.status = DocumentParseJob.Status.FAILED
        job.finished_at = timezone.now()
        job.stable_error_code = code
        job.save(update_fields=("status", "finished_at", "stable_error_code", "updated_at"))
        DocumentParseEvent.objects.create(
            user_id=job.user_id,
            subject_id=job.subject_id,
            document_id=job.document_id,
            document_version_id=job.document_version_id,
            job=job,
            event_type=DocumentParseEvent.EventType.FAILED,
            stable_error_code=code,
            safe_summary={},
            request_id=job.request_id,
        )
        Notification.objects.create(
            recipient_id=job.user_id,
            notification_type="document_parse_failed",
            title="\u6587\u4ef6\u89e3\u6790\u5931\u8d25",
            safe_summary="\u6587\u4ef6\u5185\u5bb9\u65e0\u6cd5\u5b89\u5168\u89e3\u6790\uff0c\u8bf7\u68c0\u67e5\u6587\u4ef6\u540e\u91cd\u8bd5\u3002",
        )
        return True


def fail_internal_parse_job(*, job_id, generation):
    return _permanent_failure(
        job_id=job_id,
        generation=generation,
        code=DocumentParseInternalError.code,
    )


def finalize_parse_job(*, job_id, generation, result):
    with transaction.atomic():
        job = (
            DocumentParseJob.objects.select_for_update()
            .select_related("document_version")
            .get(pk=job_id)
        )
        if job.status == DocumentParseJob.Status.SUCCEEDED:
            return job
        if job.status != DocumentParseJob.Status.RUNNING or job.generation != generation:
            return job
        state = DocumentParseState.objects.select_for_update().get(
            document_version_id=job.document_version_id
        )
        if state.latest_parsed_version_id is not None:
            raise DocumentParseStateConflict
        parsed = DocumentParsedVersion.objects.create(
            user_id=job.user_id,
            subject_id=job.subject_id,
            document_id=job.document_id,
            document_version_id=job.document_version_id,
            version_no=1,
            source=DocumentParsedVersion.Source.PARSER,
            extracted_text=result.canonical_text,
            tables_json=result.tables,
            warning_codes=sorted(set(result.warning_codes)),
            parser_key=result.parser_key,
            parser_version=result.parser_version,
            ocr_provider_key=result.ocr_provider_key,
            ocr_engine_version=result.ocr_engine_version,
            content_digest=machine_digest(document_version=job.document_version, result=result),
        )
        state.latest_parsed_version = parsed
        state.version += 1
        state.save(update_fields=("latest_parsed_version", "version", "updated_at"))
        job.status = DocumentParseJob.Status.SUCCEEDED
        job.finished_at = timezone.now()
        job.stable_error_code = ""
        job.save(update_fields=("status", "finished_at", "stable_error_code", "updated_at"))
        DocumentParseEvent.objects.create(
            user_id=job.user_id,
            subject_id=job.subject_id,
            document_id=job.document_id,
            document_version_id=job.document_version_id,
            job=job,
            parsed_version=parsed,
            event_type=DocumentParseEvent.EventType.SUCCEEDED,
            safe_summary={"parser_key": result.parser_key},
            request_id=job.request_id,
        )
        Notification.objects.create(
            recipient_id=job.user_id,
            notification_type="document_parse_succeeded",
            title="\u6587\u4ef6\u89e3\u6790\u5b8c\u6210",
            safe_summary="\u6587\u4ef6\u5185\u5bb9\u5df2\u89e3\u6790\uff0c\u8bf7\u786e\u8ba4\u6587\u672c\u540e\u518d\u7528\u4e8e\u540e\u7eed\u529f\u80fd\u3002",
        )
        return job


def execute_parse(*, job_id, request_id=None, correlation_id=None, expected_generation=None):
    claim = claim_parse_job(
        job_id=job_id,
        request_id=request_id,
        correlation_id=correlation_id,
        expected_generation=expected_generation,
    )
    if claim is None:
        return {"status": "not_due_or_terminal"}
    try:
        provider = storage_provider()
        ocr = get_ocr_provider()
        with _verified_parse_input(provider=provider, claim=claim) as stream:
            result = parse_stream(claim.file_kind, stream, ocr)
    except FileStorageUnavailable:
        _schedule_retry(
            job_id=claim.job_id,
            generation=claim.generation,
            code=DocumentParseInfrastructureUnavailable.code,
        )
        return {
            "status": "retry_wait",
            "code": DocumentParseInfrastructureUnavailable.code,
        }
    except DocumentParseError as exc:
        if exc.permanent:
            _permanent_failure(
                job_id=claim.job_id,
                generation=claim.generation,
                code=exc.code,
            )
        else:
            _schedule_retry(
                job_id=claim.job_id,
                generation=claim.generation,
                code=exc.code,
            )
        return {"status": "failed" if exc.permanent else "retry_wait", "code": exc.code}
    except Exception as exc:
        logger.exception(
            "Unexpected document parser execution failure.",
            extra={
                "job_id": str(claim.job_id),
                "document_version_id": str(claim.document_version_id),
                "generation": str(claim.generation),
            },
        )
        raise DocumentParseUnexpectedError(
            job_id=claim.job_id,
            generation=claim.generation,
        ) from exc
    try:
        finalize_parse_job(job_id=claim.job_id, generation=claim.generation, result=result)
    except (OperationalError, InterfaceError):
        try:
            _schedule_retry(
                job_id=claim.job_id,
                generation=claim.generation,
                code=DocumentParseInfrastructureUnavailable.code,
            )
        except (OperationalError, InterfaceError):
            pass
        raise
    except Exception as exc:
        logger.exception(
            "Unexpected document parser finalization failure.",
            extra={
                "job_id": str(claim.job_id),
                "document_version_id": str(claim.document_version_id),
                "generation": str(claim.generation),
            },
        )
        raise DocumentParseUnexpectedError(
            job_id=claim.job_id,
            generation=claim.generation,
        ) from exc
    return {"status": "succeeded"}


def due_parse_job_ids(*, limit=200):
    now = timezone.now()
    stale_before = now - timedelta(seconds=settings.DOCUMENT_PARSE_RUNNING_STALE_SECONDS)
    return list(
        DocumentParseJob.objects.filter(
            Q(
                status=DocumentParseJob.Status.RETRY_WAIT,
                next_attempt_at__lte=now,
            )
            | Q(status=DocumentParseJob.Status.RUNNING, started_at__lte=stale_before)
        )
        .order_by("id")
        .values_list("id", flat=True)[:limit]
    )


def confirm_parsed_text(
    *,
    user_id,
    document_id,
    expected_parse_state_version,
    source_parsed_version_id,
    confirmed_text,
    request_id,
):
    text = canonicalize_text(confirmed_text)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if not _confirm_write_allowed(user):
            raise DocumentParseStateConflict
        try:
            subject_id = (
                UserDocument.objects.only("subject_id").get(pk=document_id, user=user).subject_id
            )
            subject = Subject.objects.select_for_update().get(pk=subject_id, user=user)
            document = UserDocument.objects.select_for_update().get(
                pk=document_id, user=user, subject=subject
            )
            current_version_id = document.current_version_id
            if current_version_id is None:
                raise DocumentParseStateConflict
            version = DocumentVersion.objects.select_for_update().get(
                pk=current_version_id, document=document
            )
            state = DocumentParseState.objects.select_for_update().get(
                document_version=version,
                user=user,
                subject=subject,
                document=document,
            )
            source = DocumentParsedVersion.objects.select_for_update().get(
                pk=source_parsed_version_id,
                document_version=version,
                user=user,
                subject=subject,
                document=document,
            )
        except (
            UserDocument.DoesNotExist,
            Subject.DoesNotExist,
            DocumentVersion.DoesNotExist,
            DocumentParseState.DoesNotExist,
            DocumentParsedVersion.DoesNotExist,
        ) as exc:
            raise NotFound from exc
        if subject.status == Subject.Status.ARCHIVED:
            raise DocumentParseStateConflict
        machine_base = (
            source
            if source.source == DocumentParsedVersion.Source.PARSER
            else source.machine_base_version
        )
        if machine_base is None:
            raise DocumentParseStateConflict
        digest = confirmation_digest(machine_base=machine_base, parent=source, text=text)
        replay = DocumentParsedVersion.objects.filter(
            parent_version=source,
            source=DocumentParsedVersion.Source.USER_CONFIRMATION,
            content_digest=digest,
        ).first()
        if replay is not None and state.current_confirmed_version_id == replay.pk:
            return state, replay, False
        if (
            state.version != expected_parse_state_version
            or state.latest_parsed_version_id != source.pk
        ):
            raise DocumentParseVersionConflict
        parsed = DocumentParsedVersion.objects.create(
            user=user,
            subject=subject,
            document=document,
            document_version=version,
            version_no=source.version_no + 1,
            source=DocumentParsedVersion.Source.USER_CONFIRMATION,
            parent_version=source,
            machine_base_version=machine_base,
            extracted_text=text,
            tables_json=[],
            warning_codes=[],
            parser_key=machine_base.parser_key,
            parser_version=machine_base.parser_version,
            ocr_provider_key=machine_base.ocr_provider_key,
            ocr_engine_version=machine_base.ocr_engine_version,
            content_digest=digest,
            confirmed_by=user,
            confirmed_at=timezone.now(),
        )
        state.latest_parsed_version = parsed
        state.current_confirmed_version = parsed
        state.version += 1
        state.save(
            update_fields=(
                "latest_parsed_version",
                "current_confirmed_version",
                "version",
                "updated_at",
            )
        )
        DocumentParseEvent.objects.create(
            user=user,
            subject=subject,
            document=document,
            document_version=version,
            parsed_version=parsed,
            event_type=DocumentParseEvent.EventType.CONFIRMED,
            safe_summary={"version_no": parsed.version_no},
            actor=user,
            request_id=request_id,
        )
        return state, parsed, True


def parse_result_for_user(*, user, document_id):
    try:
        document = UserDocument.objects.select_related(
            "current_version__parse_job",
            "current_version__parse_state__latest_parsed_version",
            "current_version__parse_state__current_confirmed_version",
        ).get(pk=document_id, user=user)
    except UserDocument.DoesNotExist as exc:
        raise NotFound from exc
    version = document.current_version
    if version is None:
        return document, None, None
    try:
        job = version.parse_job
    except DocumentParseJob.DoesNotExist:
        job = None
    try:
        state = version.parse_state
    except DocumentParseState.DoesNotExist:
        state = None
    return document, job, state


def get_confirmed_document_content(*, subject, document_version):
    try:
        state = DocumentParseState.objects.select_related(
            "current_confirmed_version__machine_base_version"
        ).get(
            document_version=document_version,
            subject=subject,
            user=subject.user,
        )
    except DocumentParseState.DoesNotExist as exc:
        raise DocumentParseStateConflict from exc
    if state.current_confirmed_version_id is None:
        raise DocumentParseStateConflict
    return state.current_confirmed_version


def get_confirmed_document_content_for_feature(*, subject, document_version, feature_key: str):
    ensure_subject_feature_allowed(subject, feature_key)
    return get_confirmed_document_content(
        subject=subject,
        document_version=document_version,
    )
