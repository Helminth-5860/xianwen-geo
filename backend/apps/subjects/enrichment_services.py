from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.ai.sanitization import sanitize_provider_metrics
from apps.documents.parse_models import DocumentParsedVersion, DocumentParseState
from apps.plans.models import Subscription
from apps.users.models import User
from apps.web_sources.models import WebSourceImport, WebSourceParsedVersion

from .enrichment_contracts import SubjectEnrichmentRequest, TargetField, UntrustedSource
from .enrichment_exceptions import (
    SubjectEnrichmentError,
    SubjectEnrichmentIdempotencyConflict,
    SubjectEnrichmentInputTooLarge,
    SubjectEnrichmentInvalidResponse,
    SubjectEnrichmentProviderError,
    SubjectEnrichmentSourceInvalid,
    SubjectEnrichmentStateConflict,
    SubjectEnrichmentTargetInvalid,
    SubjectEnrichmentUnexpectedError,
    SubjectEnrichmentVersionConflict,
)
from .enrichment_idempotency import canonical_digest, derive_idempotency
from .enrichment_providers import (
    get_subject_enrichment_provider,
    require_available_subject_enrichment_provider,
)
from .enrichment_rate_limits import enforce_enrichment_limits
from .models import (
    Subject,
    SubjectEnrichmentConfirmation,
    SubjectEnrichmentDecision,
    SubjectEnrichmentEvent,
    SubjectEnrichmentJob,
    SubjectEnrichmentSource,
    SubjectEnrichmentSuggestion,
    SubjectEnrichmentSuggestionSource,
)
from .schema_snapshots import (
    SnapshotValueError,
    assert_snapshot_integrity,
    merge_and_validate_values,
)
from .subject_services import (
    SubjectBusinessError,
    _effective_subscription_locked,
    merge_subject_draft_values_locked,
    subject_for_user_or_404,
)

_ALLOWED_FIELD_TYPES = {"text", "textarea", "number", "date", "url", "single", "select", "multi"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _value_digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_event(
    job: SubjectEnrichmentJob, event_type: str, *, code: str = "", summary=None, actor=None
):
    return SubjectEnrichmentEvent.objects.create(
        job=job,
        event_type=event_type,
        stable_error_code=code,
        safe_summary=dict(summary or {}),
        actor=actor,
        request_id=job.request_id,
        correlation_id=job.correlation_id,
    )


def _ensure_create_eligible(*, user: User, subject: Subject) -> Subscription:
    if (
        not user.is_active
        or user.account_status != User.AccountStatus.ACTIVE
        or subject.user_id != user.pk
        or subject.status not in {Subject.Status.DRAFT, Subject.Status.ACTIVE}
    ):
        raise SubjectEnrichmentStateConflict
    subscription = _effective_subscription_locked(user=user, moment=timezone.now())
    if subscription is None:
        raise SubjectEnrichmentStateConflict
    return subscription


def _official_name_present(subject: Subject) -> bool:
    for field in subject.schema_snapshot.get("fields", []):
        if field.get("name_role") != "official_name":
            continue
        value = subject.draft_values.get(field.get("field_key"))
        if isinstance(value, str) and value.strip():
            return True
        if value not in (None, "", []):
            return True
    return False


def _context_values(subject: Subject) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in subject.schema_snapshot.get("fields", []):
        if not field.get("used_for_ai") or field.get("field_type") in {"image", "file"}:
            continue
        result[field["field_key"]] = copy.deepcopy(subject.draft_values.get(field["field_key"]))
    return result


def _target_manifest(subject: Subject, target_field_keys: list[str]) -> list[dict[str, Any]]:
    if len(target_field_keys) != len(set(target_field_keys)):
        raise SubjectEnrichmentTargetInvalid
    by_key = {field["field_key"]: field for field in subject.schema_snapshot.get("fields", [])}
    manifest: list[dict[str, Any]] = []
    for key in target_field_keys:
        field = by_key.get(key)
        if (
            not field
            or not field.get("used_for_ai")
            or field.get("name_role") == "official_name"
            or field.get("field_type") not in _ALLOWED_FIELD_TYPES
        ):
            raise SubjectEnrichmentTargetInvalid
        manifest.append(
            {
                "field_key": key,
                "field_type": field["field_type"],
                "label": field.get("label", key),
                "options": copy.deepcopy(field.get("options", [])),
            }
        )
    if not manifest or len(manifest) > settings.SUBJECT_ENRICHMENT_MAX_TARGET_FIELDS:
        raise SubjectEnrichmentTargetInvalid
    return manifest


@dataclass(frozen=True)
class SelectedSource:
    source_type: str
    parsed_id: Any
    digest: str
    text: str
    document: DocumentParsedVersion | None = None
    web: WebSourceParsedVersion | None = None


def _selected_sources_locked(
    *, user: User, subject: Subject, refs: list[dict[str, Any]]
) -> list[SelectedSource]:
    if len(refs) > settings.SUBJECT_ENRICHMENT_MAX_SOURCES:
        raise SubjectEnrichmentSourceInvalid
    seen: set[tuple[str, str]] = set()
    rows: list[SelectedSource] = []
    total_chars = 0
    for ref in refs:
        key = (ref["source_type"], str(ref["parsed_version_id"]))
        if key in seen:
            raise SubjectEnrichmentSourceInvalid
        seen.add(key)
        if ref["source_type"] == "document":
            try:
                document_parsed = DocumentParsedVersion.objects.select_related(
                    "document_version__parse_state"
                ).get(
                    pk=ref["parsed_version_id"],
                    user=user,
                    subject=subject,
                    source=DocumentParsedVersion.Source.USER_CONFIRMATION,
                )
            except DocumentParsedVersion.DoesNotExist as exc:
                raise SubjectEnrichmentSourceInvalid from exc
            try:
                state = document_parsed.document_version.parse_state
            except DocumentParseState.DoesNotExist as exc:
                raise SubjectEnrichmentSourceInvalid from exc
            if state.current_confirmed_version_id != document_parsed.pk:
                raise SubjectEnrichmentSourceInvalid
            text = document_parsed.extracted_text
            row = SelectedSource(
                "document",
                document_parsed.pk,
                document_parsed.content_digest,
                text,
                document=document_parsed,
            )
        else:
            try:
                web_parsed = WebSourceParsedVersion.objects.select_related("import_record").get(
                    pk=ref["parsed_version_id"],
                    user=user,
                    subject=subject,
                    source=WebSourceParsedVersion.Source.USER_CONFIRMATION,
                )
            except WebSourceParsedVersion.DoesNotExist as exc:
                raise SubjectEnrichmentSourceInvalid from exc
            if (
                web_parsed.import_record.status != WebSourceImport.Status.SUCCEEDED
                or web_parsed.import_record.current_confirmed_version_id != web_parsed.pk
            ):
                raise SubjectEnrichmentSourceInvalid
            text = web_parsed.canonical_text
            row = SelectedSource(
                "web",
                web_parsed.pk,
                web_parsed.content_digest,
                text,
                web=web_parsed,
            )
        if not text or len(text) > settings.SUBJECT_ENRICHMENT_MAX_SOURCE_CHARACTERS:
            raise SubjectEnrichmentInputTooLarge
        total_chars += len(text)
        if total_chars > settings.SUBJECT_ENRICHMENT_MAX_TOTAL_SOURCE_CHARACTERS:
            raise SubjectEnrichmentInputTooLarge
        rows.append(row)
    return rows


def available_sources(*, user: User, subject: Subject) -> list[dict[str, Any]]:
    if subject.user_id != user.pk:
        raise NotFound
    output: list[dict[str, Any]] = []
    document_states = (
        DocumentParseState.objects.filter(
            user=user, subject=subject, current_confirmed_version__isnull=False
        )
        .select_related("document", "current_confirmed_version")
        .order_by("-updated_at", "id")
    )
    for state in document_states:
        document_parsed = state.current_confirmed_version
        if document_parsed is None:
            continue
        output.append(
            {
                "source_type": "document",
                "parsed_version_id": str(document_parsed.pk),
                "label": state.document.display_name,
                "version_no": document_parsed.version_no,
                "character_count": len(document_parsed.extracted_text),
            }
        )
    imports = (
        WebSourceImport.objects.filter(
            user=user,
            subject=subject,
            status=WebSourceImport.Status.SUCCEEDED,
            current_confirmed_version__isnull=False,
        )
        .select_related("current_confirmed_version")
        .order_by("-updated_at", "id")
    )
    for row in imports:
        web_parsed = row.current_confirmed_version
        if web_parsed is None:
            continue
        output.append(
            {
                "source_type": "web",
                "parsed_version_id": str(web_parsed.pk),
                "label": row.display_url,
                "version_no": web_parsed.version_no,
                "character_count": len(web_parsed.canonical_text),
            }
        )
    return output


def available_targets(subject: Subject) -> list[dict[str, Any]]:
    targets = []
    for field in subject.schema_snapshot.get("fields", []):
        if (
            field.get("used_for_ai")
            and field.get("name_role") != "official_name"
            and field.get("field_type") in _ALLOWED_FIELD_TYPES
        ):
            targets.append(
                {
                    "field_key": field["field_key"],
                    "label": field.get("label", field["field_key"]),
                    "field_type": field["field_type"],
                    "current_value": copy.deepcopy(subject.draft_values.get(field["field_key"])),
                }
            )
    return targets


def latest_unapplied_job(*, user: User, subject: Subject):
    return (
        SubjectEnrichmentJob.objects.filter(
            user=user,
            subject=subject,
            subject_object_version_at_create=subject.version,
        )
        .exclude(confirmation__isnull=False)
        .order_by("-created_at", "-id")
        .first()
    )


def create_enrichment_job(
    *,
    request,
    user_id,
    subject_id,
    expected_subject_version: int,
    source_refs,
    target_field_keys,
    idempotency_key: str,
    request_id,
):
    idem = derive_idempotency(user_id=user_id, subject_id=subject_id, raw_key=idempotency_key)
    request_payload = {
        "subject_id": str(subject_id),
        "expected_subject_version": expected_subject_version,
        "sources": sorted(
            [
                {
                    "source_type": item["source_type"],
                    "parsed_version_id": str(item["parsed_version_id"]),
                }
                for item in source_refs
            ],
            key=lambda item: (item["source_type"], item["parsed_version_id"]),
        ),
        "target_field_keys": sorted(target_field_keys),
    }
    req_digest = canonical_digest(request_payload)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
        replay = SubjectEnrichmentJob.objects.filter(idempotency_key_digest=idem).first()
        if replay is not None:
            if replay.request_digest != req_digest:
                raise SubjectEnrichmentIdempotencyConflict
            return replay, False
        if subject.version != expected_subject_version:
            raise SubjectEnrichmentVersionConflict
        _ensure_create_eligible(user=user, subject=subject)
        provider = require_available_subject_enrichment_provider()
        if not _official_name_present(subject):
            raise SubjectEnrichmentTargetInvalid
        if SubjectEnrichmentJob.objects.filter(
            subject=subject,
            status__in=("queued", "running", "retry_wait"),
        ).exists():
            raise SubjectEnrichmentStateConflict
        enforce_enrichment_limits(request=request, user_id=user.pk, subject_id=subject.pk)
        assert_snapshot_integrity(subject.schema_snapshot, subject.schema_digest)
        manifest = _target_manifest(subject, list(target_field_keys))
        sources = _selected_sources_locked(user=user, subject=subject, refs=list(source_refs))
        context = _context_values(subject)
        input_digest = canonical_digest(
            {
                "subject_version": subject.version,
                "schema_digest": subject.schema_digest,
                "targets": manifest,
                "subject_values": context,
                "sources": [
                    {
                        "type": source.source_type,
                        "id": str(source.parsed_id),
                        "digest": source.digest,
                    }
                    for source in sources
                ],
            }
        )
        try:
            job = SubjectEnrichmentJob.objects.create(
                user=user,
                subject=subject,
                subject_object_version_at_create=subject.version,
                current_formal_subject_version_id_at_create=subject.current_version_id,
                schema_digest=subject.schema_digest,
                schema_snapshot_format_version=subject.schema_snapshot_format_version,
                target_manifest=manifest,
                input_subject_values=context,
                provider_key=provider.key,
                model_key=provider.model_key,
                adapter_version=provider.adapter_version,
                prompt_version=provider.prompt_version,
                input_digest=input_digest,
                idempotency_key_digest=idem,
                request_digest=req_digest,
                request_id=request_id,
                correlation_id=request_id,
            )
            for source in sources:
                SubjectEnrichmentSource.objects.create(
                    job=job,
                    user=user,
                    subject=subject,
                    source_type=source.source_type,
                    document_parsed_version=source.document,
                    web_parsed_version=source.web,
                    content_digest=source.digest,
                    input_characters=len(source.text),
                )
        except IntegrityError as exc:
            raise SubjectEnrichmentStateConflict from exc
        return job, True


def enrichment_job_for_user_or_404(*, user: User, subject_id, job_id, lock=False):
    query = SubjectEnrichmentJob.objects.filter(user=user, subject_id=subject_id)
    if lock:
        query = query.select_for_update()
    try:
        return query.get(pk=job_id)
    except SubjectEnrichmentJob.DoesNotExist as exc:
        raise NotFound from exc


def _source_text(source: SubjectEnrichmentSource) -> str:
    if source.source_type == SubjectEnrichmentSource.SourceType.DOCUMENT:
        document_parsed = source.document_parsed_version
        if document_parsed is None or document_parsed.content_digest != source.content_digest:
            raise SubjectEnrichmentSourceInvalid
        return document_parsed.extracted_text
    web_parsed = source.web_parsed_version
    if web_parsed is None or web_parsed.content_digest != source.content_digest:
        raise SubjectEnrichmentSourceInvalid
    return web_parsed.canonical_text


def _request_for_job(job: SubjectEnrichmentJob) -> SubjectEnrichmentRequest:
    sources = []
    for source in job.sources.select_related("document_parsed_version", "web_parsed_version"):
        sources.append(
            UntrustedSource(
                source_id=str(source.pk),
                source_type=source.source_type,
                content_digest=source.content_digest,
                text=_source_text(source),
            )
        )
    targets = []
    for field in job.target_manifest:
        targets.append(
            TargetField(
                field_key=field["field_key"],
                field_type=field["field_type"],
                label=field["label"],
                current_value=job.input_subject_values.get(field["field_key"]),
                options=tuple(option["option_key"] for option in field.get("options", [])),
            )
        )
    return SubjectEnrichmentRequest(
        job_id=str(job.pk),
        subject_id=str(job.subject_id),
        subject_values=copy.deepcopy(job.input_subject_values),
        sources=tuple(sources),
        target_fields=tuple(targets),
    )


def claim_enrichment_job(*, job_id, expected_generation=None):
    now = timezone.now()
    with transaction.atomic():
        job = SubjectEnrichmentJob.objects.select_for_update().get(pk=job_id)
        if job.status in {"succeeded", "failed"}:
            return None
        if expected_generation:
            if job.status == "running" and str(job.generation) == str(expected_generation):
                return job.pk, job.generation
            return None
        if (
            job.status == "running"
            and job.started_at
            and job.started_at
            > now - timedelta(seconds=settings.SUBJECT_ENRICHMENT_RUNNING_STALE_SECONDS)
        ):
            return None
        if job.status == "retry_wait" and job.next_attempt_at and job.next_attempt_at > now:
            return None
        job.status = "running"
        job.generation = uuid.uuid4()
        job.attempts += 1
        job.started_at = now
        job.next_attempt_at = None
        job.stable_error_code = ""
        job.version += 1
        job.save(
            update_fields=[
                "status",
                "generation",
                "attempts",
                "started_at",
                "next_attempt_at",
                "stable_error_code",
                "version",
                "updated_at",
            ]
        )
        _safe_event(job, "started", summary={"attempt": job.attempts})
        return job.pk, job.generation


def _schedule_retry(job_id, generation, code):
    with transaction.atomic():
        job = SubjectEnrichmentJob.objects.select_for_update().get(pk=job_id)
        if job.status != "running" or job.generation != generation:
            return {"status": job.status}
        if job.attempts >= settings.SUBJECT_ENRICHMENT_MAX_PROVIDER_ATTEMPTS:
            return _fail_locked(job, code)
        job.status = "retry_wait"
        job.retry_count += 1
        job.next_attempt_at = timezone.now() + timedelta(
            seconds=min(
                900,
                settings.SUBJECT_ENRICHMENT_RETRY_BASE_SECONDS * 2 ** min(job.retry_count - 1, 5),
            )
        )
        job.stable_error_code = code
        job.version += 1
        job.save(
            update_fields=[
                "status",
                "retry_count",
                "next_attempt_at",
                "stable_error_code",
                "version",
                "updated_at",
            ]
        )
        _safe_event(job, "retry_scheduled", code=code, summary={"retry_count": job.retry_count})
        return {"status": "retry_wait", "code": code}


def _fail_locked(job: SubjectEnrichmentJob, code: str):
    job.status = "failed"
    job.finished_at = timezone.now()
    job.stable_error_code = code
    job.version += 1
    job.save(update_fields=["status", "finished_at", "stable_error_code", "version", "updated_at"])
    _safe_event(job, "failed", code=code)
    return {"status": "failed", "code": code}


def fail_internal_enrichment(*, job_id, generation):
    with transaction.atomic():
        job = SubjectEnrichmentJob.objects.select_for_update().get(pk=job_id)
        if job.status != "running" or str(job.generation) != str(generation):
            return {"status": job.status}
        return _fail_locked(job, "SUBJECT_ENRICHMENT_INTERNAL_ERROR")


def _validate_response(job: SubjectEnrichmentJob, response):
    if response.model_key != job.model_key:
        raise SubjectEnrichmentInvalidResponse
    manifest = {item["field_key"]: item for item in job.target_manifest}
    suggestions = list(response.suggestions)
    if len(suggestions) != len(manifest):
        raise SubjectEnrichmentInvalidResponse
    source_ids = {str(source.pk) for source in job.sources.all()}
    seen = set()
    validated = []
    for suggestion in suggestions:
        if suggestion.field_key in seen or suggestion.field_key not in manifest:
            raise SubjectEnrichmentInvalidResponse
        seen.add(suggestion.field_key)
        if suggestion.confidence not in {"high", "medium", "low"}:
            raise SubjectEnrichmentInvalidResponse
        if len(suggestion.source_ids) != len(set(suggestion.source_ids)):
            raise SubjectEnrichmentInvalidResponse
        if source_ids and not suggestion.source_ids:
            raise SubjectEnrichmentInvalidResponse
        if not source_ids and suggestion.source_ids:
            raise SubjectEnrichmentInvalidResponse
        if not set(suggestion.source_ids) <= source_ids:
            raise SubjectEnrichmentInvalidResponse
        try:
            merge_and_validate_values(
                job.subject.schema_snapshot,
                current=job.subject.draft_values,
                updates={suggestion.field_key: suggestion.value},
            )
        except SnapshotValueError as exc:
            raise SubjectEnrichmentInvalidResponse from exc
        validated.append(suggestion)
    if seen != set(manifest):
        raise SubjectEnrichmentInvalidResponse
    return validated


def _finalize_success(job_id, generation, response):
    with transaction.atomic():
        job = (
            SubjectEnrichmentJob.objects.select_for_update()
            .select_related("subject")
            .get(pk=job_id)
        )
        if job.status == "succeeded":
            return {"status": "succeeded"}
        if job.status != "running" or job.generation != generation:
            return {"status": job.status}
        validated = _validate_response(job, response)
        source_map = {str(source.pk): source for source in job.sources.all()}
        output_projection = []
        for item in validated:
            current_value = job.input_subject_values.get(item.field_key)
            conflict = current_value not in (None, "", []) and current_value != item.value
            suggestion = SubjectEnrichmentSuggestion.objects.create(
                job=job,
                field_key=item.field_key,
                suggested_value=copy.deepcopy(item.value),
                value_digest=_value_digest(item.value),
                confidence=item.confidence,
                conflict=conflict,
                conflict_code="CURRENT_VALUE_DIFFERS" if conflict else "",
            )
            for source_id in item.source_ids:
                SubjectEnrichmentSuggestionSource.objects.create(
                    suggestion=suggestion,
                    source=source_map[source_id],
                )
            output_projection.append(
                {
                    "field_key": item.field_key,
                    "value_digest": suggestion.value_digest,
                    "confidence": item.confidence,
                    "source_ids": sorted(item.source_ids),
                }
            )
        job.output_digest = canonical_digest(output_projection)
        job.provider_metrics = sanitize_provider_metrics(response.provider_metrics)
        job.status = "succeeded"
        job.finished_at = timezone.now()
        job.stable_error_code = ""
        job.version += 1
        job.save(
            update_fields=[
                "output_digest",
                "provider_metrics",
                "status",
                "finished_at",
                "stable_error_code",
                "version",
                "updated_at",
            ]
        )
        _safe_event(
            job,
            "succeeded",
            summary={"suggestion_count": len(validated), "source_count": job.sources.count()},
        )
        return {"status": "succeeded"}


def execute_enrichment(*, job_id, expected_generation=None):
    claimed = claim_enrichment_job(job_id=job_id, expected_generation=expected_generation)
    if claimed is None:
        row = SubjectEnrichmentJob.objects.get(pk=job_id)
        return {"status": row.status}
    _, generation = claimed
    job = SubjectEnrichmentJob.objects.select_related("subject").get(pk=job_id)
    provider = get_subject_enrichment_provider(job.provider_key)
    try:
        response = provider.enrich(_request_for_job(job))
        return _finalize_success(job_id, generation, response)
    except SubjectEnrichmentProviderError as exc:
        if exc.permanent:
            with transaction.atomic():
                locked = SubjectEnrichmentJob.objects.select_for_update().get(pk=job_id)
                if locked.status != "running" or locked.generation != generation:
                    return {"status": locked.status}
                return _fail_locked(locked, exc.code)
        return _schedule_retry(job_id, generation, exc.code)
    except SubjectEnrichmentError as exc:
        if getattr(exc, "permanent", True):
            with transaction.atomic():
                locked = SubjectEnrichmentJob.objects.select_for_update().get(pk=job_id)
                if locked.status != "running" or locked.generation != generation:
                    return {"status": locked.status}
                return _fail_locked(locked, exc.code)
        return _schedule_retry(job_id, generation, exc.code)
    except Exception as exc:
        raise SubjectEnrichmentUnexpectedError(job_id=job_id, generation=generation) from exc


def due_enrichment_job_ids(limit=100):
    now = timezone.now()
    stale = now - timedelta(seconds=settings.SUBJECT_ENRICHMENT_RUNNING_STALE_SECONDS)
    return list(
        SubjectEnrichmentJob.objects.filter(
            models.Q(status="queued")
            | models.Q(status="retry_wait", next_attempt_at__lte=now)
            | models.Q(status="running", started_at__lte=stale)
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)[:limit]
    )


def confirmation_request_digest(
    *, job_id, expected_subject_version, expected_job_version, decisions
):
    normalized: list[dict[str, Any]] = [
        {
            "suggestion_id": str(item["suggestion_id"]),
            "accepted": bool(item["accepted"]),
        }
        for item in decisions
    ]
    normalized.sort(key=lambda item: str(item["suggestion_id"]))
    return canonical_digest(
        {
            "job_id": str(job_id),
            "expected_subject_version": expected_subject_version,
            "expected_job_version": expected_job_version,
            "decisions": normalized,
        }
    )


def confirm_enrichment(
    *,
    user_id,
    subject_id,
    job_id,
    expected_subject_version: int,
    expected_job_version: int,
    decisions,
    request_id,
):
    request_digest = confirmation_request_digest(
        job_id=job_id,
        expected_subject_version=expected_subject_version,
        expected_job_version=expected_job_version,
        decisions=decisions,
    )
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
        job = enrichment_job_for_user_or_404(
            user=user, subject_id=subject_id, job_id=job_id, lock=True
        )
        existing = SubjectEnrichmentConfirmation.objects.filter(job=job).first()
        if existing is not None:
            if existing.request_digest != request_digest:
                raise SubjectEnrichmentStateConflict
            return subject, existing, False
        if (
            not user.is_active
            or user.account_status != User.AccountStatus.ACTIVE
            or subject.status not in {Subject.Status.DRAFT, Subject.Status.ACTIVE}
        ):
            raise SubjectEnrichmentStateConflict
        if job.status != "succeeded" or job.version != expected_job_version:
            raise SubjectEnrichmentVersionConflict
        if (
            subject.version != expected_subject_version
            or subject.version != job.subject_object_version_at_create
        ):
            raise SubjectEnrichmentVersionConflict
        suggestions = {str(row.pk): row for row in job.suggestions.all()}
        normalized = {str(item["suggestion_id"]): bool(item["accepted"]) for item in decisions}
        if len(normalized) != len(decisions) or set(normalized) != set(suggestions):
            raise SubjectEnrichmentStateConflict
        accepted = {
            row.field_key: copy.deepcopy(row.suggested_value)
            for key, row in suggestions.items()
            if normalized[key]
        }
        before = subject.version
        if accepted:
            try:
                subject = merge_subject_draft_values_locked(
                    user=user, subject=subject, values=accepted
                )
            except SubjectBusinessError as exc:
                raise SubjectEnrichmentStateConflict from exc
        after = subject.version
        confirmation = SubjectEnrichmentConfirmation.objects.create(
            job=job,
            user=user,
            subject=subject,
            subject_version_before=before,
            subject_version_after=after,
            request_digest=request_digest,
            confirmed_by=user,
        )
        for key, row in suggestions.items():
            SubjectEnrichmentDecision.objects.create(
                confirmation=confirmation,
                suggestion=row,
                accepted=normalized[key],
            )
        _safe_event(
            job,
            "applied",
            summary={"accepted_count": len(accepted), "decision_count": len(suggestions)},
            actor=user,
        )
        return subject, confirmation, True
