from __future__ import annotations

import copy
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.http import Http404
from django.utils import timezone

from apps.quotas.models import QuotaAccount
from apps.quotas.services import (
    consume_hold,
    freeze_quota,
    get_or_create_subject_cycle_account,
    release_hold,
)

from .exceptions import KeywordError, KeywordVersionNoChanges
from .generation_contracts import KeywordGenerationRequest
from .generation_exceptions import (
    KeywordGenerationConfigInvalid,
    KeywordGenerationError,
    KeywordGenerationIdempotencyConflict,
    KeywordGenerationInProgress,
    KeywordGenerationInvalidResponse,
    KeywordGenerationLimitExceeded,
    KeywordGenerationProviderError,
    KeywordGenerationRegenerationConfirmationRequired,
    KeywordGenerationUnexpectedError,
    KeywordGenerationVersionConflict,
)
from .generation_idempotency import canonical_digest, derive_generation_idempotency
from .generation_providers import (
    get_keyword_generation_provider,
    require_available_keyword_generation_provider,
)
from .models import (
    Keyword,
    KeywordGenerationEvent,
    KeywordGenerationJob,
    KeywordGenerationResult,
    KeywordSet,
)
from .normalization import (
    KeywordNormalizationError,
    normalize_generated_keyword_items,
    normalize_plain_text,
)
from .services import (
    _assert_user_write_allowed,
    _lock_effective_subscription,
    _lock_subject_for_keywords,
    replace_keyword_draft_from_generation,
)

User = get_user_model()
_TERMINAL = {"succeeded", "failed", "conflict", "superseded"}


def _safe_event(job, event_type, *, code="", summary=None):
    return KeywordGenerationEvent.objects.create(
        job=job,
        event_type=event_type,
        stable_error_code=code,
        safe_summary=copy.deepcopy(summary or {}),
        request_id=job.request_id,
        correlation_id=job.correlation_id,
    )


def _validate_config(
    *,
    target_count: int,
    include_short: bool,
    include_long_tail: bool,
    include_regional: bool,
    regions: list[str],
) -> list[str]:
    if (
        type(target_count) is not int
        or not 1 <= target_count <= settings.KEYWORD_GENERATION_MAX_COUNT
    ):
        raise KeywordGenerationLimitExceeded
    if any(
        type(value) is not bool for value in (include_short, include_long_tail, include_regional)
    ):
        raise KeywordGenerationConfigInvalid
    if not isinstance(regions, list) or len(regions) > settings.KEYWORD_GENERATION_MAX_REGIONS:
        raise KeywordGenerationConfigInvalid
    normalized = []
    seen = set()
    for raw in regions:
        if not isinstance(raw, str):
            raise KeywordGenerationConfigInvalid
        try:
            value, matching = normalize_plain_text(raw, max_length=200)
        except KeywordNormalizationError as exc:
            raise KeywordGenerationConfigInvalid from exc
        if matching in seen:
            raise KeywordGenerationConfigInvalid
        seen.add(matching)
        normalized.append(value)
    if include_regional != bool(normalized):
        raise KeywordGenerationConfigInvalid
    return normalized


def _request_payload(
    *,
    subject_id,
    expected_subject_version_id,
    expected_keyword_set_version,
    target_count,
    include_short,
    include_long_tail,
    include_regional,
    regions,
    regenerate,
):
    return {
        "subject_id": str(subject_id),
        "expected_subject_version_id": str(expected_subject_version_id),
        "expected_keyword_set_version": expected_keyword_set_version,
        "target_count": target_count,
        "include_short": include_short,
        "include_long_tail": include_long_tail,
        "include_regional": include_regional,
        "regions": regions,
        "regenerate": regenerate,
    }


def _subject_values(subject_version) -> dict[str, Any]:
    values = copy.deepcopy(subject_version.field_values)
    values["official_name"] = subject_version.official_name
    return values


def _historical_exclusions(subject_id) -> list[str]:
    values = list(
        Keyword.objects.filter(keyword_set_version__subject_id=subject_id)
        .order_by("created_at", "id")
        .values_list("text", flat=True)
    )
    values.extend(
        KeywordSet.objects.filter(subject_id=subject_id).values_list("draft_items__text", flat=True)
    )
    snapshots = KeywordGenerationResult.objects.filter(
        job__subject_id=subject_id,
        job__status=KeywordGenerationJob.Status.SUCCEEDED,
    ).values_list("output_snapshot", flat=True)
    for snapshot in snapshots:
        for item in snapshot:
            if not isinstance(item, dict):
                continue
            value = item.get("text")
            if isinstance(value, str):
                values.append(value)
    output = []
    seen = set()
    for value in values:
        if not value:
            continue
        _, matching = normalize_plain_text(value)
        if matching not in seen:
            seen.add(matching)
            output.append(value)
    return output


@transaction.atomic
def create_keyword_generation_job(
    *,
    user_id,
    subject_id,
    expected_subject_version_id,
    expected_keyword_set_version: int,
    target_count: int,
    include_short: bool,
    include_long_tail: bool,
    include_regional: bool,
    regions: list[str],
    regenerate: bool,
    idempotency_key: str,
    request_id,
):
    normalized_regions = _validate_config(
        target_count=target_count,
        include_short=include_short,
        include_long_tail=include_long_tail,
        include_regional=include_regional,
        regions=regions,
    )
    if type(expected_keyword_set_version) is not int or expected_keyword_set_version < 0:
        raise KeywordGenerationVersionConflict
    if type(regenerate) is not bool:
        raise KeywordGenerationConfigInvalid
    idem = derive_generation_idempotency(
        user_id=user_id,
        subject_id=subject_id,
        raw_key=idempotency_key,
    )
    payload = _request_payload(
        subject_id=subject_id,
        expected_subject_version_id=expected_subject_version_id,
        expected_keyword_set_version=expected_keyword_set_version,
        target_count=target_count,
        include_short=include_short,
        include_long_tail=include_long_tail,
        include_regional=include_regional,
        regions=normalized_regions,
        regenerate=regenerate,
    )
    request_digest = canonical_digest(payload)
    user = User.objects.select_for_update().get(pk=user_id)
    replay = KeywordGenerationJob.objects.filter(idempotency_key_digest=idem).first()
    if replay is not None:
        if (
            replay.user_id != user.pk
            or str(replay.subject_id) != str(subject_id)
            or replay.request_digest != request_digest
        ):
            raise KeywordGenerationIdempotencyConflict
        return replay, False

    _assert_user_write_allowed(user)
    subject, subject_version = _lock_subject_for_keywords(
        user=user,
        subject_id=subject_id,
        expected_subject_version_id=expected_subject_version_id,
    )
    subscription = _lock_effective_subscription(user)
    limits = subscription.entitlement_snapshot.get("limits", {})
    plan_generation_limit = limits.get("keyword_generation_limit")
    if type(plan_generation_limit) is not int or target_count > plan_generation_limit:
        raise KeywordGenerationLimitExceeded
    if KeywordGenerationJob.objects.filter(
        subject=subject,
        status__in=("queued", "running", "retry_wait"),
    ).exists():
        raise KeywordGenerationInProgress

    keyword_set = KeywordSet.objects.select_for_update().filter(subject=subject).first()
    actual_version = keyword_set.version if keyword_set is not None else 0
    if actual_version != expected_keyword_set_version:
        raise KeywordGenerationVersionConflict

    provider = require_available_keyword_generation_provider()
    prior_success = KeywordGenerationJob.objects.filter(
        subject=subject,
        status=KeywordGenerationJob.Status.SUCCEEDED,
    ).exists()
    if prior_success and not regenerate:
        raise KeywordGenerationRegenerationConfirmationRequired
    billing_mode = (
        KeywordGenerationJob.BillingMode.REGENERATION
        if prior_success
        else KeywordGenerationJob.BillingMode.FREE_INITIAL
    )
    account = get_or_create_subject_cycle_account(
        subscription=subscription,
        subject=subject,
        quota_type="keyword_regenerations",
        request_id=request_id,
    )
    job_id = uuid.uuid4()
    quota_hold = None
    if billing_mode == KeywordGenerationJob.BillingMode.REGENERATION:
        quota_hold = freeze_quota(
            account_id=account.pk,
            amount=1,
            business_type="keyword_generation",
            business_id=job_id,
            idempotency_key=f"keyword-generation-freeze-{job_id}",
            request_id=request_id,
        )

    subject_values = _subject_values(subject_version)
    exclusions = _historical_exclusions(subject.pk)
    input_digest = canonical_digest(
        {
            "subject_version_id": str(subject_version.pk),
            "subject_values": subject_values,
            "configuration": payload,
            "historical_exclusions": exclusions,
        }
    )
    try:
        job = KeywordGenerationJob.objects.create(
            id=job_id,
            user=user,
            subject=subject,
            subject_version=subject_version,
            keyword_set=keyword_set,
            subscription=subscription,
            quota_hold=quota_hold,
            billing_mode=billing_mode,
            expected_keyword_set_version=expected_keyword_set_version,
            target_count=target_count,
            include_short=include_short,
            include_long_tail=include_long_tail,
            include_regional=include_regional,
            regions=normalized_regions,
            input_subject_values=subject_values,
            historical_exclusions=exclusions,
            provider_key=provider.key,
            model_key=provider.model_key,
            adapter_version=provider.adapter_version,
            prompt_version=provider.prompt_version,
            input_digest=input_digest,
            idempotency_key_digest=idem,
            request_digest=request_digest,
            request_id=request_id,
            correlation_id=request_id,
        )
    except IntegrityError as exc:
        raise KeywordGenerationInProgress from exc
    return job, True


def keyword_generation_job_for_user_or_404(*, user, job_id):
    try:
        return KeywordGenerationJob.objects.select_related(
            "subject",
            "subject_version",
            "quota_hold",
        ).get(pk=job_id, user=user)
    except KeywordGenerationJob.DoesNotExist as exc:
        raise Http404 from exc


def _request_for_job(job):
    return KeywordGenerationRequest(
        job_id=str(job.pk),
        subject_id=str(job.subject_id),
        subject_version_id=str(job.subject_version_id),
        subject_values=copy.deepcopy(job.input_subject_values),
        target_count=job.target_count,
        include_short=job.include_short,
        include_long_tail=job.include_long_tail,
        include_regional=job.include_regional,
        regions=tuple(job.regions),
        historical_exclusions=tuple(job.historical_exclusions),
    )


def claim_keyword_generation_job(*, job_id, expected_generation=None):
    now = timezone.now()
    with transaction.atomic():
        job = KeywordGenerationJob.objects.select_for_update().get(pk=job_id)
        if job.status in _TERMINAL:
            return None
        if expected_generation is not None:
            if job.status == "running" and str(job.generation) == str(expected_generation):
                return job.pk, job.generation
            return None
        if (
            job.status == "running"
            and job.started_at
            and job.started_at
            > now - timedelta(seconds=settings.KEYWORD_GENERATION_RUNNING_STALE_SECONDS)
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


def _settle_quota(job, action):
    if job.quota_hold_id is None:
        return
    settle = consume_hold if action == "consume" else release_hold
    settle(
        hold_id=job.quota_hold_id,
        amount=1,
        idempotency_key=f"keyword-generation-{action}-{job.pk}",
        request_id=job.request_id,
    )


def _terminal_locked(job, *, status, code):
    if job.status in _TERMINAL:
        return {"status": job.status}
    _settle_quota(job, "release")
    job.status = status
    job.finished_at = timezone.now()
    job.next_attempt_at = None
    job.stable_error_code = code
    job.version += 1
    job.save(
        update_fields=[
            "status",
            "finished_at",
            "next_attempt_at",
            "stable_error_code",
            "version",
            "updated_at",
        ]
    )
    _safe_event(job, status, code=code)
    return {"status": status, "code": code}


def _schedule_retry(job_id, generation, code):
    with transaction.atomic():
        job = KeywordGenerationJob.objects.select_for_update().get(pk=job_id)
        if job.status != "running" or job.generation != generation:
            return {"status": job.status}
        if job.attempts >= settings.KEYWORD_GENERATION_MAX_PROVIDER_ATTEMPTS:
            return _terminal_locked(job, status="failed", code=code)
        job.status = "retry_wait"
        job.retry_count += 1
        job.next_attempt_at = timezone.now() + timedelta(
            seconds=min(
                900,
                settings.KEYWORD_GENERATION_RETRY_BASE_SECONDS * 2 ** min(job.retry_count - 1, 5),
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
        _safe_event(
            job,
            "retry_scheduled",
            code=code,
            summary={"retry_count": job.retry_count},
        )
        return {"status": "retry_wait", "code": code}


def _generated_items(job, response):
    if response.model_key != job.model_key:
        raise KeywordGenerationInvalidResponse
    raw = [
        {
            "text": item.text,
            "structure_type": item.structure_type,
            "is_regional": item.is_regional,
            "region_level": item.region_level or "",
            "region_text": item.region_text or "",
            "base_keyword_text": item.base_keyword,
            "business_category": item.business_category,
            "search_intent": item.search_intent,
            "relevance_score": item.relevance_score,
            "priority": item.priority,
            "ai_reason": item.ai_reason,
        }
        for item in response.items
    ]
    try:
        normalized = normalize_generated_keyword_items(
            raw,
            target_count=job.target_count,
        )
    except KeywordNormalizationError as exc:
        raise KeywordGenerationInvalidResponse from exc
    if len(normalized) != job.target_count:
        raise KeywordGenerationInvalidResponse
    allowed_structures = set()
    if job.include_short:
        allowed_structures.add("short")
    if job.include_long_tail:
        allowed_structures.add("long_tail")
    if not allowed_structures:
        allowed_structures.add("general")
    allowed_regions = {normalize_plain_text(value, max_length=200)[1] for value in job.regions}
    for item in normalized:
        if item.structure_type not in allowed_structures:
            raise KeywordGenerationInvalidResponse
        if item.is_regional:
            if not job.include_regional:
                raise KeywordGenerationInvalidResponse
            region_key = normalize_plain_text(
                item.region_text,
                max_length=200,
            )[1]
            if region_key not in allowed_regions:
                raise KeywordGenerationInvalidResponse
    return normalized


def _safe_provider_metrics(metrics):
    if not isinstance(metrics, dict):
        return {}
    allowed = {
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "item_count",
        "mock",
    }
    result = {}
    for key, value in metrics.items():
        if key in allowed and (
            isinstance(value, bool) or (type(value) is int and 0 <= value <= 2**63 - 1)
        ):
            result[key] = value
    return result


def _finalize_success(job_id, generation, response):
    with transaction.atomic():
        job = (
            KeywordGenerationJob.objects.select_for_update()
            .select_related("subject", "subject_version")
            .get(pk=job_id)
        )
        if job.status == "succeeded":
            return {"status": "succeeded"}
        if job.status != "running" or job.generation != generation:
            return {"status": job.status}
        subject = job.subject.__class__.objects.select_for_update().get(pk=job.subject_id)
        if subject.current_version_id != job.subject_version_id:
            return _terminal_locked(
                job,
                status="conflict",
                code="KEYWORD_SUBJECT_VERSION_CONFLICT",
            )
        keyword_set = KeywordSet.objects.select_for_update().filter(subject=subject).first()
        actual_version = keyword_set.version if keyword_set is not None else 0
        if actual_version != job.expected_keyword_set_version:
            return _terminal_locked(
                job,
                status="conflict",
                code="KEYWORD_VERSION_CONFLICT",
            )
        normalized = _generated_items(job, response)
        payload = [item.semantic_payload() for item in normalized]
        try:
            updated = replace_keyword_draft_from_generation(
                user_id=job.user_id,
                subject_id=job.subject_id,
                expected_version=job.expected_keyword_set_version,
                expected_subject_version_id=job.subject_version_id,
                items=payload,
            )
        except KeywordVersionNoChanges:
            return _terminal_locked(
                job,
                status="conflict",
                code="KEYWORD_VERSION_NO_CHANGES",
            )
        except KeywordError as exc:
            status = (
                "conflict"
                if exc.code
                in {
                    "KEYWORD_VERSION_CONFLICT",
                    "KEYWORD_SUBJECT_VERSION_CONFLICT",
                }
                else "failed"
            )
            return _terminal_locked(job, status=status, code=exc.code)

        output_digest = canonical_digest(payload)
        KeywordGenerationResult.objects.create(
            job=job,
            output_snapshot=payload,
            output_digest=output_digest,
            item_count=len(payload),
            applied_keyword_set_version=updated.version,
            provider_metrics=_safe_provider_metrics(response.provider_metrics),
        )
        _settle_quota(job, "consume")
        job.status = "succeeded"
        job.finished_at = timezone.now()
        job.next_attempt_at = None
        job.stable_error_code = ""
        job.version += 1
        job.save(
            update_fields=[
                "status",
                "finished_at",
                "next_attempt_at",
                "stable_error_code",
                "version",
                "updated_at",
            ]
        )
        _safe_event(
            job,
            "succeeded",
            summary={
                "item_count": len(payload),
                "keyword_set_version": updated.version,
            },
        )
        return {"status": "succeeded"}


def execute_keyword_generation(*, job_id, expected_generation=None):
    claimed = claim_keyword_generation_job(
        job_id=job_id,
        expected_generation=expected_generation,
    )
    if claimed is None:
        row = KeywordGenerationJob.objects.get(pk=job_id)
        return {"status": row.status}
    _, generation = claimed
    job = KeywordGenerationJob.objects.get(pk=job_id)
    try:
        provider = get_keyword_generation_provider(job.provider_key)
        response = provider.generate(_request_for_job(job))
        return _finalize_success(job_id, generation, response)
    except KeywordGenerationProviderError as exc:
        if not exc.permanent:
            return _schedule_retry(job_id, generation, exc.code)
        with transaction.atomic():
            locked = KeywordGenerationJob.objects.select_for_update().get(pk=job_id)
            if locked.status != "running" or locked.generation != generation:
                return {"status": locked.status}
            return _terminal_locked(
                locked,
                status="failed",
                code=exc.code,
            )
    except KeywordGenerationError as exc:
        if not getattr(exc, "permanent", True):
            return _schedule_retry(job_id, generation, exc.code)
        with transaction.atomic():
            locked = KeywordGenerationJob.objects.select_for_update().get(pk=job_id)
            if locked.status != "running" or locked.generation != generation:
                return {"status": locked.status}
            return _terminal_locked(
                locked,
                status="failed",
                code=exc.code,
            )
    except Exception as exc:
        raise KeywordGenerationUnexpectedError(
            job_id=job_id,
            generation=generation,
        ) from exc


def fail_internal_keyword_generation(*, job_id, generation):
    with transaction.atomic():
        job = KeywordGenerationJob.objects.select_for_update().get(pk=job_id)
        if job.status != "running" or str(job.generation) != str(generation):
            return {"status": job.status}
        return _terminal_locked(
            job,
            status="failed",
            code="KEYWORD_GENERATION_INTERNAL_ERROR",
        )


def due_keyword_generation_job_ids(limit=100):
    now = timezone.now()
    stale = now - timedelta(seconds=settings.KEYWORD_GENERATION_RUNNING_STALE_SECONDS)
    return list(
        KeywordGenerationJob.objects.filter(
            models.Q(status="queued")
            | models.Q(status="retry_wait", next_attempt_at__lte=now)
            | models.Q(status="running", started_at__lte=stale)
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)[:limit]
    )


def keyword_generation_quota_payload(job):
    account = (
        QuotaAccount.objects.filter(
            subscription=job.subscription,
            subject=job.subject,
            quota_type="keyword_regenerations",
        )
        .order_by("-cycle_started_at", "-created_at")
        .first()
    )
    return {
        "billing_mode": job.billing_mode,
        "held": (job.quota_hold_id is not None and job.status not in _TERMINAL),
        "remaining": account.available if account is not None else None,
    }
