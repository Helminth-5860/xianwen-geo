from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.plans.models import Subscription
from apps.subjects.models import Subject
from apps.users.models import Notification, User

from .exceptions import (
    WebSourceError,
    WebSourceIdempotencyConflict,
    WebSourceStateConflict,
    WebSourceUnexpectedError,
    WebSourceVersionConflict,
)
from .http_transport import fetch_url
from .idempotency import canonical_digest, derive_idempotency
from .models import (
    WebSourceEvent,
    WebSourceImport,
    WebSourceParsedVersion,
    WebSourceSnapshot,
)
from .parser import PARSER_VERSION, parse_response
from .rate_limits import enforce_import_limits
from .url_security import canonicalize_url, fingerprint


def _eligible_locked(*, user: User, subject: Subject) -> Subscription:
    now = timezone.now()
    if (
        not settings.WEB_IMPORT_ENABLED
        or not user.is_active
        or user.account_status != User.AccountStatus.ACTIVE
        or user.approval_status != User.ApprovalStatus.APPROVED
        or subject.user_id != user.pk
        or subject.status not in {Subject.Status.DRAFT, Subject.Status.ACTIVE}
    ):
        raise WebSourceStateConflict
    subscription = (
        Subscription.objects.select_for_update()
        .filter(user=user, status="active", starts_at__lte=now, ends_at__gt=now)
        .first()
    )
    if subscription is None:
        raise WebSourceStateConflict
    return subscription


def create_import(*, request, user_id, subject_id, raw_url: str, idempotency_key: str, request_id):
    target = canonicalize_url(raw_url)
    digest = derive_idempotency(user_id=user_id, subject_id=subject_id, raw_key=idempotency_key)
    request_digest = canonical_digest(
        {"subject_id": str(subject_id), "canonical_url": target.value}
    )
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        try:
            subject = Subject.objects.select_for_update().get(pk=subject_id, user=user)
        except Subject.DoesNotExist as exc:
            raise NotFound from exc
        _eligible_locked(user=user, subject=subject)
        replay = WebSourceImport.objects.filter(idempotency_key_digest=digest).first()
        if replay is not None:
            if replay.request_digest != request_digest:
                raise WebSourceIdempotencyConflict
            return replay, False
        enforce_import_limits(
            request=request, user_id=user.pk, subject_id=subject.pk, host=target.host
        )
        existing = WebSourceImport.objects.filter(
            user=user,
            subject=subject,
            canonical_url=target.value,
            status__in=("queued", "fetching", "retry_wait"),
        ).first()
        if existing is not None:
            raise WebSourceStateConflict
        try:
            row = WebSourceImport.objects.create(
                user=user,
                subject=subject,
                canonical_url=target.value,
                display_url=target.display,
                has_query=target.has_query,
                hostname_fingerprint=fingerprint("host", target.host),
                idempotency_key_digest=digest,
                request_digest=request_digest,
                request_id=request_id,
                correlation_id=request_id,
            )
        except IntegrityError as exc:
            raise WebSourceStateConflict from exc
        return row, True


def claim_import(*, import_id, expected_generation=None):
    now = timezone.now()
    with transaction.atomic():
        row = WebSourceImport.objects.select_for_update().get(pk=import_id)
        if row.status in {"succeeded", "failed"}:
            return None
        if expected_generation:
            if (
                row.status == "fetching"
                and row.generation
                and str(row.generation) == str(expected_generation)
            ):
                return row.pk, row.generation, row.canonical_url
            return None
        if (
            row.status == "fetching"
            and row.started_at
            and row.started_at > now - timedelta(seconds=settings.WEB_IMPORT_RUNNING_STALE_SECONDS)
        ):
            return None
        if row.status == "retry_wait" and row.next_attempt_at and row.next_attempt_at > now:
            return None
        row.status = "fetching"
        row.generation = uuid.uuid4()
        row.attempts += 1
        row.started_at = now
        row.next_attempt_at = None
        row.stable_error_code = ""
        row.version += 1
        row.save(
            update_fields=(
                "status",
                "generation",
                "attempts",
                "started_at",
                "next_attempt_at",
                "stable_error_code",
                "version",
                "updated_at",
            )
        )
        WebSourceEvent.objects.create(
            import_record=row,
            user=row.user,
            subject=row.subject,
            event_type="started",
            safe_summary={"attempt": row.attempts},
            request_id=row.request_id,
            correlation_id=row.correlation_id,
        )
        return row.pk, row.generation, row.canonical_url


def _retry(import_id, generation, code):
    with transaction.atomic():
        row = WebSourceImport.objects.select_for_update().get(pk=import_id)
        if row.status != "fetching" or row.generation != generation:
            return {"status": row.status}
        row.status = "retry_wait"
        row.retry_count += 1
        row.next_attempt_at = timezone.now() + timedelta(
            seconds=min(
                3600, settings.WEB_IMPORT_RETRY_BASE_SECONDS * 2 ** min(row.retry_count - 1, 7)
            )
        )
        row.stable_error_code = code
        row.version += 1
        row.save(
            update_fields=(
                "status",
                "retry_count",
                "next_attempt_at",
                "stable_error_code",
                "version",
                "updated_at",
            )
        )
        WebSourceEvent.objects.create(
            import_record=row,
            user=row.user,
            subject=row.subject,
            event_type="retry_scheduled",
            stable_error_code=code,
            safe_summary={"retry_count": row.retry_count},
            request_id=row.request_id,
            correlation_id=row.correlation_id,
        )
        return {"status": "retry_wait", "code": code}


def _fail(import_id, generation, code):
    with transaction.atomic():
        row = WebSourceImport.objects.select_for_update().get(pk=import_id)
        if row.status != "fetching" or row.generation != generation:
            return {"status": row.status}
        row.status = "failed"
        row.finished_at = timezone.now()
        row.stable_error_code = code
        row.version += 1
        row.save(
            update_fields=("status", "finished_at", "stable_error_code", "version", "updated_at")
        )
        WebSourceEvent.objects.create(
            import_record=row,
            user=row.user,
            subject=row.subject,
            event_type="failed",
            stable_error_code=code,
            safe_summary={},
            request_id=row.request_id,
            correlation_id=row.correlation_id,
        )
        Notification.objects.create(
            recipient=row.user,
            notification_type=Notification.NotificationType.WEB_SOURCE_IMPORT_FAILED,
            title="网页导入失败",
            safe_summary="网页内容未能安全导入，请稍后重试或检查地址。",
        )
        return {"status": "failed", "code": code}


def _finalize(import_id, generation, fetched):
    media_type = fetched.content_type.split(";", 1)[0].strip().lower()
    title, text, charset, digest = parse_response(
        body=fetched.body, media_type=media_type, content_type=fetched.content_type
    )
    with transaction.atomic():
        row = WebSourceImport.objects.select_for_update().get(pk=import_id)
        if row.status == "succeeded":
            return {"status": "succeeded"}
        if row.status != "fetching" or row.generation != generation:
            return {"status": row.status}
        fetched_at = timezone.now()
        snapshot = WebSourceSnapshot.objects.create(
            import_record=row,
            user=row.user,
            subject=row.subject,
            request_url=fetched.request_url,
            final_url=fetched.final_url,
            http_status=fetched.status,
            content_type=media_type,
            charset=charset,
            actual_bytes=len(fetched.body),
            response_sha256=fetched.response_sha256,
            redirect_count=fetched.redirect_count,
            provenance={
                "transport": "fixed_ip",
                "tls_verified": fetched.final_url.startswith("https://"),
            },
            title=title,
            canonical_text=text,
            parser_version=PARSER_VERSION,
            content_digest=digest,
            fetched_at=fetched_at,
        )
        parsed = WebSourceParsedVersion.objects.create(
            import_record=row,
            snapshot=snapshot,
            user=row.user,
            subject=row.subject,
            version_no=1,
            source="machine",
            canonical_text=text,
            content_digest=digest,
        )
        row.latest_parsed_version = parsed
        row.status = "succeeded"
        row.finished_at = fetched_at
        row.stable_error_code = ""
        row.version += 1
        row.save(
            update_fields=(
                "latest_parsed_version",
                "status",
                "finished_at",
                "stable_error_code",
                "version",
                "updated_at",
            )
        )
        WebSourceEvent.objects.create(
            import_record=row,
            snapshot=snapshot,
            parsed_version=parsed,
            user=row.user,
            subject=row.subject,
            event_type="succeeded",
            safe_summary={
                "actual_bytes": len(fetched.body),
                "redirect_count": fetched.redirect_count,
            },
            request_id=row.request_id,
            correlation_id=row.correlation_id,
        )
        Notification.objects.create(
            recipient=row.user,
            notification_type=Notification.NotificationType.WEB_SOURCE_IMPORT_SUCCEEDED,
            title="网页导入完成",
            safe_summary="网页内容已完成安全抓取，可以查看并确认。",
        )
        return {"status": "succeeded", "import_id": str(row.pk)}


def execute_import(*, import_id, expected_generation=None):
    claim = claim_import(import_id=import_id, expected_generation=expected_generation)
    if claim is None:
        return {"status": "unchanged"}
    row_id, generation, url = claim
    try:
        fetched = fetch_url(url)
        return _finalize(row_id, generation, fetched)
    except WebSourceError as exc:
        if exc.permanent:
            return _fail(row_id, generation, exc.code)
        return _retry(row_id, generation, exc.code)
    except Exception as exc:
        raise WebSourceUnexpectedError(import_id=row_id, generation=generation) from exc


def fail_internal_import(*, import_id, generation):
    return _fail(import_id, uuid.UUID(str(generation)), "WEB_SOURCE_INTERNAL_ERROR")


def due_import_ids(*, limit=200):
    now = timezone.now()
    stale = now - timedelta(seconds=settings.WEB_IMPORT_RUNNING_STALE_SECONDS)
    return list(
        WebSourceImport.objects.filter(
            models.Q(status="queued")
            | models.Q(status="retry_wait", next_attempt_at__lte=now)
            | models.Q(status="fetching", started_at__lte=stale)
        )
        .order_by("created_at")
        .values_list("id", flat=True)[:limit]
    )


def import_for_user_or_404(*, user, import_id, for_update=False):
    if for_update:
        rows = WebSourceImport.objects.select_for_update()
    else:
        rows = WebSourceImport.objects.select_related(
            "latest_parsed_version", "current_confirmed_version", "snapshot"
        )
    try:
        return rows.get(pk=import_id, user=user)
    except WebSourceImport.DoesNotExist as exc:
        raise NotFound from exc


def confirm_import(
    *, user_id, import_id, expected_version, source_version_id, confirmed_text, request_id
):
    text = " ".join(confirmed_text.split())
    if len(text) > settings.WEB_IMPORT_MAX_TEXT_CHARACTERS:
        raise WebSourceStateConflict
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        row = import_for_user_or_404(user=user, import_id=import_id, for_update=True)
        subject = Subject.objects.select_for_update().get(pk=row.subject_id, user=user)
        if (
            not user.is_active
            or user.account_status != User.AccountStatus.ACTIVE
            or subject.status not in {Subject.Status.DRAFT, Subject.Status.ACTIVE}
            or row.status != "succeeded"
        ):
            raise WebSourceStateConflict
        try:
            source = WebSourceParsedVersion.objects.get(
                pk=source_version_id, import_record=row, user=user, subject=subject
            )
        except WebSourceParsedVersion.DoesNotExist as exc:
            raise WebSourceStateConflict from exc
        machine = source if source.source == "machine" else source.machine_base_version
        if machine is None:
            raise WebSourceStateConflict
        digest = canonical_digest(
            {"machine": str(machine.pk), "parent": str(source.pk), "text": text}
        )
        replay = WebSourceParsedVersion.objects.filter(
            parent_version=source, source="user_confirmation", content_digest=digest
        ).first()
        if replay is not None and row.current_confirmed_version_id == replay.pk:
            return row, replay, False
        if row.version != expected_version or row.latest_parsed_version_id != source.pk:
            raise WebSourceVersionConflict
        parsed = WebSourceParsedVersion.objects.create(
            import_record=row,
            snapshot=source.snapshot,
            user=user,
            subject=subject,
            version_no=source.version_no + 1,
            source="user_confirmation",
            parent_version=source,
            machine_base_version=machine,
            canonical_text=text,
            content_digest=digest,
            confirmed_by=user,
            confirmed_at=timezone.now(),
        )
        row.latest_parsed_version = parsed
        row.current_confirmed_version = parsed
        row.version += 1
        row.save(
            update_fields=(
                "latest_parsed_version",
                "current_confirmed_version",
                "version",
                "updated_at",
            )
        )
        WebSourceEvent.objects.create(
            import_record=row,
            snapshot=source.snapshot,
            parsed_version=parsed,
            user=user,
            subject=subject,
            event_type="confirmed",
            safe_summary={"version_no": parsed.version_no},
            actor=user,
            request_id=request_id,
        )
        return row, parsed, True


def confirmed_content(*, subject, import_record):
    if import_record.subject_id != subject.pk or import_record.user_id != subject.user_id:
        raise WebSourceStateConflict
    if import_record.current_confirmed_version_id is None:
        raise WebSourceStateConflict
    return import_record.current_confirmed_version


def confirmed_content_for_feature(*, subject, import_record, feature_key):
    from apps.subjects.risk_services import ensure_subject_feature_allowed

    ensure_subject_feature_allowed(subject, feature_key)
    return confirmed_content(subject=subject, import_record=import_record)
