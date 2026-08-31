from __future__ import annotations

import copy
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.http import Http404
from django.utils import timezone

from apps.ai.sanitization import sanitize_provider_metrics
from apps.quotas.models import QuotaAccount
from apps.quotas.services import (
    consume_hold,
    freeze_quota,
    get_or_create_subject_cycle_account,
    release_hold,
)
from apps.subjects.subject_services import subject_for_user_or_404

from .distillation_contracts import DistillationKeywordInput, DistillationRequest
from .distillation_exceptions import (
    DistillationError,
    DistillationIdempotencyConflict,
    DistillationInProgress,
    DistillationInvalidResponse,
    DistillationKeywordVersionConflict,
    DistillationProviderError,
    DistillationRegenerationConfirmationRequired,
    DistillationUnexpectedError,
    DistillationValuesInvalid,
    DistillationVersionConflict,
    DistillationVersionNoChanges,
)
from .distillation_idempotency import canonical_digest, derive_distillation_idempotency
from .distillation_providers import (
    get_distillation_provider,
    require_available_distillation_provider,
)
from .distillation_validation import validate_provider_response, validate_user_adjustments
from .models import (
    DistillationDraftItem,
    DistillationEvent,
    DistillationItem,
    DistillationJob,
    DistillationResult,
    DistillationSet,
    DistillationWorkspace,
    KeywordSet,
    KeywordSetVersion,
)
from .services import _assert_user_write_allowed, _lock_effective_subscription

User = get_user_model()
_TERMINAL = {"succeeded", "failed", "conflict", "superseded"}


def _safe_event(job, event_type, *, code="", summary=None):
    return DistillationEvent.objects.create(
        job=job,
        event_type=event_type,
        stable_error_code=code,
        safe_summary=copy.deepcopy(summary or {}),
        request_id=job.request_id,
        correlation_id=job.correlation_id,
    )


def _subject_values(subject_version):
    values = copy.deepcopy(subject_version.field_values)
    values["official_name"] = subject_version.official_name
    return values


def _keyword_snapshot(version):
    return [
        {
            "id": str(item.pk),
            "text": item.text,
            "structure_type": item.structure_type,
            "is_regional": item.is_regional,
            "region_level": item.region_level,
            "region_text": item.region_text,
            "region_matching_key": item.region_matching_key,
            "business_category": item.business_category,
            "search_intent": item.search_intent,
            "relevance_score": item.relevance_score,
            "priority": item.priority,
            "sort_order": item.sort_order,
        }
        for item in version.keywords.order_by("sort_order", "id")
    ]


def _input_objects(snapshot):
    return tuple(
        DistillationKeywordInput(
            id=item["id"],
            text=item["text"],
            structure_type=item["structure_type"],
            is_regional=item["is_regional"],
            region_level=item["region_level"],
            region_text=item["region_text"],
            region_matching_key=item["region_matching_key"],
            business_category=item["business_category"],
            search_intent=item["search_intent"],
            relevance_score=item["relevance_score"],
            priority=item["priority"],
        )
        for item in snapshot
    )


def _request_payload(*, subject_id, keyword_set_version_id, expected_workspace_version, regenerate):
    return {
        "subject_id": str(subject_id),
        "keyword_set_version_id": str(keyword_set_version_id),
        "expected_workspace_version": expected_workspace_version,
        "regenerate": regenerate,
    }


@transaction.atomic
def create_distillation_job(
    *,
    user_id,
    subject_id,
    keyword_set_version_id,
    expected_workspace_version: int,
    regenerate: bool,
    idempotency_key: str,
    request_id,
):
    if type(expected_workspace_version) is not int or expected_workspace_version < 0:
        raise DistillationVersionConflict
    if type(regenerate) is not bool:
        raise DistillationValuesInvalid
    idem = derive_distillation_idempotency(
        user_id=user_id,
        subject_id=subject_id,
        raw_key=idempotency_key,
    )
    payload = _request_payload(
        subject_id=subject_id,
        keyword_set_version_id=keyword_set_version_id,
        expected_workspace_version=expected_workspace_version,
        regenerate=regenerate,
    )
    request_digest = canonical_digest(payload)
    user = User.objects.select_for_update().get(pk=user_id)
    replay = DistillationJob.objects.filter(idempotency_key_digest=idem).first()
    if replay is not None:
        if (
            replay.user_id != user.pk
            or str(replay.subject_id) != str(subject_id)
            or replay.request_digest != request_digest
        ):
            raise DistillationIdempotencyConflict
        return replay, False

    _assert_user_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.status != subject.Status.ACTIVE or subject.current_version_id is None:
        raise DistillationKeywordVersionConflict
    subscription = _lock_effective_subscription(user)
    try:
        input_version = (
            KeywordSetVersion.objects.select_related("keyword_set", "subject_version")
            .prefetch_related("keywords")
            .get(pk=keyword_set_version_id, subject=subject)
        )
    except KeywordSetVersion.DoesNotExist as exc:
        raise DistillationKeywordVersionConflict from exc
    keyword_set = KeywordSet.objects.select_for_update().get(subject=subject)
    if (
        keyword_set.current_version_id != input_version.pk
        or subject.current_version_id != input_version.subject_version_id
    ):
        raise DistillationKeywordVersionConflict
    if DistillationJob.objects.filter(
        subject=subject,
        status__in=("queued", "running", "retry_wait"),
    ).exists():
        raise DistillationInProgress
    workspace = DistillationWorkspace.objects.select_for_update().filter(subject=subject).first()
    actual_version = workspace.version if workspace is not None else 0
    if actual_version != expected_workspace_version:
        raise DistillationVersionConflict

    provider = require_available_distillation_provider()
    prior_success = DistillationJob.objects.filter(
        subject=subject,
        status=DistillationJob.Status.SUCCEEDED,
    ).exists()
    if prior_success and not regenerate:
        raise DistillationRegenerationConfirmationRequired
    billing_mode = (
        DistillationJob.BillingMode.REGENERATION
        if prior_success
        else DistillationJob.BillingMode.FREE_INITIAL
    )
    job_id = uuid.uuid4()
    quota_hold = None
    if billing_mode == DistillationJob.BillingMode.REGENERATION:
        account = get_or_create_subject_cycle_account(
            subscription=subscription,
            subject=subject,
            quota_type="distillation_regenerations",
            request_id=request_id,
        )
        quota_hold = freeze_quota(
            account_id=account.pk,
            amount=1,
            business_type="keyword_distillation",
            business_id=job_id,
            idempotency_key=f"keyword-distillation-freeze-{job_id}",
            request_id=request_id,
        )

    subject_values = _subject_values(input_version.subject_version)
    keywords = _keyword_snapshot(input_version)
    if not keywords:
        raise DistillationValuesInvalid
    input_digest = canonical_digest(
        {
            "subject_version_id": str(input_version.subject_version_id),
            "subject_values": subject_values,
            "keyword_set_version_id": str(input_version.pk),
            "keywords": keywords,
        }
    )
    try:
        job = DistillationJob.objects.create(
            id=job_id,
            user=user,
            subject=subject,
            subject_version=input_version.subject_version,
            input_keyword_set_version=input_version,
            subscription=subscription,
            quota_hold=quota_hold,
            billing_mode=billing_mode,
            expected_workspace_version=expected_workspace_version,
            input_subject_values=subject_values,
            input_keywords=keywords,
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
        raise DistillationInProgress from exc
    return job, True


def distillation_job_for_user_or_404(*, user, job_id):
    try:
        return DistillationJob.objects.select_related(
            "subject",
            "subject_version",
            "input_keyword_set_version",
            "quota_hold",
        ).get(pk=job_id, user=user)
    except DistillationJob.DoesNotExist as exc:
        raise Http404 from exc


def distillation_workspace_for_subject(*, user, subject):
    subject_for_user_or_404(user=user, subject_id=subject.pk)
    return (
        DistillationWorkspace.objects.select_related(
            "draft_input_version__subject_version",
            "draft_source_result__job",
            "current_set",
        )
        .filter(subject=subject)
        .first()
    )


def _request_for_job(job):
    return DistillationRequest(
        job_id=str(job.pk),
        subject_id=str(job.subject_id),
        subject_version_id=str(job.subject_version_id),
        keyword_set_version_id=str(job.input_keyword_set_version_id),
        subject_values=copy.deepcopy(job.input_subject_values),
        keywords=_input_objects(job.input_keywords),
    )


def claim_distillation_job(*, job_id, expected_generation=None):
    now = timezone.now()
    with transaction.atomic():
        job = DistillationJob.objects.select_for_update().get(pk=job_id)
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
            > now - timedelta(seconds=settings.DISTILLATION_RUNNING_STALE_SECONDS)
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
        idempotency_key=f"keyword-distillation-{action}-{job.pk}",
        request_id=job.request_id,
    )


def _terminal_locked(job, *, status, code, summary=None):
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
    _safe_event(job, status, code=code, summary=summary)
    return {"status": status, "code": code}


def _schedule_retry(job_id, generation, code):
    with transaction.atomic():
        job = DistillationJob.objects.select_for_update().get(pk=job_id)
        if job.status != "running" or job.generation != generation:
            return {"status": job.status}
        if job.attempts >= settings.DISTILLATION_MAX_PROVIDER_ATTEMPTS:
            return _terminal_locked(job, status="failed", code=code)
        job.status = "retry_wait"
        job.retry_count += 1
        job.next_attempt_at = timezone.now() + timedelta(
            seconds=min(
                900,
                settings.DISTILLATION_RETRY_BASE_SECONDS * 2 ** min(job.retry_count - 1, 5),
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


def _safe_provider_metrics(metrics):
    return sanitize_provider_metrics(metrics)


def _replace_workspace_draft(*, workspace, normalized, source_order):
    DistillationDraftItem.objects.filter(workspace=workspace).delete()
    order = {uuid.UUID(value): index for index, value in enumerate(source_order)}
    DistillationDraftItem.objects.bulk_create(
        [
            DistillationDraftItem(
                workspace=workspace,
                source_keyword_id=item.source_keyword_id,
                action=item.action,
                canonical_keyword_id=item.canonical_keyword_id,
                merge_group_key=item.merge_group_key,
                ai_action=item.action,
                ai_canonical_keyword_id=item.canonical_keyword_id,
                ai_merge_group_key=item.merge_group_key,
                ai_reason=item.reason,
                user_reason="",
                user_overridden=False,
                sort_order=order[item.source_keyword_id],
            )
            for item in normalized
        ]
    )


def _finalize_success(job_id, generation, response):
    with transaction.atomic():
        job = (
            DistillationJob.objects.select_for_update()
            .select_related("subject", "subject_version", "input_keyword_set_version")
            .get(pk=job_id)
        )
        if job.status == "succeeded":
            return {"status": "succeeded"}
        if job.status != "running" or job.generation != generation:
            return {"status": job.status}
        subject = job.subject.__class__.objects.select_for_update().get(pk=job.subject_id)
        keyword_set = KeywordSet.objects.select_for_update().get(subject=subject)
        if (
            subject.current_version_id != job.subject_version_id
            or keyword_set.current_version_id != job.input_keyword_set_version_id
        ):
            return _terminal_locked(
                job,
                status="conflict",
                code="DISTILLATION_KEYWORD_VERSION_CONFLICT",
            )
        workspace = (
            DistillationWorkspace.objects.select_for_update().filter(subject=subject).first()
        )
        actual_version = workspace.version if workspace is not None else 0
        if actual_version != job.expected_workspace_version:
            return _terminal_locked(job, status="conflict", code="DISTILLATION_VERSION_CONFLICT")
        if response.model_key != job.model_key:
            raise DistillationInvalidResponse
        inputs = _input_objects(job.input_keywords)
        normalized = validate_provider_response(inputs=inputs, response=response)
        source_order = [item["id"] for item in job.input_keywords]
        normalized.sort(key=lambda item: source_order.index(str(item.source_keyword_id)))
        output = [item.payload() for item in normalized]
        next_workspace_version = 1 if workspace is None else workspace.version + 1
        result = DistillationResult.objects.create(
            job=job,
            output_snapshot=output,
            output_digest=canonical_digest(output),
            item_count=len(output),
            applied_workspace_version=next_workspace_version,
            provider_metrics=_safe_provider_metrics(response.provider_metrics),
        )
        if workspace is None:
            workspace = DistillationWorkspace.objects.create(
                user_id=job.user_id,
                subject=subject,
                draft_input_version=job.input_keyword_set_version,
                draft_source_result=result,
                version=1,
            )
        else:
            workspace.version += 1
            workspace.draft_input_version = job.input_keyword_set_version
            workspace.draft_source_result = result
            workspace.save(
                update_fields=[
                    "draft_input_version",
                    "draft_source_result",
                    "version",
                    "updated_at",
                ]
            )
        _replace_workspace_draft(
            workspace=workspace,
            normalized=normalized,
            source_order=source_order,
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
            summary={"item_count": len(output), "workspace_version": workspace.version},
        )
        return {"status": "succeeded"}


def execute_distillation(*, job_id, expected_generation=None):
    claimed = claim_distillation_job(job_id=job_id, expected_generation=expected_generation)
    if claimed is None:
        return {"status": DistillationJob.objects.get(pk=job_id).status}
    _, generation = claimed
    job = DistillationJob.objects.get(pk=job_id)
    try:
        provider = get_distillation_provider(job.provider_key)
        response = provider.distill(_request_for_job(job))
        return _finalize_success(job_id, generation, response)
    except DistillationProviderError as exc:
        if not exc.permanent:
            return _schedule_retry(job_id, generation, exc.code)
        with transaction.atomic():
            locked = DistillationJob.objects.select_for_update().get(pk=job_id)
            if locked.status != "running" or locked.generation != generation:
                return {"status": locked.status}
            return _terminal_locked(locked, status="failed", code=exc.code)
    except DistillationError as exc:
        if not getattr(exc, "permanent", True):
            return _schedule_retry(job_id, generation, exc.code)
        with transaction.atomic():
            locked = DistillationJob.objects.select_for_update().get(pk=job_id)
            if locked.status != "running" or locked.generation != generation:
                return {"status": locked.status}
            return _terminal_locked(
                locked,
                status="failed",
                code=exc.code,
                summary=getattr(exc, "diagnostic", None),
            )
    except Exception as exc:
        raise DistillationUnexpectedError(job_id=job_id, generation=generation) from exc


def fail_internal_distillation(*, job_id, generation):
    with transaction.atomic():
        job = DistillationJob.objects.select_for_update().get(pk=job_id)
        if job.status != "running" or str(job.generation) != str(generation):
            return {"status": job.status}
        return _terminal_locked(job, status="failed", code="DISTILLATION_INTERNAL_ERROR")


def due_distillation_job_ids(limit=100):
    now = timezone.now()
    stale = now - timedelta(seconds=settings.DISTILLATION_RUNNING_STALE_SECONDS)
    return list(
        DistillationJob.objects.filter(
            models.Q(status="queued")
            | models.Q(status="retry_wait", next_attempt_at__lte=now)
            | models.Q(status="running", started_at__lte=stale)
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)[:limit]
    )


def distillation_quota_payload(job):
    account = (
        QuotaAccount.objects.filter(
            subscription=job.subscription,
            subject=job.subject,
            quota_type="distillation_regenerations",
        )
        .order_by("-cycle_started_at", "-created_at")
        .first()
    )
    return {
        "billing_mode": job.billing_mode,
        "held": job.quota_hold_id is not None and job.status not in _TERMINAL,
        "remaining": account.available if account is not None else None,
    }


def _draft_payload_rows(workspace):
    return [
        {
            "source_keyword_id": str(item.source_keyword_id),
            "action": item.action,
            "canonical_keyword_id": (
                str(item.canonical_keyword_id) if item.canonical_keyword_id else None
            ),
            "merge_group_key": str(item.merge_group_key) if item.merge_group_key else None,
            "user_reason": item.user_reason,
        }
        for item in workspace.draft_items.order_by("sort_order", "id")
    ]


def distillation_draft_content_digest(workspace, *, rows=None):
    """Return the immutable digest used when confirming the current draft.

    Keeping this calculation in one place lets read APIs distinguish an AI/user
    draft that still needs confirmation from the already-confirmed evidence set.
    """
    rows = list(
        rows
        if rows is not None
        else workspace.draft_items.select_related(
            "source_keyword", "canonical_keyword", "ai_canonical_keyword"
        ).order_by("sort_order", "id")
    )
    payload = [
        {
            "source_keyword_id": str(row.source_keyword_id),
            "action": row.action,
            "canonical_keyword_id": (
                str(row.canonical_keyword_id) if row.canonical_keyword_id else None
            ),
            "merge_group_key": str(row.merge_group_key) if row.merge_group_key else None,
            "ai_action": row.ai_action,
            "ai_canonical_keyword_id": (
                str(row.ai_canonical_keyword_id) if row.ai_canonical_keyword_id else None
            ),
            "ai_merge_group_key": (
                str(row.ai_merge_group_key) if row.ai_merge_group_key else None
            ),
            "ai_reason": row.ai_reason,
            "user_reason": row.user_reason,
            "user_overridden": row.user_overridden,
            "sort_order": row.sort_order,
        }
        for row in rows
    ]
    return canonical_digest(
        {
            "subject_version_id": str(workspace.draft_input_version.subject_version_id),
            "keyword_set_version_id": str(workspace.draft_input_version_id),
            "source_result_id": str(workspace.draft_source_result_id),
            "items": payload,
        }
    )


@transaction.atomic
def save_distillation_draft(*, user_id, subject_id, expected_version: int, items):
    user = User.objects.select_for_update().get(pk=user_id)
    _assert_user_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    _lock_effective_subscription(user)
    try:
        workspace = (
            DistillationWorkspace.objects.select_for_update()
            .select_related("draft_input_version", "draft_source_result")
            .get(subject=subject)
        )
    except DistillationWorkspace.DoesNotExist as exc:
        raise DistillationValuesInvalid from exc
    if workspace.version != expected_version:
        raise DistillationVersionConflict
    keyword_set = KeywordSet.objects.select_for_update().get(subject=subject)
    if (
        keyword_set.current_version_id != workspace.draft_input_version_id
        or subject.current_version_id != workspace.draft_input_version.subject_version_id
    ):
        raise DistillationKeywordVersionConflict
    inputs = _input_objects(_keyword_snapshot(workspace.draft_input_version))
    normalized = validate_user_adjustments(
        inputs=inputs,
        ai_items=workspace.draft_source_result.output_snapshot,
        items=items,
    )
    new_payload = [
        {
            "source_keyword_id": str(item["source_keyword_id"]),
            "action": item["action"],
            "canonical_keyword_id": (
                str(item["canonical_keyword_id"]) if item["canonical_keyword_id"] else None
            ),
            "merge_group_key": str(item["merge_group_key"]) if item["merge_group_key"] else None,
            "user_reason": item["user_reason"],
        }
        for item in normalized
    ]
    if _draft_payload_rows(workspace) == new_payload:
        return workspace, False
    DistillationDraftItem.objects.filter(workspace=workspace).delete()
    DistillationDraftItem.objects.bulk_create(
        [
            DistillationDraftItem(
                workspace=workspace,
                sort_order=index,
                **item,
            )
            for index, item in enumerate(normalized)
        ]
    )
    workspace.version += 1
    workspace.save(update_fields=["version", "updated_at"])
    return workspace, True


@transaction.atomic
def confirm_distillation(*, user_id, subject_id, expected_version: int):
    user = User.objects.select_for_update().get(pk=user_id)
    _assert_user_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    _lock_effective_subscription(user)
    try:
        workspace = (
            DistillationWorkspace.objects.select_for_update()
            .select_related("draft_input_version__subject_version", "draft_source_result")
            .get(subject=subject)
        )
    except DistillationWorkspace.DoesNotExist as exc:
        raise DistillationValuesInvalid from exc
    if workspace.version != expected_version:
        raise DistillationVersionConflict
    keyword_set = KeywordSet.objects.select_for_update().get(subject=subject)
    if (
        keyword_set.current_version_id != workspace.draft_input_version_id
        or subject.current_version_id != workspace.draft_input_version.subject_version_id
    ):
        raise DistillationKeywordVersionConflict
    rows = list(
        workspace.draft_items.select_related(
            "source_keyword", "canonical_keyword", "ai_canonical_keyword"
        ).order_by("sort_order", "id")
    )
    if not rows or len(rows) != workspace.draft_input_version.item_count:
        raise DistillationValuesInvalid
    digest = distillation_draft_content_digest(workspace, rows=rows)
    if (
        workspace.current_set is not None
        and workspace.current_set.input_keyword_set_version_id == workspace.draft_input_version_id
        and workspace.current_set.content_digest == digest
    ):
        raise DistillationVersionNoChanges
    next_version = 1 if workspace.current_set is None else workspace.current_set.version_no + 1
    version = DistillationSet.objects.create(
        workspace=workspace,
        user=user,
        subject=subject,
        subject_version=workspace.draft_input_version.subject_version,
        input_keyword_set_version=workspace.draft_input_version,
        source_result=workspace.draft_source_result,
        version_no=next_version,
        content_digest=digest,
        item_count=len(rows),
        confirmed_by=user,
        confirmed_at=timezone.now(),
    )
    DistillationItem.objects.bulk_create(
        [
            DistillationItem(
                distillation_set=version,
                source_keyword=row.source_keyword,
                action=row.action,
                canonical_keyword=row.canonical_keyword,
                merge_group_key=row.merge_group_key,
                ai_action=row.ai_action,
                ai_canonical_keyword=row.ai_canonical_keyword,
                ai_merge_group_key=row.ai_merge_group_key,
                ai_reason=row.ai_reason,
                user_reason=row.user_reason,
                user_overridden=row.user_overridden,
                sort_order=row.sort_order,
            )
            for row in rows
        ]
    )
    workspace.current_set = version
    workspace.version += 1
    workspace.save(update_fields=["current_set", "version", "updated_at"])
    return workspace, version


def current_distillation_for_user_or_404(*, user, subject_id):
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    try:
        workspace = DistillationWorkspace.objects.select_related("current_set").get(
            subject=subject
        )
    except DistillationWorkspace.DoesNotExist as exc:
        raise Http404 from exc
    if workspace.current_set_id is None:
        raise Http404
    return DistillationSet.objects.select_related(
        "subject_version", "input_keyword_set_version", "source_result__job"
    ).get(pk=workspace.current_set_id)
