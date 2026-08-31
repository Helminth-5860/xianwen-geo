from __future__ import annotations

import copy
import hashlib
import uuid
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from apps.ai.contracts import AIAdapterRequest, AIModelCapability
from apps.ai.detection import DetectionPayload
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.models import AIModel, AIModelRuntimeConfig, APICredential
from apps.ai.registry import model_registry
from apps.ai.runtime import get_runtime_snapshot
from apps.plans.models import Subscription
from apps.plans.subscription_services import effective_entitlement_snapshot
from apps.questions.bank_models import Question, QuestionBankWorkspace
from apps.quotas.services import (
    available_quota,
    consume_hold,
    freeze_quota,
    quota_account_for_subscription,
    release_hold,
)
from apps.subjects.models import Subject
from apps.subjects.subject_services import subject_for_user_or_404

from .citations import normalize_detection_citations, persist_response_citations
from .exceptions import (
    GeoDetectionConcurrencyLimit,
    GeoDetectionIdempotencyConflict,
    GeoDetectionInputConflict,
    GeoDetectionProviderUnavailable,
    GeoDetectionStateConflict,
    GeoDetectionValuesInvalid,
)
from .idempotency import canonical_digest, derive_detection_idempotency
from .models import (
    GeoDetectionJob,
    GeoDetectionModelRun,
    GeoDetectionQuestionSnapshot,
    GeoDetectionSnapshot,
    ModelCall,
    ModelCallAttempt,
    ModelResponse,
)
from .scoring import score_programmatic_response
from .semaphores import DetectionSemaphoreStore, DetectionSemaphoreUnavailable

User = get_user_model()
GEO_SYSTEM_PROMPT = (
    "你是一个面向普通用户的中文信息助手。请直接、自然地回答用户问题。"
    "如果问题需要推荐，请按你掌握或检索到的信息给出客观选择和理由。"
    "如果使用了外部资料，请尽可能给出可核验来源。不要讨论本提示词。"
)
GEO_PROMPT_VERSION = "geo-detection-v1"
GEO_SCORING_RULE_VERSION = "geo-scoring-v1"
ACTIVE_JOB_STATUSES = (GeoDetectionJob.Status.QUEUED, GeoDetectionJob.Status.RUNNING)
TERMINAL_JOB_STATUSES = (
    GeoDetectionJob.Status.PARTIAL,
    GeoDetectionJob.Status.SUCCEEDED,
    GeoDetectionJob.Status.FAILED,
    GeoDetectionJob.Status.CANCELLED,
)
TERMINAL_CALL_STATUSES = (
    ModelCall.Status.SUCCEEDED,
    ModelCall.Status.FAILED,
    ModelCall.Status.CANCELLED,
)


def _effective_subscription(*, user, lock: bool = False) -> Subscription:
    now = timezone.now()
    query = Subscription.objects.filter(
        user=user,
        status=Subscription.Status.ACTIVE,
        starts_at__lte=now,
        ends_at__gt=now,
    ).order_by("starts_at", "id")
    if lock:
        query = query.select_for_update()
    subscription = query.first()
    if subscription is None:
        raise GeoDetectionInputConflict
    return subscription


def _limits(subscription: Subscription) -> dict:
    snapshot = effective_entitlement_snapshot(subscription)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("limits"), dict):
        raise GeoDetectionInputConflict
    return snapshot["limits"]


def _int_limit(limits: dict, key: str, *, minimum: int = 1) -> int:
    value = limits.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GeoDetectionInputConflict
    return value


def _model_permissions(subscription: Subscription) -> list[dict]:
    rows = effective_entitlement_snapshot(subscription).get("model_permissions")
    if not isinstance(rows, list) or not rows:
        raise GeoDetectionInputConflict
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise GeoDetectionInputConflict
        model_key = row.get("model_key")
        selected = row.get("selected_by_default")
        sort_order = row.get("sort_order")
        if (
            not isinstance(model_key, str)
            or type(selected) is not bool
            or type(sort_order) is not int
        ):
            raise GeoDetectionInputConflict
        normalized.append(
            {"model_key": model_key, "selected_by_default": selected, "sort_order": sort_order}
        )
    return sorted(normalized, key=lambda item: (item["sort_order"], item["model_key"]))


def _credential_configured(provider_id) -> bool:
    return APICredential.objects.filter(
        provider_id=provider_id,
        environment=settings.API_CREDENTIAL_ENVIRONMENT,
        status=APICredential.Status.ACTIVE,
    ).exists()


def available_models_for_subscription(subscription: Subscription) -> list[dict]:
    permissions = _model_permissions(subscription)
    permission_by_key = {row["model_key"]: row for row in permissions}
    rows = (
        AIModelRuntimeConfig.objects.select_related("model__provider")
        .filter(model__model_key__in=permission_by_key, enabled=True, paused=False)
        .order_by("sort_order", "model__canonical_order", "model__model_key")
    )
    result = []
    for config in rows:
        permission = permission_by_key[config.model.model_key]
        adapter_available = True
        try:
            model_registry.resolve(
                provider_key=config.model.provider.provider_key,
                model_key=config.model.model_key,
                capability=AIModelCapability.GEO_DETECTION,
            )
        except AIAdapterError:
            adapter_available = False
        configured = bool(config.provider_model_id) and _credential_configured(
            config.model.provider_id
        )
        result.append(
            {
                "id": str(config.model_id),
                "model_key": config.model.model_key,
                "provider_key": config.model.provider.provider_key,
                "display_name": config.display_name,
                "selected_by_default": permission["selected_by_default"],
                "sort_order": permission["sort_order"],
                "enabled": config.enabled,
                "paused": config.paused,
                "configured": configured and adapter_available,
                "network_access_enabled": config.network_access_enabled,
                "runtime_version": config.version,
            }
        )
    return result


def models_for_user(*, user) -> dict:
    subscription = _effective_subscription(user=user)
    limits = _limits(subscription)
    return {
        "models": available_models_for_subscription(subscription),
        "allow_user_model_selection": bool(limits.get("allow_user_model_selection", True)),
        "max_models_per_detection": _int_limit(limits, "max_models_per_detection"),
    }


def _current_detection_inputs(*, user, subject: Subject):
    if subject.status != Subject.Status.ACTIVE or subject.current_version_id is None:
        raise GeoDetectionInputConflict
    # A confirmed question-bank version is the detection boundary. It already owns an
    # immutable distillation -> keyword lineage, so newer upstream drafts or confirmed
    # assets must not invalidate questions the user has explicitly saved for detection.
    question_workspace = (
        QuestionBankWorkspace.objects.select_related(
            "current_version__distillation_set__input_keyword_set_version"
        )
        .filter(user=user, subject=subject)
        .first()
    )
    if question_workspace is None or question_workspace.current_version_id is None:
        raise GeoDetectionInputConflict
    question_bank = question_workspace.current_version
    distillation = question_bank.distillation_set if question_bank else None
    keyword_version = distillation.input_keyword_set_version if distillation else None
    if keyword_version is None or distillation is None or question_bank is None:
        raise GeoDetectionInputConflict
    if (
        keyword_version.subject_version_id != subject.current_version_id
        or distillation.subject_version_id != subject.current_version_id
        or question_bank.subject_version_id != subject.current_version_id
        or keyword_version.subject_id != subject.pk
        or distillation.subject_id != subject.pk
        or question_bank.subject_id != subject.pk
        or keyword_version.user_id != user.pk
        or distillation.user_id != user.pk
        or question_bank.user_id != user.pk
    ):
        raise GeoDetectionInputConflict
    return keyword_version, distillation, question_bank


def _detection_account(subscription: Subscription):
    try:
        return quota_account_for_subscription(
            subscription=subscription,
            quota_type="geo_detection_runs",
            legacy_quota_type="detection_points",
        )
    except Exception as exc:
        raise GeoDetectionInputConflict from exc


def _detection_hold_amount(*, quota_type: str, planned_calls: int) -> int:
    """Keep legacy point billing compatible while natural-unit plans charge one run."""

    return planned_calls if quota_type == "detection_points" else 1


def _available_detection_runs(subscription: Subscription) -> int:
    account = _detection_account(subscription)
    return available_quota(subscription=subscription, quota_type=account.quota_type)


def _selection(
    *,
    user,
    subject,
    subscription,
    question_ids,
    model_ids,
    lock: bool = False,
):
    limits = _limits(subscription)
    keyword_version, distillation, question_bank = _current_detection_inputs(
        user=user, subject=subject
    )
    max_questions = _int_limit(limits, "max_questions_per_detection")
    max_models = _int_limit(limits, "max_models_per_detection")
    if not question_ids or len(question_ids) > max_questions:
        raise GeoDetectionValuesInvalid
    if not model_ids or len(model_ids) > max_models:
        raise GeoDetectionValuesInvalid
    question_query = Question.objects.filter(
        pk__in=question_ids, question_bank_version=question_bank
    ).select_related("primary_category")
    if lock:
        question_query = question_query.select_for_update()
    questions = list(question_query.order_by("sort_order", "id"))
    if len(questions) != len(question_ids):
        raise GeoDetectionInputConflict

    permission_rows = _model_permissions(subscription)
    permission_by_key = {row["model_key"]: row for row in permission_rows}
    model_query = AIModel.objects.select_related("provider", "runtime_config").filter(
        pk__in=model_ids
    )
    if lock:
        model_query = model_query.select_for_update(of=("self",))
    models = list(model_query.order_by("canonical_order", "id"))
    if len(models) != len(model_ids):
        raise GeoDetectionValuesInvalid
    selected_keys = {row.model_key for row in models}
    if not selected_keys.issubset(permission_by_key):
        raise GeoDetectionValuesInvalid
    allow_selection = limits.get("allow_user_model_selection", True)
    if type(allow_selection) is not bool:
        raise GeoDetectionInputConflict
    if not allow_selection:
        defaults = {row["model_key"] for row in permission_rows if row["selected_by_default"]}
        if selected_keys != defaults:
            raise GeoDetectionValuesInvalid

    if lock:
        list(
            AIModelRuntimeConfig.objects.select_for_update()
            .filter(model_id__in=[model.pk for model in models])
            .order_by("model_id")
        )

    runtime_snapshots = []
    for model in models:
        snapshot = get_runtime_snapshot(model_key=model.model_key, require_available=True)
        if not snapshot.provider_model_id:
            raise GeoDetectionProviderUnavailable
        if not _credential_configured(model.provider_id):
            raise GeoDetectionProviderUnavailable
        adapter = model_registry.resolve(
            provider_key=snapshot.provider_key,
            model_key=snapshot.model_key,
            capability=AIModelCapability.GEO_DETECTION,
        )
        runtime_snapshots.append(
            {
                **asdict(snapshot),
                "input_cost": str(snapshot.input_cost) if snapshot.input_cost is not None else None,
                "output_cost": str(snapshot.output_cost)
                if snapshot.output_cost is not None
                else None,
                "request_cost": str(snapshot.request_cost)
                if snapshot.request_cost is not None
                else None,
                "adapter_version": adapter.descriptor.adapter_version,
                "prompt_version": adapter.descriptor.prompt_version,
            }
        )
    required = len(questions) * len(models)
    return {
        "limits": limits,
        "keyword_version": keyword_version,
        "distillation": distillation,
        "question_bank": question_bank,
        "questions": questions,
        "models": models,
        "runtime_snapshots": runtime_snapshots,
        "required": required,
    }


def detection_options(*, user, subject_id) -> dict:
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    subscription = _effective_subscription(user=user)
    limits = _limits(subscription)
    _, _, question_bank = _current_detection_inputs(user=user, subject=subject)
    active = GeoDetectionJob.objects.filter(user=user, status__in=ACTIVE_JOB_STATUSES).count()
    concurrency = _int_limit(limits, "concurrent_detection_jobs")
    return {
        "question_bank_version_id": str(question_bank.pk),
        "question_count": question_bank.item_count,
        "max_questions_per_detection": _int_limit(limits, "max_questions_per_detection"),
        "models": available_models_for_subscription(subscription),
        "max_models_per_detection": _int_limit(limits, "max_models_per_detection"),
        "allow_user_model_selection": bool(limits.get("allow_user_model_selection", True)),
        "available_detection_runs": _available_detection_runs(subscription),
        "active_detection_jobs": active,
        "concurrent_detection_jobs": concurrency,
        "can_start_job": active < concurrency,
    }


def estimate_detection(*, user, subject_id, question_ids, model_ids, mode="new") -> dict:
    if mode != "new":
        raise GeoDetectionValuesInvalid
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    subscription = _effective_subscription(user=user)
    selected = _selection(
        user=user,
        subject=subject,
        subscription=subscription,
        question_ids=question_ids,
        model_ids=model_ids,
        lock=False,
    )
    available = _available_detection_runs(subscription)
    active = GeoDetectionJob.objects.filter(user=user, status__in=ACTIVE_JOB_STATUSES).count()
    concurrency = _int_limit(selected["limits"], "concurrent_detection_jobs")
    return {
        "question_count": len(selected["questions"]),
        "model_count": len(selected["models"]),
        "required_detection_runs": 1,
        "available_detection_runs": available,
        "active_detection_jobs": active,
        "concurrent_detection_jobs": concurrency,
        "can_submit": available >= 1 and active < concurrency,
    }


def _request_payload(*, subject_id, question_ids, model_ids, mode):
    return {
        "subject_id": str(subject_id),
        "question_ids": sorted(str(value) for value in question_ids),
        "model_ids": sorted(str(value) for value in model_ids),
        "mode": mode,
    }


@transaction.atomic
def create_detection_job(
    *,
    user_id,
    subject_id,
    question_ids,
    model_ids,
    mode,
    idempotency_key,
    request_id,
):
    if mode != "new":
        raise GeoDetectionValuesInvalid
    try:
        idem = derive_detection_idempotency(
            user_id=user_id, subject_id=subject_id, raw_key=idempotency_key
        )
    except ValueError as exc:
        raise GeoDetectionValuesInvalid from exc
    request_digest = canonical_digest(
        _request_payload(
            subject_id=subject_id, question_ids=question_ids, model_ids=model_ids, mode=mode
        )
    )
    user = User.objects.select_for_update().get(pk=user_id)
    replay = GeoDetectionJob.objects.filter(idempotency_key_digest=idem).first()
    if replay is not None:
        if (
            replay.user_id != user.pk
            or str(replay.subject_id) != str(subject_id)
            or replay.request_digest != request_digest
        ):
            raise GeoDetectionIdempotencyConflict
        return replay, False
    if not user.is_active or user.account_status != user.AccountStatus.ACTIVE:
        raise GeoDetectionInputConflict
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    subscription = _effective_subscription(user=user, lock=True)
    selected = _selection(
        user=user,
        subject=subject,
        subscription=subscription,
        question_ids=question_ids,
        model_ids=model_ids,
        lock=True,
    )
    concurrent_limit = _int_limit(selected["limits"], "concurrent_detection_jobs")
    active_count = (
        GeoDetectionJob.objects.select_for_update()
        .filter(user=user, status__in=ACTIVE_JOB_STATUSES)
        .count()
    )
    if active_count >= concurrent_limit:
        raise GeoDetectionConcurrencyLimit
    job_id = uuid.uuid4()
    account = _detection_account(subscription)
    held_amount = _detection_hold_amount(
        quota_type=account.quota_type,
        planned_calls=selected["required"],
    )
    hold = freeze_quota(
        account_id=account.pk,
        amount=held_amount,
        business_type="geo_detection",
        business_id=job_id,
        idempotency_key=f"geo-detection-freeze-{job_id}",
        request_id=request_id,
    )
    queued_at = timezone.now()
    job = GeoDetectionJob.objects.create(
        id=job_id,
        user=user,
        subject=subject,
        subscription=subscription,
        quota_hold=hold,
        status=GeoDetectionJob.Status.QUEUED,
        mode="new",
        planned_question_count=len(selected["questions"]),
        planned_model_count=len(selected["models"]),
        planned_detection_points=selected["required"],
        queue_priority=subscription.plan_version.queue_priority,
        idempotency_key_digest=idem,
        request_digest=request_digest,
        request_id=request_id,
        queued_at=queued_at,
    )
    model_snapshots = []
    for model, runtime in zip(selected["models"], selected["runtime_snapshots"], strict=True):
        model_snapshots.append(
            {
                "model_id": str(model.pk),
                "model_key": model.model_key,
                "provider_key": model.provider.provider_key,
                **copy.deepcopy(runtime),
            }
        )
    input_digest = canonical_digest(
        {
            "subject_version_id": str(subject.current_version_id),
            "keyword_set_version_id": str(selected["keyword_version"].pk),
            "distillation_set_id": str(selected["distillation"].pk),
            "question_bank_version_id": str(selected["question_bank"].pk),
            "question_ids": [str(row.pk) for row in selected["questions"]],
            "model_snapshots": model_snapshots,
            "system_prompt": GEO_SYSTEM_PROMPT,
            "prompt_version": GEO_PROMPT_VERSION,
            "scoring_rule_version": GEO_SCORING_RULE_VERSION,
        }
    )
    subject_version_id = subject.current_version_id
    if subject_version_id is None:
        raise GeoDetectionInputConflict

    snapshot = GeoDetectionSnapshot.objects.create(
        job=job,
        subject_version_id=subject_version_id,
        keyword_set_version=selected["keyword_version"],
        distillation_set=selected["distillation"],
        question_bank_version=selected["question_bank"],
        entitlement_snapshot=copy.deepcopy(effective_entitlement_snapshot(subscription)),
        model_snapshots=model_snapshots,
        system_prompt=GEO_SYSTEM_PROMPT,
        prompt_version=GEO_PROMPT_VERSION,
        scoring_rule_version=GEO_SCORING_RULE_VERSION,
        input_digest=input_digest,
    )
    question_snapshots = []
    for index, question in enumerate(selected["questions"]):
        question_snapshots.append(
            GeoDetectionQuestionSnapshot.objects.create(
                snapshot=snapshot,
                source_question=question,
                text=question.text,
                primary_category_key=question.primary_category_key,
                primary_category_name=question.primary_category_name,
                primary_category_version=question.primary_category_version,
                priority=question.priority,
                question_type=question.question_type,
                participates_in_scoring=question.participates_in_scoring,
                sort_order=index,
            )
        )
    for model, runtime in zip(selected["models"], selected["runtime_snapshots"], strict=True):
        model_run = GeoDetectionModelRun.objects.create(
            job=job,
            model=model,
            provider_key=model.provider.provider_key,
            model_key=model.model_key,
            provider_model_id=runtime["provider_model_id"],
            runtime_snapshot=copy.deepcopy(runtime),
            adapter_version=runtime["adapter_version"],
            prompt_version=runtime["prompt_version"],
            planned_calls=len(question_snapshots),
        )
        ModelCall.objects.bulk_create(
            [
                ModelCall(
                    job=job,
                    model_run=model_run,
                    question_snapshot=question_snapshot,
                    model=model,
                    provider_key=model.provider.provider_key,
                    model_key=model.model_key,
                    provider_model_id=runtime["provider_model_id"],
                    web_search_requested=bool(runtime["network_access_enabled"]),
                    queued_at=queued_at,
                )
                for question_snapshot in question_snapshots
            ]
        )
    return job, True


def detection_for_user_or_404(*, user, detection_id, lock: bool = False):
    query = GeoDetectionJob.objects.filter(
        user=user,
        user_removed_at__isnull=True,
    ).select_related("quota_hold", "subject")
    if lock:
        query = query.select_for_update()
    try:
        return query.get(pk=detection_id)
    except GeoDetectionJob.DoesNotExist as exc:
        raise Http404 from exc


def queue_position(job: GeoDetectionJob) -> int | None:
    if job.status != GeoDetectionJob.Status.QUEUED:
        return None
    ahead = GeoDetectionJob.objects.filter(status=GeoDetectionJob.Status.QUEUED).filter(
        Q(queue_priority__gt=job.queue_priority)
        | Q(queue_priority=job.queue_priority, queued_at__lt=job.queued_at)
        | Q(queue_priority=job.queue_priority, queued_at=job.queued_at, id__lt=job.pk)
    )
    return ahead.count() + 1


def job_payload(job: GeoDetectionJob) -> dict:
    hold = job.quota_hold
    return {
        "id": str(job.pk),
        "subject_id": str(job.subject_id),
        "status": job.status,
        "version": job.version,
        "planned_question_count": job.planned_question_count,
        "planned_model_count": job.planned_model_count,
        "planned_detection_points": job.planned_detection_points,
        "completed_calls": job.completed_calls,
        "successful_calls": job.successful_calls,
        "failed_calls": job.failed_calls,
        "cancelled_calls": job.cancelled_calls,
        "progress_percent": int(100 * job.completed_calls / job.planned_detection_points),
        "queue_priority": job.queue_priority,
        "queue_position": queue_position(job),
        "cancel_requested": job.cancel_requested_at is not None,
        "quota": {
            "status": hold.status if hold else "settled",
            "held": hold.requested_amount if hold else 0,
            "quota_type": hold.quota_type if hold else "geo_detection_runs",
            "consumed": hold.consumed_amount if hold else 0,
            "released": hold.released_amount if hold else 0,
        },
        "queued_at": job.queued_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "cancelled_at": job.cancelled_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def model_progress_payload(job: GeoDetectionJob) -> list[dict]:
    return [
        {
            "model_id": str(row.model_id),
            "model_key": row.model_key,
            "provider_key": row.provider_key,
            "provider_model_id": row.provider_model_id,
            "status": row.status,
            "planned_calls": row.planned_calls,
            "completed_calls": row.completed_calls,
            "successful_calls": row.successful_calls,
            "failed_calls": row.failed_calls,
            "cancelled_calls": row.cancelled_calls,
            "web_search_used_count": row.web_search_used_count,
            "degraded_count": row.degraded_count,
        }
        for row in job.model_runs.order_by("model__canonical_order", "id")
    ]


def detection_history(*, user, subject_id, page: int = 1, page_size: int = 20):
    subject_for_user_or_404(user=user, subject_id=subject_id)
    page = max(1, int(page))
    page_size = min(20, max(1, int(page_size)))
    query = (
        GeoDetectionJob.objects.filter(
            user=user,
            subject_id=subject_id,
            user_removed_at__isnull=True,
        )
        .select_related("quota_hold", "subject")
        .order_by("-created_at", "-id")
    )
    count = query.count()
    start = (page - 1) * page_size
    rows = list(query[start : start + page_size])
    return rows, {
        "page": page,
        "page_size": page_size,
        "count": count,
        "total_pages": (count + page_size - 1) // page_size if count else 0,
    }


@transaction.atomic
def remove_detection_from_history(*, user, subject_id, detection_id):
    try:
        job = (
            GeoDetectionJob.objects.select_for_update()
            .select_related("quota_hold", "subject")
            .get(pk=detection_id, user=user, subject_id=subject_id)
        )
    except GeoDetectionJob.DoesNotExist as exc:
        raise Http404 from exc
    if job.status not in TERMINAL_JOB_STATUSES:
        raise GeoDetectionStateConflict
    if job.user_removed_at is None:
        job.user_removed_at = timezone.now()
        job.version += 1
        job.save(update_fields=("user_removed_at", "version", "updated_at"))
    return job


def _settle_point(call: ModelCall, *, action: str) -> None:
    if call.settlement_status != ModelCall.Settlement.PENDING:
        return
    if call.job.quota_hold.quota_type == "detection_points":
        key = f"geo-detection-{action}-{call.pk}"
        (consume_hold if action == "consume" else release_hold)(
            hold_id=call.job.quota_hold_id,
            amount=1,
            idempotency_key=key,
            request_id=call.job.request_id,
        )
    if action == "consume":
        call.settlement_status = ModelCall.Settlement.CONSUMED
    else:
        call.settlement_status = ModelCall.Settlement.RELEASED


def _refresh_model_run_locked(model_run: GeoDetectionModelRun) -> None:
    counts = {
        status: model_run.calls.filter(status=status).count() for status in TERMINAL_CALL_STATUSES
    }
    model_run.successful_calls = counts[ModelCall.Status.SUCCEEDED]
    model_run.failed_calls = counts[ModelCall.Status.FAILED]
    model_run.cancelled_calls = counts[ModelCall.Status.CANCELLED]
    model_run.completed_calls = sum(counts.values())
    model_run.web_search_used_count = model_run.calls.filter(
        status=ModelCall.Status.SUCCEEDED, web_search_used=True
    ).count()
    model_run.degraded_count = model_run.calls.filter(
        status=ModelCall.Status.SUCCEEDED, degraded=True
    ).count()
    if model_run.completed_calls < model_run.planned_calls:
        model_run.status = (
            GeoDetectionModelRun.Status.RUNNING
            if model_run.calls.filter(status=ModelCall.Status.RUNNING).exists()
            else GeoDetectionModelRun.Status.QUEUED
        )
    elif model_run.successful_calls == model_run.planned_calls:
        model_run.status = GeoDetectionModelRun.Status.SUCCEEDED
    elif model_run.successful_calls > 0:
        model_run.status = GeoDetectionModelRun.Status.PARTIAL
    elif model_run.cancelled_calls == model_run.planned_calls:
        model_run.status = GeoDetectionModelRun.Status.CANCELLED
    else:
        model_run.status = GeoDetectionModelRun.Status.FAILED
    model_run.save(
        update_fields=(
            "status",
            "completed_calls",
            "successful_calls",
            "failed_calls",
            "cancelled_calls",
            "web_search_used_count",
            "degraded_count",
            "updated_at",
        )
    )


def _refresh_job_locked(job: GeoDetectionJob) -> None:
    counts = {
        status: job.model_calls.filter(status=status).count() for status in TERMINAL_CALL_STATUSES
    }
    job.successful_calls = counts[ModelCall.Status.SUCCEEDED]
    job.failed_calls = counts[ModelCall.Status.FAILED]
    job.cancelled_calls = counts[ModelCall.Status.CANCELLED]
    job.completed_calls = sum(counts.values())
    now = timezone.now()
    if job.completed_calls < job.planned_detection_points:
        if job.started_at is not None:
            job.status = GeoDetectionJob.Status.RUNNING
    else:
        if job.successful_calls == job.planned_detection_points:
            job.status = GeoDetectionJob.Status.SUCCEEDED
        elif job.successful_calls > 0:
            job.status = GeoDetectionJob.Status.PARTIAL
        elif job.cancel_requested_at is not None:
            job.status = GeoDetectionJob.Status.CANCELLED
            job.cancelled_at = now
        else:
            job.status = GeoDetectionJob.Status.FAILED
        job.finished_at = now
        hold = job.quota_hold
        if hold.quota_type == "geo_detection_runs" and hold.status != hold.Status.SETTLED:
            settle = consume_hold if job.successful_calls > 0 else release_hold
            settlement_action = "consume" if job.successful_calls > 0 else "release"
            settle(
                hold_id=hold.pk,
                amount=1,
                idempotency_key=f"geo-detection-run-{settlement_action}-{job.pk}",
                request_id=job.request_id,
            )
    job.version += 1
    job.save(
        update_fields=(
            "status",
            "completed_calls",
            "successful_calls",
            "failed_calls",
            "cancelled_calls",
            "started_at",
            "finished_at",
            "cancelled_at",
            "version",
            "updated_at",
        )
    )


def _terminal_call_locked(
    call: ModelCall,
    *,
    status: str,
    stable_error_code: str = "",
    safe_error_summary: dict | None = None,
) -> bool:
    if call.status in TERMINAL_CALL_STATUSES:
        return False
    if status == ModelCall.Status.SUCCEEDED:
        _settle_point(call, action="consume")
    else:
        _settle_point(call, action="release")
    call.status = status
    call.stable_error_code = stable_error_code
    call.safe_error_summary = copy.deepcopy(safe_error_summary or {})
    call.next_attempt_at = None
    call.generation = None
    call.finished_at = timezone.now()
    call.save(
        update_fields=(
            "status",
            "settlement_status",
            "stable_error_code",
            "safe_error_summary",
            "next_attempt_at",
            "generation",
            "finished_at",
            "updated_at",
        )
    )
    model_run = GeoDetectionModelRun.objects.select_for_update().get(pk=call.model_run_id)
    job = GeoDetectionJob.objects.select_for_update().get(pk=call.job_id)
    _refresh_model_run_locked(model_run)
    _refresh_job_locked(job)
    return True


@transaction.atomic
def cancel_detection(*, user, detection_id):
    job = detection_for_user_or_404(user=user, detection_id=detection_id, lock=True)
    if job.status not in ACTIVE_JOB_STATUSES:
        raise GeoDetectionStateConflict
    if job.cancel_requested_at is None:
        job.cancel_requested_at = timezone.now()
        job.version += 1
        job.save(update_fields=("cancel_requested_at", "version", "updated_at"))
    call_ids = list(
        ModelCall.objects.select_for_update()
        .filter(job=job, status__in=(ModelCall.Status.QUEUED, ModelCall.Status.RETRY_WAIT))
        .values_list("id", flat=True)
    )
    for call_id in call_ids:
        call = ModelCall.objects.select_for_update().get(pk=call_id)
        _terminal_call_locked(
            call,
            status=ModelCall.Status.CANCELLED,
            stable_error_code="GEO_DETECTION_USER_CANCELLED_BEFORE_START",
        )
    job.refresh_from_db()
    return job


def _backoff_seconds(runtime: dict, attempt_count: int) -> int:
    base = int(runtime.get("retry_base_seconds") or 1)
    if runtime.get("retry_backoff") == "fixed":
        return base
    return min(3600, base * (2 ** max(0, attempt_count - 1)))


def _estimated_cost(runtime: dict, response) -> tuple[Decimal | None, str]:
    unit = runtime.get("cost_unit")
    currency = str(runtime.get("currency") or "")
    if unit == "per_request" and runtime.get("request_cost") is not None:
        return Decimal(str(runtime["request_cost"])), currency
    if unit == "per_million_tokens":
        if response.usage.input_tokens is None or response.usage.output_tokens is None:
            return None, currency
        input_cost = Decimal(str(runtime.get("input_cost") or "0"))
        output_cost = Decimal(str(runtime.get("output_cost") or "0"))
        total = (
            Decimal(response.usage.input_tokens) * input_cost
            + Decimal(response.usage.output_tokens) * output_cost
        ) / Decimal(1_000_000)
        return total.quantize(Decimal("0.000001")), currency
    return None, currency


def _adapter_request(call: ModelCall, *, generation: uuid.UUID):
    runtime = call.model_run.runtime_snapshot
    adapter = model_registry.resolve(
        provider_key=call.provider_key,
        model_key=call.model_key,
        capability=AIModelCapability.GEO_DETECTION,
    )
    return adapter, AIAdapterRequest(
        request_id=str(call.pk),
        correlation_id=str(call.job_id),
        identity=adapter.descriptor.identity,
        capability=AIModelCapability.GEO_DETECTION,
        adapter_version=call.model_run.adapter_version,
        prompt_version=call.model_run.prompt_version,
        timeout_seconds=int(runtime["timeout_seconds"]),
        payload=DetectionPayload(
            provider_model_id=call.provider_model_id,
            system_prompt=call.job.snapshot.system_prompt,
            user_question=call.question_snapshot.text,
            web_search_requested=call.web_search_requested,
            temperature=0.2,
            max_output_tokens=None,
        ),
        metadata={"model_call_id": str(call.pk), "attempt_generation": str(generation)},
    )


def _live_model_available(call: ModelCall) -> bool:
    try:
        config = AIModelRuntimeConfig.objects.get(model_id=call.model_id)
    except AIModelRuntimeConfig.DoesNotExist:
        return False
    return bool(config.enabled and not config.paused)


def execute_model_call(*, call_id, semaphore_store: DetectionSemaphoreStore | None = None):
    try:
        call = ModelCall.objects.select_related(
            "job__snapshot", "question_snapshot", "model_run", "model"
        ).get(pk=call_id)
    except ModelCall.DoesNotExist:
        return {"status": "missing", "terminal_transition": False}
    now = timezone.now()
    if call.status not in (ModelCall.Status.QUEUED, ModelCall.Status.RETRY_WAIT):
        return {"status": call.status, "terminal_transition": False}
    if call.next_attempt_at is not None and call.next_attempt_at > now:
        return {"status": call.status, "terminal_transition": False}
    if call.job.cancel_requested_at is not None:
        with transaction.atomic():
            locked = ModelCall.objects.select_for_update().get(pk=call.pk)
            transitioned = _terminal_call_locked(
                locked,
                status=ModelCall.Status.CANCELLED,
                stable_error_code="GEO_DETECTION_USER_CANCELLED_BEFORE_START",
            )
        return {"status": locked.status, "terminal_transition": transitioned}
    queue_deadline = call.queued_at + timedelta(
        seconds=settings.GEO_DETECTION_QUEUE_TIMEOUT_SECONDS
    )
    if call.attempt_count == 0 and now >= queue_deadline:
        with transaction.atomic():
            locked = ModelCall.objects.select_for_update().get(pk=call.pk)
            transitioned = _terminal_call_locked(
                locked,
                status=ModelCall.Status.FAILED,
                stable_error_code="GEO_DETECTION_QUEUE_TIMEOUT",
            )
        return {"status": locked.status, "terminal_transition": transitioned}
    if not _live_model_available(call):
        with transaction.atomic():
            locked = ModelCall.objects.select_for_update().get(pk=call.pk)
            transitioned = _terminal_call_locked(
                locked,
                status=ModelCall.Status.FAILED,
                stable_error_code="GEO_DETECTION_MODEL_PAUSED_OR_DISABLED",
            )
        return {"status": locked.status, "terminal_transition": transitioned}

    runtime = call.model_run.runtime_snapshot
    store = semaphore_store or DetectionSemaphoreStore()
    try:
        lease = store.acquire(
            model_key=call.model_key,
            global_limit=settings.GEO_DETECTION_GLOBAL_MAX_CONCURRENCY,
            model_limit=int(runtime["max_concurrency"]),
            lease_seconds=int(runtime["timeout_seconds"]) + 60,
        )
    except DetectionSemaphoreUnavailable:
        return {
            "status": "queued",
            "reason": "semaphore_unavailable",
            "terminal_transition": False,
        }
    if lease is None:
        return {
            "status": "queued",
            "reason": "concurrency_limit",
            "terminal_transition": False,
        }

    generation = uuid.uuid4()
    attempt_no = 0
    try:
        with transaction.atomic():
            locked = (
                ModelCall.objects.select_for_update(of=("self",))
                .select_related("job__snapshot", "question_snapshot", "model_run", "model")
                .get(pk=call.pk)
            )
            if locked.status not in (ModelCall.Status.QUEUED, ModelCall.Status.RETRY_WAIT):
                return {"status": locked.status, "terminal_transition": False}
            if locked.job.cancel_requested_at is not None:
                transitioned = _terminal_call_locked(
                    locked,
                    status=ModelCall.Status.CANCELLED,
                    stable_error_code="GEO_DETECTION_CANCELLED_BEFORE_PROVIDER_START",
                )
                return {"status": locked.status, "terminal_transition": transitioned}
            if not _live_model_available(locked):
                transitioned = _terminal_call_locked(
                    locked,
                    status=ModelCall.Status.FAILED,
                    stable_error_code="GEO_DETECTION_MODEL_PAUSED_OR_DISABLED",
                )
                return {"status": locked.status, "terminal_transition": transitioned}
            locked.attempt_count += 1
            attempt_no = locked.attempt_count
            locked.status = ModelCall.Status.RUNNING
            locked.generation = generation
            locked.started_at = locked.started_at or timezone.now()
            locked.next_attempt_at = None
            locked.save(
                update_fields=(
                    "attempt_count",
                    "status",
                    "generation",
                    "started_at",
                    "next_attempt_at",
                    "updated_at",
                )
            )
            job = GeoDetectionJob.objects.select_for_update().get(pk=locked.job_id)
            if job.started_at is None:
                job.started_at = timezone.now()
                job.status = GeoDetectionJob.Status.RUNNING
                job.version += 1
                job.save(update_fields=("started_at", "status", "version", "updated_at"))
            model_run = GeoDetectionModelRun.objects.select_for_update().get(pk=locked.model_run_id)
            if model_run.status == GeoDetectionModelRun.Status.QUEUED:
                model_run.status = GeoDetectionModelRun.Status.RUNNING
                model_run.save(update_fields=("status", "updated_at"))
            ModelCallAttempt.objects.create(
                model_call=locked,
                attempt_no=attempt_no,
                status=ModelCallAttempt.Status.RUNNING,
                started_at=timezone.now(),
            )
            call = locked

        try:
            adapter, request = _adapter_request(call, generation=generation)
            response = adapter.invoke(request)
        except AIAdapterError as exc:
            with transaction.atomic():
                locked = (
                    ModelCall.objects.select_for_update(of=("self",))
                    .select_related("model_run")
                    .get(pk=call.pk)
                )
                if locked.status != ModelCall.Status.RUNNING or locked.generation != generation:
                    return {"status": locked.status, "terminal_transition": False}
                attempt = ModelCallAttempt.objects.select_for_update().get(
                    model_call=locked, attempt_no=attempt_no
                )
                attempt.status = ModelCallAttempt.Status.FAILED
                attempt.error_category = exc.category.value
                attempt.stable_error_code = exc.stable_code
                attempt.retryable = exc.retryable
                attempt.finished_at = timezone.now()
                attempt.save(
                    update_fields=(
                        "status",
                        "error_category",
                        "stable_error_code",
                        "retryable",
                        "finished_at",
                    )
                )
                max_retries = int(locked.model_run.runtime_snapshot["max_retries"])
                should_retry = (
                    exc.retryable
                    and locked.attempt_count <= max_retries
                    and locked.job.cancel_requested_at is None
                    and _live_model_available(locked)
                )
                if should_retry:
                    locked.status = ModelCall.Status.RETRY_WAIT
                    locked.generation = None
                    locked.stable_error_code = exc.stable_code
                    locked.safe_error_summary = {"category": exc.category.value}
                    locked.next_attempt_at = timezone.now() + timedelta(
                        seconds=_backoff_seconds(
                            locked.model_run.runtime_snapshot, locked.attempt_count
                        )
                    )
                    locked.save(
                        update_fields=(
                            "status",
                            "generation",
                            "stable_error_code",
                            "safe_error_summary",
                            "next_attempt_at",
                            "updated_at",
                        )
                    )
                    return {"status": "retry_wait", "terminal_transition": False}
                transitioned = _terminal_call_locked(
                    locked,
                    status=ModelCall.Status.FAILED,
                    stable_error_code=exc.stable_code,
                    safe_error_summary={"category": exc.category.value},
                )
                return {"status": locked.status, "terminal_transition": transitioned}
        except Exception:
            with transaction.atomic():
                locked = ModelCall.objects.select_for_update().get(pk=call.pk)
                if locked.status != ModelCall.Status.RUNNING or locked.generation != generation:
                    return {"status": locked.status, "terminal_transition": False}
                attempt = ModelCallAttempt.objects.select_for_update().get(
                    model_call=locked, attempt_no=attempt_no
                )
                attempt.status = ModelCallAttempt.Status.FAILED
                attempt.error_category = AIAdapterErrorCategory.INTERNAL_ADAPTER.value
                attempt.stable_error_code = "GEO_DETECTION_ADAPTER_INTERNAL"
                attempt.retryable = False
                attempt.finished_at = timezone.now()
                attempt.save(
                    update_fields=(
                        "status",
                        "error_category",
                        "stable_error_code",
                        "retryable",
                        "finished_at",
                    )
                )
                transitioned = _terminal_call_locked(
                    locked,
                    status=ModelCall.Status.FAILED,
                    stable_error_code="GEO_DETECTION_ADAPTER_INTERNAL",
                    safe_error_summary={"category": AIAdapterErrorCategory.INTERNAL_ADAPTER.value},
                )
                return {"status": locked.status, "terminal_transition": transitioned}

        normalized_citations = normalize_detection_citations(response.output)

        with transaction.atomic():
            locked = (
                ModelCall.objects.select_for_update().select_related("model_run").get(pk=call.pk)
            )
            if locked.status != ModelCall.Status.RUNNING or locked.generation != generation:
                return {"status": locked.status, "terminal_transition": False}
            attempt = ModelCallAttempt.objects.select_for_update().get(
                model_call=locked, attempt_no=attempt_no
            )
            attempt.status = ModelCallAttempt.Status.SUCCEEDED
            attempt.provider_request_id = response.provider_request_id or ""
            attempt.input_tokens = response.usage.input_tokens
            attempt.output_tokens = response.usage.output_tokens
            attempt.total_tokens = response.usage.total_tokens
            attempt.latency_ms = response.timing.latency_ms
            attempt.finish_reason = response.finish_reason.value
            attempt.provider_metadata = copy.deepcopy(dict(response.sanitized_provider_metadata))
            attempt.finished_at = timezone.now()
            attempt.save()
            raw_text = response.output.raw_text
            stored_response, response_created = ModelResponse.objects.get_or_create(
                model_call=locked,
                defaults={
                    "provider_model_id": response.output.provider_model_id,
                    "raw_text": raw_text,
                    "raw_text_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                    "provider_metadata": copy.deepcopy(dict(response.sanitized_provider_metadata)),
                },
            )
            if response_created:
                persist_response_citations(
                    model_response=stored_response,
                    citations=normalized_citations,
                )
                score_programmatic_response(model_response=stored_response)
            cost, currency = _estimated_cost(locked.model_run.runtime_snapshot, response)
            locked.web_search_used = response.output.web_search_used
            locked.degraded = response.output.degraded
            locked.finish_reason = response.finish_reason.value
            locked.provider_request_id = response.provider_request_id or ""
            locked.input_tokens = response.usage.input_tokens
            locked.output_tokens = response.usage.output_tokens
            locked.total_tokens = response.usage.total_tokens
            locked.latency_ms = response.timing.latency_ms
            locked.estimated_cost = cost
            locked.cost_currency = currency if cost is not None else ""
            locked.save(
                update_fields=(
                    "web_search_used",
                    "degraded",
                    "finish_reason",
                    "provider_request_id",
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "latency_ms",
                    "estimated_cost",
                    "cost_currency",
                    "updated_at",
                )
            )
            transitioned = _terminal_call_locked(locked, status=ModelCall.Status.SUCCEEDED)
            return {"status": locked.status, "terminal_transition": transitioned}
    finally:
        try:
            store.release(lease)
        except DetectionSemaphoreUnavailable:
            pass


def due_model_call_ids(limit: int = 100) -> list:
    now = timezone.now()
    query = ModelCall.objects.filter(
        Q(status=ModelCall.Status.QUEUED)
        | Q(status=ModelCall.Status.RETRY_WAIT, next_attempt_at__lte=now)
    ).filter(job__cancel_requested_at__isnull=True)
    return list(
        query.order_by("-job__queue_priority", "queued_at", "id").values_list("id", flat=True)[
            :limit
        ]
    )


@transaction.atomic
def expire_queue_timeouts() -> int:
    cutoff = timezone.now() - timedelta(seconds=settings.GEO_DETECTION_QUEUE_TIMEOUT_SECONDS)
    ids = list(
        ModelCall.objects.select_for_update()
        .filter(
            status=ModelCall.Status.QUEUED,
            attempt_count=0,
            queued_at__lte=cutoff,
        )
        .values_list("id", flat=True)[:500]
    )
    for call_id in ids:
        call = ModelCall.objects.select_for_update().get(pk=call_id)
        _terminal_call_locked(
            call,
            status=ModelCall.Status.FAILED,
            stable_error_code="GEO_DETECTION_QUEUE_TIMEOUT",
        )
    return len(ids)


@transaction.atomic
def expire_stale_running_calls() -> int:
    now = timezone.now()
    ids = list(
        ModelCall.objects.select_for_update()
        .filter(status=ModelCall.Status.RUNNING, started_at__isnull=False)
        .values_list("id", flat=True)[:500]
    )
    expired = 0
    for call_id in ids:
        call = ModelCall.objects.select_for_update().select_related("model_run").get(pk=call_id)
        timeout_seconds = int(call.model_run.runtime_snapshot["timeout_seconds"]) + 90
        attempt = ModelCallAttempt.objects.filter(
            model_call=call,
            attempt_no=call.attempt_count,
            status=ModelCallAttempt.Status.RUNNING,
        ).first()
        if attempt is None or attempt.started_at > now - timedelta(seconds=timeout_seconds):
            continue
        attempt.status = ModelCallAttempt.Status.FAILED
        attempt.stable_error_code = "GEO_DETECTION_WORKER_STALE"
        attempt.retryable = False
        attempt.finished_at = now
        attempt.save(
            update_fields=(
                "status",
                "stable_error_code",
                "retryable",
                "finished_at",
            )
        )
        _terminal_call_locked(
            call,
            status=ModelCall.Status.FAILED,
            stable_error_code="GEO_DETECTION_WORKER_STALE",
        )
        expired += 1
    return expired


@transaction.atomic
def fail_internal_model_call(*, call_id) -> dict:
    try:
        call = ModelCall.objects.select_for_update().get(pk=call_id)
    except ModelCall.DoesNotExist:
        return {"status": "missing", "terminal_transition": False}
    if call.status in TERMINAL_CALL_STATUSES:
        return {"status": call.status, "terminal_transition": False}
    if call.status == ModelCall.Status.RUNNING:
        attempt = ModelCallAttempt.objects.filter(
            model_call=call,
            attempt_no=call.attempt_count,
            status=ModelCallAttempt.Status.RUNNING,
        ).first()
        if attempt is not None:
            attempt.status = ModelCallAttempt.Status.FAILED
            attempt.error_category = AIAdapterErrorCategory.INTERNAL_ADAPTER.value
            attempt.stable_error_code = "GEO_DETECTION_WORKER_INTERNAL"
            attempt.retryable = False
            attempt.finished_at = timezone.now()
            attempt.save(
                update_fields=(
                    "status",
                    "error_category",
                    "stable_error_code",
                    "retryable",
                    "finished_at",
                )
            )
    transitioned = _terminal_call_locked(
        call,
        status=ModelCall.Status.FAILED,
        stable_error_code="GEO_DETECTION_WORKER_INTERNAL",
    )
    return {"status": call.status, "terminal_transition": transitioned}
