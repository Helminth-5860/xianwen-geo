from __future__ import annotations

import copy
import uuid
from dataclasses import asdict

from django.db import transaction
from django.utils import timezone

from apps.ai.contracts import AIModelCapability
from apps.ai.models import AIModel, AIModelRuntimeConfig
from apps.ai.registry import model_registry
from apps.quotas.services import freeze_quota

from .exceptions import (
    GeoDetectionConcurrencyLimit,
    GeoDetectionInputConflict,
    GeoDetectionProviderUnavailable,
    GeoDetectionValuesInvalid,
)
from .idempotency import canonical_digest, derive_detection_idempotency
from .models import (
    DetectionRetest,
    GeoDetectionJob,
    GeoDetectionModelRun,
    GeoDetectionQuestionSnapshot,
    GeoDetectionSnapshot,
    GeoReport,
    ModelCall,
)
from .services import (
    ACTIVE_JOB_STATUSES,
    GEO_PROMPT_VERSION,
    GEO_SCORING_RULE_VERSION,
    GEO_SYSTEM_PROMPT,
    User,
    _credential_configured,
    _detection_account,
    _effective_subscription,
    _int_limit,
    _limits,
    _model_permissions,
    create_detection_job,
    get_runtime_snapshot,
    subject_for_user_or_404,
)


class QuickRetestBlocked(GeoDetectionProviderUnavailable):
    def __init__(self, *, model_key: str, reason: str):
        self.model_key = model_key
        self.reason = reason
        super().__init__(f"{model_key}: {reason}")


def _preflight_models(*, subscription, baseline: GeoReport) -> tuple[list, list[dict]]:
    baseline_models = baseline.provenance["models"]
    model_ids = [row["model_id"] for row in baseline_models]
    try:
        permissions = {row["model_key"] for row in _model_permissions(subscription)}
    except GeoDetectionInputConflict:
        if subscription.entitlement_snapshot.get("model_permissions") == []:
            permissions = set()
        else:
            raise
    models = list(
        AIModel.objects.select_related("provider", "runtime_config")
        .filter(pk__in=model_ids)
        .order_by("canonical_order", "id")
    )
    by_id = {str(row.pk): row for row in models}
    ordered = []
    runtimes = []
    for frozen in baseline_models:
        model_key = frozen["model_key"]
        model = by_id.get(frozen["model_id"])
        if model is None or model.model_key != model_key:
            raise QuickRetestBlocked(model_key=model_key, reason="model_missing")
        if model_key not in permissions:
            raise QuickRetestBlocked(model_key=model_key, reason="model_not_entitled")
        try:
            config = AIModelRuntimeConfig.objects.get(model=model)
        except AIModelRuntimeConfig.DoesNotExist as exc:
            raise QuickRetestBlocked(model_key=model_key, reason="runtime_missing") from exc
        if not config.enabled:
            raise QuickRetestBlocked(model_key=model_key, reason="model_disabled")
        if config.paused:
            raise QuickRetestBlocked(model_key=model_key, reason="model_paused")
        try:
            runtime = get_runtime_snapshot(model_key=model_key, require_available=True)
        except Exception as exc:
            raise QuickRetestBlocked(model_key=model_key, reason="runtime_unavailable") from exc
        if not runtime.provider_model_id:
            raise QuickRetestBlocked(model_key=model_key, reason="runtime_missing")
        if not _credential_configured(model.provider_id):
            raise QuickRetestBlocked(model_key=model_key, reason="credential_unavailable")
        try:
            adapter = model_registry.resolve(
                provider_key=runtime.provider_key,
                model_key=runtime.model_key,
                capability=AIModelCapability.GEO_DETECTION,
            )
        except Exception as exc:
            raise QuickRetestBlocked(model_key=model_key, reason="adapter_unavailable") from exc
        ordered.append(model)
        runtimes.append(
            {
                **asdict(runtime),
                "input_cost": str(runtime.input_cost) if runtime.input_cost is not None else None,
                "output_cost": (
                    str(runtime.output_cost) if runtime.output_cost is not None else None
                ),
                "request_cost": (
                    str(runtime.request_cost) if runtime.request_cost is not None else None
                ),
                "adapter_version": adapter.descriptor.adapter_version,
                "prompt_version": adapter.descriptor.prompt_version,
            }
        )
    return ordered, runtimes


@transaction.atomic
def create_quick_retest(
    *, user_id, baseline_report_id, idempotency_key: str, request_id
) -> tuple[GeoDetectionJob, bool]:
    user = User.objects.select_for_update().get(pk=user_id)
    try:
        baseline = GeoReport.objects.select_related("job__snapshot", "subject").get(
            pk=baseline_report_id, user=user
        )
    except GeoReport.DoesNotExist as exc:
        raise GeoDetectionInputConflict from exc
    if not user.is_active or user.account_status != user.AccountStatus.ACTIVE:
        raise GeoDetectionInputConflict
    try:
        idem = derive_detection_idempotency(
            user_id=user.pk, subject_id=baseline.subject_id, raw_key=idempotency_key
        )
    except ValueError as exc:
        raise GeoDetectionValuesInvalid from exc
    request_digest = canonical_digest(
        {"baseline_report_id": str(baseline.pk), "mode": "quick_retest"}
    )
    replay = GeoDetectionJob.objects.filter(idempotency_key_digest=idem).first()
    if replay is not None:
        if replay.user_id != user.pk or replay.request_digest != request_digest:
            raise GeoDetectionInputConflict
        return replay, False
    subject = subject_for_user_or_404(user=user, subject_id=baseline.subject_id, lock=True)
    if subject.status != "active" or subject.current_version_id is None:
        raise GeoDetectionInputConflict
    subscription = _effective_subscription(user=user, lock=True)
    limits = _limits(subscription)
    frozen_questions = list(
        baseline.job.snapshot.questions.select_related("source_question").order_by(
            "sort_order", "id"
        )
    )
    if not frozen_questions or len(frozen_questions) > _int_limit(
        limits, "max_questions_per_detection"
    ):
        raise GeoDetectionValuesInvalid
    models, runtimes = _preflight_models(subscription=subscription, baseline=baseline)
    if len(models) > _int_limit(limits, "max_models_per_detection"):
        raise QuickRetestBlocked(model_key="", reason="model_limit_reduced")
    # The current subject version is the new execution identity. The derivation artifacts and
    # questions remain historical baseline provenance and do not depend on mutable current-bank
    # membership.
    keyword_version = baseline.job.snapshot.keyword_set_version
    distillation = baseline.job.snapshot.distillation_set
    required = len(frozen_questions) * len(models)
    active_count = (
        GeoDetectionJob.objects.select_for_update()
        .filter(user=user, status__in=ACTIVE_JOB_STATUSES)
        .count()
    )
    if active_count >= _int_limit(limits, "concurrent_detection_jobs"):
        raise GeoDetectionConcurrencyLimit
    job_id = uuid.uuid4()
    hold = freeze_quota(
        account_id=_detection_account(subscription).pk,
        amount=required,
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
        planned_question_count=len(frozen_questions),
        planned_model_count=len(models),
        planned_detection_points=required,
        queue_priority=subscription.plan_version.queue_priority,
        idempotency_key_digest=idem,
        request_digest=request_digest,
        request_id=request_id,
        queued_at=queued_at,
    )
    model_snapshots = [
        {
            "model_id": str(model.pk),
            "model_key": model.model_key,
            "provider_key": model.provider.provider_key,
            **copy.deepcopy(runtime),
        }
        for model, runtime in zip(models, runtimes, strict=True)
    ]
    snapshot = GeoDetectionSnapshot.objects.create(
        job=job,
        subject_version_id=subject.current_version_id,
        keyword_set_version=keyword_version,
        distillation_set=distillation,
        question_bank_version=baseline.job.snapshot.question_bank_version,
        entitlement_snapshot=copy.deepcopy(subscription.entitlement_snapshot),
        model_snapshots=model_snapshots,
        system_prompt=GEO_SYSTEM_PROMPT,
        prompt_version=GEO_PROMPT_VERSION,
        scoring_rule_version=GEO_SCORING_RULE_VERSION,
        input_digest=canonical_digest(
            {
                "baseline_report_id": str(baseline.pk),
                "subject_version_id": str(subject.current_version_id),
                "questions": baseline.provenance["questions"],
                "models": baseline.provenance["models"],
                "scoring_rule_version": GEO_SCORING_RULE_VERSION,
            }
        ),
    )
    copied_questions = [
        GeoDetectionQuestionSnapshot.objects.create(
            snapshot=snapshot,
            source_question=row.source_question,
            text=row.text,
            primary_category_key=row.primary_category_key,
            primary_category_name=row.primary_category_name,
            primary_category_version=row.primary_category_version,
            priority=row.priority,
            question_type=row.question_type,
            participates_in_scoring=row.participates_in_scoring,
            sort_order=row.sort_order,
        )
        for row in frozen_questions
    ]
    for model, runtime in zip(models, runtimes, strict=True):
        run = GeoDetectionModelRun.objects.create(
            job=job,
            model=model,
            provider_key=model.provider.provider_key,
            model_key=model.model_key,
            provider_model_id=runtime["provider_model_id"],
            runtime_snapshot=copy.deepcopy(runtime),
            adapter_version=runtime["adapter_version"],
            prompt_version=runtime["prompt_version"],
            planned_calls=len(copied_questions),
        )
        ModelCall.objects.bulk_create(
            [
                ModelCall(
                    job=job,
                    model_run=run,
                    question_snapshot=question,
                    model=model,
                    provider_key=model.provider.provider_key,
                    model_key=model.model_key,
                    provider_model_id=runtime["provider_model_id"],
                    web_search_requested=bool(runtime["network_access_enabled"]),
                    queued_at=queued_at,
                )
                for question in copied_questions
            ]
        )
    DetectionRetest.objects.create(job=job, baseline_report=baseline, mode="quick")
    return job, True


@transaction.atomic
def create_adjusted_retest(
    *,
    user_id,
    baseline_report_id,
    question_ids,
    model_ids,
    idempotency_key,
    request_id,
) -> tuple[GeoDetectionJob, bool]:
    try:
        baseline = GeoReport.objects.get(pk=baseline_report_id, user_id=user_id)
    except GeoReport.DoesNotExist as exc:
        raise GeoDetectionInputConflict from exc
    job, created = create_detection_job(
        user_id=user_id,
        subject_id=baseline.subject_id,
        question_ids=question_ids,
        model_ids=model_ids,
        mode="new",
        idempotency_key=f"adjusted-retest:{baseline.pk}:{idempotency_key}",
        request_id=request_id,
    )
    if created:
        DetectionRetest.objects.create(job=job, baseline_report=baseline, mode="adjusted")
    return job, created
