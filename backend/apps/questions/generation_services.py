import copy
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from apps.ai.sanitization import sanitize_provider_metrics
from apps.keywords.models import (
    DistillationSet,
    DistillationWorkspace,
    Keyword,
    KeywordAssetPreference,
)
from apps.keywords.services import _assert_user_write_allowed, _lock_effective_subscription
from apps.plans.subscription_services import effective_entitlement_snapshot
from apps.quotas.models import QuotaAccount
from apps.quotas.services import (
    available_quota,
    consume_hold,
    freeze_quota,
    quota_account_for_subscription,
    release_hold,
)
from apps.subjects.risk_services import capabilities_for_subject
from apps.subjects.subject_services import subject_for_user_or_404

from .bank_models import (
    Question,
    QuestionBankVersion,
    QuestionBankWorkspace,
    QuestionDraftItem,
    QuestionGenerationEvent,
    QuestionGenerationJob,
    QuestionGenerationResult,
    QuestionKeywordLink,
    QuestionTagLink,
)
from .generation_contracts import (
    QuestionCatalogInput,
    QuestionGenerationRequest,
    QuestionKeywordInput,
)
from .generation_exceptions import (
    QuestionBankError,
    QuestionBankInputConflict,
    QuestionBankValuesInvalid,
    QuestionBankVersionConflict,
    QuestionBankVersionNoChanges,
    QuestionGenerationIdempotencyConflict,
    QuestionGenerationInProgress,
    QuestionGenerationInvalidResponse,
    QuestionGenerationProviderError,
    QuestionGenerationRegenerationConfirmationRequired,
    QuestionGenerationUnexpectedError,
)
from .generation_idempotency import (
    canonical_digest,
    derive_question_generation_idempotency,
)
from .generation_providers import (
    get_question_generation_provider,
    require_available_question_generation_provider,
)
from .generation_validation import (
    NormalizedQuestion,
    validate_draft_items,
    validate_generated_questions,
)
from .models import QuestionCategory, QuestionTag

User = get_user_model()
TERMINAL = {"succeeded", "failed", "conflict", "superseded"}


def _safe_event(job, event_type, *, code="", summary=None):
    return QuestionGenerationEvent.objects.create(
        job=job,
        event_type=event_type,
        stable_error_code=code,
        safe_summary=copy.deepcopy(summary or {}),
        request_id=job.request_id,
        correlation_id=job.correlation_id,
    )


def _subject_values(subject, subject_version):
    values = copy.deepcopy(subject_version.field_values)
    values["official_name"] = subject_version.official_name
    profile = getattr(subject, "business_profile", None)
    if profile is not None:
        values["brand_name"] = profile.brand_name
        values["subject_aliases"] = profile.subject_aliases
    return values


def _applicable(rows, subject_type_id):
    return (
        rows.filter(status="active")
        .filter(
            Q(subject_type_links__isnull=True)
            | Q(subject_type_links__subject_type_id=subject_type_id)
        )
        .distinct()
    )


def _catalog_snapshots(subject):
    categories = [
        {
            "id": str(row.pk),
            "key": row.key,
            "name": row.name,
            "version": row.version,
            "guidance": row.generation_guidance,
        }
        for row in _applicable(QuestionCategory.objects, subject.subject_type_id).order_by(
            "sort_order", "key", "id"
        )
    ]
    tags = [
        {"id": str(row.pk), "key": row.key, "name": row.name, "version": row.version}
        for row in _applicable(QuestionTag.objects, subject.subject_type_id).order_by(
            "sort_order", "key", "id"
        )
    ]
    if not categories:
        raise QuestionBankValuesInvalid
    return categories, tags


def _effective_keywords(distillation_set):
    keyword_by_id: dict[uuid.UUID, Keyword] = {}
    rows = distillation_set.items.select_related("source_keyword", "canonical_keyword").order_by(
        "sort_order", "id"
    )
    for row in rows:
        keyword = None
        if row.action == "keep":
            keyword = row.source_keyword
        elif row.action == "merge":
            keyword = row.canonical_keyword
        if keyword is not None:
            keyword_by_id.setdefault(keyword.pk, keyword)
    preferences = {
        row.source_keyword_id: row
        for row in KeywordAssetPreference.objects.filter(
            user=distillation_set.user,
            subject=distillation_set.subject,
            source_keyword_id__in=keyword_by_id,
        )
    }
    excluded = {
        keyword_id
        for keyword_id, preference in preferences.items()
        if not preference.enabled
        or not preference.usable_for_questions
        or preference.deleted_at is not None
    }

    def effective_region_text(keyword, preference):
        if preference is None or preference.region_selections is None:
            return keyword.region_text
        labels = []
        for region in preference.region_selections:
            path = region.get("path") if isinstance(region, dict) else None
            names = [node.get("name") for node in path or [] if isinstance(node, dict)]
            if isinstance(region, dict) and region.get("name"):
                if not names or names[-1] != region["name"]:
                    names.append(region["name"])
            label = " / ".join(str(name) for name in names if name)
            if label and label not in labels:
                labels.append(label)
        return "；".join(labels) or None

    return [
        {
            "id": str(row.pk),
            "text": (
                preferences[row.pk].display_text
                if row.pk in preferences and preferences[row.pk].display_text
                else row.text
            ),
            "region_text": effective_region_text(row, preferences.get(row.pk)),
            "search_intent": row.search_intent,
            "business_category": (
                preferences[row.pk].business_category
                if row.pk in preferences and preferences[row.pk].business_category
                else row.business_category
            ),
            "search_intents": (
                preferences[row.pk].search_intents
                if row.pk in preferences and preferences[row.pk].search_intents is not None
                else row.search_intents
            ),
        }
        for row in keyword_by_id.values()
        if row.pk not in excluded
    ]


def _request_payload(*, subject_id, distillation_set_id, expected_workspace_version, regenerate):
    return {
        "subject_id": str(subject_id),
        "distillation_set_id": str(distillation_set_id),
        "expected_workspace_version": expected_workspace_version,
        "regenerate": regenerate,
    }


@transaction.atomic
def create_question_generation_job(
    *,
    user_id,
    subject_id,
    distillation_set_id,
    expected_workspace_version,
    regenerate,
    idempotency_key,
    request_id,
):
    if type(expected_workspace_version) is not int or expected_workspace_version < 0:
        raise QuestionBankVersionConflict
    if type(regenerate) is not bool:
        raise QuestionBankValuesInvalid
    try:
        idem = derive_question_generation_idempotency(
            user_id=user_id, subject_id=subject_id, raw_key=idempotency_key
        )
    except ValueError as exc:
        raise QuestionBankValuesInvalid from exc
    request_digest = canonical_digest(
        _request_payload(
            subject_id=subject_id,
            distillation_set_id=distillation_set_id,
            expected_workspace_version=expected_workspace_version,
            regenerate=regenerate,
        )
    )
    user = User.objects.select_for_update().get(pk=user_id)
    replay = QuestionGenerationJob.objects.filter(idempotency_key_digest=idem).first()
    if replay is not None:
        if (
            replay.user_id != user.pk
            or str(replay.subject_id) != str(subject_id)
            or replay.request_digest != request_digest
        ):
            raise QuestionGenerationIdempotencyConflict
        return replay, False

    _assert_user_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.status != subject.Status.ACTIVE or subject.current_version_id is None:
        raise QuestionBankInputConflict
    capabilities_for_subject(subject)
    subscription = _lock_effective_subscription(user)
    try:
        distillation_set = (
            DistillationSet.objects.select_related(
                "workspace", "subject_version", "input_keyword_set_version"
            )
            .prefetch_related("items__source_keyword", "items__canonical_keyword")
            .get(pk=distillation_set_id, subject=subject)
        )
    except DistillationSet.DoesNotExist as exc:
        raise QuestionBankInputConflict from exc
    try:
        distillation_workspace = DistillationWorkspace.objects.select_for_update().get(
            subject=subject
        )
    except DistillationWorkspace.DoesNotExist as exc:
        raise QuestionBankInputConflict from exc
    if (
        distillation_workspace.current_set_id != distillation_set.pk
        or distillation_set.subject_version_id != subject.current_version_id
    ):
        raise QuestionBankInputConflict
    if QuestionGenerationJob.objects.filter(
        subject=subject, status__in=("queued", "running", "retry_wait")
    ).exists():
        raise QuestionGenerationInProgress
    workspace = QuestionBankWorkspace.objects.select_for_update().filter(subject=subject).first()
    actual_version = workspace.version if workspace else 0
    if actual_version != expected_workspace_version:
        raise QuestionBankVersionConflict
    provider = require_available_question_generation_provider()
    available_items = available_quota(
        subscription=subscription,
        quota_type="question_generated_items",
    )
    caps = [100, available_items]
    historical_limit = (subscription.entitlement_snapshot.get("limits") or {}).get(
        "question_bank_limit"
    )
    if type(historical_limit) is int and historical_limit > 0:
        caps.append(historical_limit)
    question_limit = min(caps)
    if question_limit < 1:
        raise QuestionBankValuesInvalid
    prior_success = QuestionGenerationJob.objects.filter(
        subject=subject, status="succeeded"
    ).exists()
    if prior_success and not regenerate:
        raise QuestionGenerationRegenerationConfirmationRequired
    # Preserve the existing immutable evidence shape while charging by the
    # number of novel questions that are actually stored.
    billing_mode = "regeneration"
    subject_values = _subject_values(subject, distillation_set.subject_version)
    keywords = _effective_keywords(distillation_set)
    if not keywords:
        raise QuestionBankValuesInvalid
    categories, tags = _catalog_snapshots(subject)
    job_id = uuid.uuid4()
    account = quota_account_for_subscription(
        subscription=subscription,
        quota_type="question_generated_items",
    )
    quota_hold = freeze_quota(
        account_id=account.pk,
        amount=question_limit,
        business_type="question_bank_generation",
        business_id=job_id,
        idempotency_key=f"question-generation-freeze-{job_id}",
        request_id=request_id,
    )
    input_digest = canonical_digest(
        {
            "subject_version_id": str(subject.current_version_id),
            "subject_values": subject_values,
            "distillation_set_id": str(distillation_set.pk),
            "keywords": keywords,
            "categories": categories,
            "tags": tags,
            "question_limit": question_limit,
        }
    )
    try:
        job = QuestionGenerationJob.objects.create(
            id=job_id,
            user=user,
            subject=subject,
            subject_version=distillation_set.subject_version,
            input_distillation_set=distillation_set,
            subscription=subscription,
            quota_hold=quota_hold,
            billing_mode=billing_mode,
            expected_workspace_version=expected_workspace_version,
            question_limit=question_limit,
            input_subject_values=subject_values,
            input_keywords=keywords,
            input_categories=categories,
            input_tags=tags,
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
        raise QuestionGenerationInProgress from exc
    return job, True


def _request_for_job(job):
    def catalog(snapshot):
        return tuple(
            QuestionCatalogInput(
                id=row["id"],
                key=row["key"],
                name=row["name"],
                version=row["version"],
                guidance=row.get("guidance", ""),
            )
            for row in snapshot
        )

    return QuestionGenerationRequest(
        job_id=str(job.pk),
        subject_id=str(job.subject_id),
        subject_version_id=str(job.subject_version_id),
        distillation_set_id=str(job.input_distillation_set_id),
        subject_values=copy.deepcopy(job.input_subject_values),
        keywords=tuple(QuestionKeywordInput(**row) for row in job.input_keywords),
        categories=catalog(job.input_categories),
        tags=catalog(job.input_tags),
        question_limit=job.question_limit,
    )


def question_generation_job_for_user_or_404(*, user, job_id):
    try:
        return QuestionGenerationJob.objects.select_related(
            "subject", "subject_version", "input_distillation_set", "quota_hold"
        ).get(pk=job_id, user=user)
    except QuestionGenerationJob.DoesNotExist as exc:
        raise Http404 from exc


def claim_question_generation_job(*, job_id, expected_generation=None):
    now = timezone.now()
    with transaction.atomic():
        job = QuestionGenerationJob.objects.select_for_update().get(pk=job_id)
        if job.status in TERMINAL:
            return None
        if expected_generation is not None:
            if job.status == "running" and str(job.generation) == str(expected_generation):
                return job.pk, job.generation
            return None
        if (
            job.status == "running"
            and job.started_at
            and job.started_at
            > now - timedelta(seconds=settings.QUESTION_GENERATION_RUNNING_STALE_SECONDS)
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
        _safe_event(job, "started", summary={"attempt": job.attempts})
        return job.pk, job.generation


def _settle_quota(job, action, amount=None):
    if job.quota_hold_id is None:
        return
    (consume_hold if action == "consume" else release_hold)(
        hold_id=job.quota_hold_id,
        amount=job.question_limit if amount is None else amount,
        idempotency_key=f"question-generation-{action}-{job.pk}",
        request_id=job.request_id,
    )


def _terminal_locked(job, *, status, code):
    if job.status in TERMINAL:
        return {"status": job.status}
    _settle_quota(job, "release")
    job.status = status
    job.finished_at = timezone.now()
    job.next_attempt_at = None
    job.stable_error_code = code
    job.version += 1
    job.save(
        update_fields=(
            "status",
            "finished_at",
            "next_attempt_at",
            "stable_error_code",
            "version",
            "updated_at",
        )
    )
    _safe_event(job, status, code=code)
    return {"status": status, "code": code}


def _schedule_retry(job_id, generation, code):
    with transaction.atomic():
        job = QuestionGenerationJob.objects.select_for_update().get(pk=job_id)
        if job.status != "running" or job.generation != generation:
            return {"status": job.status}
        if job.attempts >= settings.QUESTION_GENERATION_MAX_PROVIDER_ATTEMPTS:
            return _terminal_locked(job, status="failed", code=code)
        job.status = "retry_wait"
        job.retry_count += 1
        job.next_attempt_at = timezone.now() + timedelta(
            seconds=min(
                900,
                settings.QUESTION_GENERATION_RETRY_BASE_SECONDS * 2 ** min(job.retry_count - 1, 5),
            )
        )
        job.stable_error_code = code
        job.version += 1
        job.save(
            update_fields=(
                "status",
                "retry_count",
                "next_attempt_at",
                "stable_error_code",
                "version",
                "updated_at",
            )
        )
        _safe_event(job, "retry_scheduled", code=code, summary={"retry_count": job.retry_count})
        return {"status": "retry_wait", "code": code}


def _safe_provider_metrics(metrics):
    return sanitize_provider_metrics(metrics)


def _replace_draft(workspace, normalized):
    QuestionDraftItem.objects.filter(workspace=workspace).delete()
    QuestionDraftItem.objects.bulk_create(
        [
            QuestionDraftItem(
                workspace=workspace,
                text=item.text,
                matching_text=item.matching_text,
                primary_category_id=item.primary_category_id,
                priority=item.priority,
                question_type=item.question_type,
                participates_in_scoring=item.participates_in_scoring,
                ai_reason=item.reason,
                tag_ids=[str(value) for value in item.tag_ids],
                keyword_ids=[str(value) for value in item.keyword_ids],
                sort_order=index,
            )
            for index, item in enumerate(normalized)
        ]
    )


def _input_is_current(job, subject):
    try:
        workspace = DistillationWorkspace.objects.select_for_update().get(subject=subject)
    except DistillationWorkspace.DoesNotExist:
        return False
    return (
        subject.current_version_id == job.subject_version_id
        and workspace.current_set_id == job.input_distillation_set_id
    )


def _finalize_success(job_id, generation, response):
    with transaction.atomic():
        job = QuestionGenerationJob.objects.select_for_update().get(pk=job_id)
        if job.status == "succeeded":
            return {"status": "succeeded"}
        if job.status != "running" or job.generation != generation:
            return {"status": job.status}
        subject = job.subject.__class__.objects.select_for_update().get(pk=job.subject_id)
        if not _input_is_current(job, subject):
            return _terminal_locked(job, status="conflict", code="QUESTION_BANK_INPUT_CONFLICT")
        workspace = (
            QuestionBankWorkspace.objects.select_for_update().filter(subject=subject).first()
        )
        actual_version = workspace.version if workspace else 0
        if actual_version != job.expected_workspace_version:
            return _terminal_locked(job, status="conflict", code="QUESTION_BANK_VERSION_CONFLICT")
        if response.model_key != job.model_key:
            raise QuestionGenerationInvalidResponse
        normalized = validate_generated_questions(
            response=response,
            category_ids={uuid.UUID(row["id"]) for row in job.input_categories},
            tag_ids={uuid.UUID(row["id"]) for row in job.input_tags},
            keyword_ids={uuid.UUID(row["id"]) for row in job.input_keywords},
            limit=job.question_limit,
            subject_values=job.input_subject_values,
        )
        output = [item.payload() for item in normalized]
        previous_matching = (
            set(workspace.draft_items.values_list("matching_text", flat=True))
            if workspace is not None
            else set()
        )
        novel_count = sum(1 for item in normalized if item.matching_text not in previous_matching)
        next_version = 1 if workspace is None else workspace.version + 1
        result = QuestionGenerationResult.objects.create(
            job=job,
            output_snapshot=output,
            output_digest=canonical_digest(output),
            item_count=len(output),
            applied_workspace_version=next_version,
            provider_metrics=_safe_provider_metrics(response.provider_metrics),
        )
        if workspace is None:
            workspace = QuestionBankWorkspace.objects.create(
                user_id=job.user_id,
                subject=subject,
                draft_subject_version=job.subject_version,
                draft_distillation_set=job.input_distillation_set,
                draft_source_result=result,
                version=1,
            )
        else:
            workspace.version += 1
            workspace.draft_subject_version = job.subject_version
            workspace.draft_distillation_set = job.input_distillation_set
            workspace.draft_source_result = result
            workspace.save(
                update_fields=(
                    "draft_subject_version",
                    "draft_distillation_set",
                    "draft_source_result",
                    "version",
                    "updated_at",
                )
            )
        _replace_draft(workspace, normalized)
        if novel_count:
            _settle_quota(job, "consume", novel_count)
        if novel_count < job.question_limit:
            _settle_quota(job, "release", job.question_limit - novel_count)
        job.status = "succeeded"
        job.finished_at = timezone.now()
        job.next_attempt_at = None
        job.stable_error_code = ""
        job.version += 1
        job.save(
            update_fields=(
                "status",
                "finished_at",
                "next_attempt_at",
                "stable_error_code",
                "version",
                "updated_at",
            )
        )
        _safe_event(
            job,
            "succeeded",
            summary={
                "item_count": len(output),
                "added_count": novel_count,
                "workspace_version": workspace.version,
            },
        )
        return {"status": "succeeded"}


def execute_question_generation(*, job_id, expected_generation=None):
    claimed = claim_question_generation_job(job_id=job_id, expected_generation=expected_generation)
    if claimed is None:
        return {"status": QuestionGenerationJob.objects.get(pk=job_id).status}
    _, generation = claimed
    job = QuestionGenerationJob.objects.get(pk=job_id)
    try:
        provider = get_question_generation_provider(job.provider_key)
        return _finalize_success(job_id, generation, provider.generate(_request_for_job(job)))
    except QuestionGenerationProviderError as exc:
        if not exc.permanent:
            return _schedule_retry(job_id, generation, exc.code)
        with transaction.atomic():
            locked = QuestionGenerationJob.objects.select_for_update().get(pk=job_id)
            if locked.status != "running" or locked.generation != generation:
                return {"status": locked.status}
            return _terminal_locked(locked, status="failed", code=exc.code)
    except QuestionBankError as exc:
        if not getattr(exc, "permanent", True):
            return _schedule_retry(job_id, generation, exc.code)
        with transaction.atomic():
            locked = QuestionGenerationJob.objects.select_for_update().get(pk=job_id)
            if locked.status != "running" or locked.generation != generation:
                return {"status": locked.status}
            return _terminal_locked(locked, status="failed", code=exc.code)
    except Exception as exc:
        raise QuestionGenerationUnexpectedError(job_id=job_id, generation=generation) from exc


def fail_internal_question_generation(*, job_id, generation):
    with transaction.atomic():
        job = QuestionGenerationJob.objects.select_for_update().get(pk=job_id)
        if job.status != "running" or str(job.generation) != str(generation):
            return {"status": job.status}
        return _terminal_locked(job, status="failed", code="QUESTION_GENERATION_INTERNAL_ERROR")


def due_question_generation_job_ids(limit=100):
    now = timezone.now()
    stale = now - timedelta(seconds=settings.QUESTION_GENERATION_RUNNING_STALE_SECONDS)
    return list(
        QuestionGenerationJob.objects.filter(
            models.Q(status="queued")
            | models.Q(status="retry_wait", next_attempt_at__lte=now)
            | models.Q(status="running", started_at__lte=stale)
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)[:limit]
    )


def question_generation_quota_payload(job):
    account = (
        QuotaAccount.objects.filter(
            subscription=job.subscription,
            subject__isnull=True,
            quota_type="question_generated_items",
        )
        .order_by("-cycle_started_at", "-created_at")
        .first()
    )
    return {
        "billing_mode": "按实际生成数量",
        "held": job.quota_hold_id is not None and job.status not in TERMINAL,
        "remaining": account.available if account else None,
    }


def question_bank_workspace_for_subject(*, user, subject):
    subject_for_user_or_404(user=user, subject_id=subject.pk)
    return (
        QuestionBankWorkspace.objects.select_related(
            "draft_subject_version",
            "draft_distillation_set",
            "draft_source_result",
            "current_version",
        )
        .filter(subject=subject)
        .first()
    )


def _current_catalog_and_keywords(workspace):
    subject = workspace.subject
    categories, tags = _catalog_snapshots(subject)
    keywords = _effective_keywords(workspace.draft_distillation_set)
    return (
        {uuid.UUID(row["id"]) for row in categories},
        {uuid.UUID(row["id"]) for row in tags},
        {uuid.UUID(row["id"]) for row in keywords},
    )


def _assert_workspace_input_current(workspace, subject):
    try:
        distillation_workspace = DistillationWorkspace.objects.select_for_update().get(
            subject=subject
        )
    except DistillationWorkspace.DoesNotExist as exc:
        raise QuestionBankInputConflict from exc
    if (
        subject.current_version_id != workspace.draft_subject_version_id
        or distillation_workspace.current_set_id != workspace.draft_distillation_set_id
    ):
        raise QuestionBankInputConflict


@transaction.atomic
def save_question_bank_draft(*, user_id, subject_id, expected_version, items):
    user = User.objects.select_for_update().get(pk=user_id)
    _assert_user_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.status != subject.Status.ACTIVE:
        raise QuestionBankInputConflict
    subscription = _lock_effective_subscription(user)
    workspace = (
        QuestionBankWorkspace.objects.select_for_update()
        .select_related("subject", "draft_distillation_set")
        .filter(subject=subject)
        .first()
    )
    created = workspace is None
    if created:
        if expected_version != 0 or subject.current_version_id is None:
            raise QuestionBankVersionConflict
        try:
            distillation_workspace = (
                DistillationWorkspace.objects.select_for_update()
                .select_related("current_set")
                .get(subject=subject)
            )
        except DistillationWorkspace.DoesNotExist as exc:
            raise QuestionBankInputConflict from exc
        current_set = distillation_workspace.current_set
        if current_set is None or current_set.subject_version_id != subject.current_version_id:
            raise QuestionBankInputConflict
        workspace = QuestionBankWorkspace.objects.create(
            user=user,
            subject=subject,
            draft_subject_version_id=subject.current_version_id,
            draft_distillation_set=current_set,
            draft_source_result=None,
            version=1,
        )
    else:
        if workspace.version != expected_version:
            raise QuestionBankVersionConflict
        _assert_workspace_input_current(workspace, subject)
    category_ids, tag_ids, keyword_ids = _current_catalog_and_keywords(workspace)
    limit = (
        effective_entitlement_snapshot(subscription).get("limits", {}).get("question_bank_limit")
    )
    if type(limit) is not int or limit < 1:
        limit = 10_000
    normalized = validate_draft_items(
        items=items,
        category_ids=category_ids,
        tag_ids=tag_ids,
        keyword_ids=keyword_ids,
        limit=limit,
    )
    old = [
        {
            "text": row.text,
            "primary_category_id": str(row.primary_category_id),
            "tag_ids": row.tag_ids,
            "keyword_ids": row.keyword_ids,
            "priority": row.priority,
            "question_type": row.question_type,
            "participates_in_scoring": row.participates_in_scoring,
            "ai_reason": row.ai_reason,
        }
        for row in workspace.draft_items.order_by("sort_order", "id")
    ]
    new = [
        {
            "text": row.text,
            "primary_category_id": str(row.primary_category_id),
            "tag_ids": [str(value) for value in row.tag_ids],
            "keyword_ids": [str(value) for value in row.keyword_ids],
            "priority": row.priority,
            "question_type": row.question_type,
            "participates_in_scoring": row.participates_in_scoring,
            "ai_reason": row.reason,
        }
        for row in normalized
    ]
    if old == new:
        return workspace, False
    _replace_draft(workspace, normalized)
    if not created:
        workspace.version += 1
        workspace.save(update_fields=("version", "updated_at"))
    return workspace, True


@transaction.atomic
def confirm_question_bank(*, user_id, subject_id, expected_version):
    user = User.objects.select_for_update().get(pk=user_id)
    _assert_user_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    _lock_effective_subscription(user)
    try:
        workspace = (
            QuestionBankWorkspace.objects.select_for_update(of=("self",))
            .select_related(
                "draft_subject_version",
                "draft_distillation_set",
                "draft_source_result",
                "current_version",
            )
            .get(subject=subject)
        )
    except QuestionBankWorkspace.DoesNotExist as exc:
        raise QuestionBankValuesInvalid from exc
    if workspace.version != expected_version:
        raise QuestionBankVersionConflict
    _assert_workspace_input_current(workspace, subject)
    rows = list(
        workspace.draft_items.select_related("primary_category").order_by("sort_order", "id")
    )
    if not rows:
        raise QuestionBankValuesInvalid
    payload = [
        {
            "text": row.text,
            "primary_category_id": str(row.primary_category_id),
            "tag_ids": row.tag_ids,
            "keyword_ids": row.keyword_ids,
            "priority": row.priority,
            "question_type": row.question_type,
            "participates_in_scoring": row.participates_in_scoring,
            "ai_reason": row.ai_reason,
            "sort_order": row.sort_order,
        }
        for row in rows
    ]
    digest = canonical_digest(
        {
            "subject_version_id": str(workspace.draft_subject_version_id),
            "distillation_set_id": str(workspace.draft_distillation_set_id),
            "items": payload,
        }
    )
    if workspace.current_version and workspace.current_version.content_digest == digest:
        raise QuestionBankVersionNoChanges
    latest_version_no = (
        QuestionBankVersion.objects.filter(workspace=workspace).aggregate(
            maximum=models.Max("version_no")
        )["maximum"]
        or 0
    )
    next_version = latest_version_no + 1
    version = QuestionBankVersion.objects.create(
        workspace=workspace,
        user=user,
        subject=subject,
        subject_version=workspace.draft_subject_version,
        distillation_set=workspace.draft_distillation_set,
        source_result=workspace.draft_source_result,
        version_no=next_version,
        content_digest=digest,
        item_count=len(rows),
        confirmed_by=user,
        confirmed_at=timezone.now(),
    )
    question_ids = [uuid.uuid4() for _ in rows]
    Question.objects.bulk_create(
        [
            Question(
                id=question_ids[index],
                question_bank_version=version,
                text=row.text,
                matching_text=row.matching_text,
                primary_category=row.primary_category,
                primary_category_key=row.primary_category.key,
                primary_category_name=row.primary_category.name,
                primary_category_version=row.primary_category.version,
                priority=row.priority,
                question_type=row.question_type,
                participates_in_scoring=row.participates_in_scoring,
                ai_reason=row.ai_reason,
                sort_order=row.sort_order,
            )
            for index, row in enumerate(rows)
        ]
    )
    tag_ids = {uuid.UUID(value) for row in rows for value in row.tag_ids}
    tags = {row.pk: row for row in QuestionTag.objects.filter(pk__in=tag_ids)}
    keyword_ids = {uuid.UUID(value) for row in rows for value in row.keyword_ids}
    keywords = {row.pk: row for row in Keyword.objects.filter(pk__in=keyword_ids)}
    QuestionTagLink.objects.bulk_create(
        [
            QuestionTagLink(
                question_id=question_ids[index],
                tag=tags[uuid.UUID(tag_id)],
                tag_key=tags[uuid.UUID(tag_id)].key,
                tag_name=tags[uuid.UUID(tag_id)].name,
                tag_version=tags[uuid.UUID(tag_id)].version,
            )
            for index, row in enumerate(rows)
            for tag_id in row.tag_ids
        ]
    )
    QuestionKeywordLink.objects.bulk_create(
        [
            QuestionKeywordLink(
                question_id=question_ids[index],
                keyword=keywords[uuid.UUID(keyword_id)],
                keyword_text=keywords[uuid.UUID(keyword_id)].text,
            )
            for index, row in enumerate(rows)
            for keyword_id in row.keyword_ids
        ]
    )
    workspace.current_version = version
    workspace.version += 1
    workspace.save(update_fields=("current_version", "version", "updated_at"))
    return workspace, version


def _formal_rows_match_draft(rows, draft_rows):
    if len(rows) != len(draft_rows):
        return False
    for row, draft_row in zip(rows, draft_rows, strict=True):
        if (
            row.text != draft_row.text
            or row.matching_text != draft_row.matching_text
            or row.primary_category_id != draft_row.primary_category_id
            or row.priority != draft_row.priority
            or row.question_type != draft_row.question_type
            or row.participates_in_scoring != draft_row.participates_in_scoring
            or row.ai_reason != draft_row.ai_reason
            or {str(link.tag_id) for link in row.tag_links.all()} != set(draft_row.tag_ids)
            or {str(link.keyword_id) for link in row.keyword_links.all()}
            != set(draft_row.keyword_ids)
        ):
            return False
    return True


def _normalized_formal_rows(rows):
    return [
        NormalizedQuestion(
            text=row.text,
            matching_text=row.matching_text,
            primary_category_id=row.primary_category_id,
            tag_ids=tuple(link.tag_id for link in row.tag_links.all()),
            keyword_ids=tuple(link.keyword_id for link in row.keyword_links.all()),
            priority=row.priority,
            question_type=row.question_type,
            participates_in_scoring=row.participates_in_scoring,
            reason=row.ai_reason,
        )
        for row in rows
    ]


@transaction.atomic
def remove_current_question_bank_items(*, user_id, subject_id, expected_version_id, question_ids):
    """Remove questions by advancing the append-only formal question-bank history."""

    user = User.objects.select_for_update().get(pk=user_id)
    _assert_user_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.status != subject.Status.ACTIVE:
        raise QuestionBankInputConflict
    try:
        workspace = (
            QuestionBankWorkspace.objects.select_for_update(of=("self",))
            .select_related(
                "draft_subject_version",
                "draft_distillation_set",
                "draft_source_result",
                "current_version",
            )
            .get(subject=subject)
        )
    except QuestionBankWorkspace.DoesNotExist as exc:
        raise QuestionBankValuesInvalid from exc
    current = workspace.current_version
    if current is None or current.pk != expected_version_id:
        raise QuestionBankVersionConflict
    rows = list(
        current.questions.select_related("primary_category")
        .prefetch_related("tag_links", "keyword_links")
        .order_by("sort_order", "id")
    )
    remove_ids = set(question_ids)
    available_ids = {row.pk for row in rows}
    if not remove_ids or not remove_ids.issubset(available_ids):
        raise QuestionBankValuesInvalid
    remaining = [row for row in rows if row.pk not in remove_ids]
    draft_rows = list(
        workspace.draft_items.select_related("primary_category").order_by("sort_order", "id")
    )
    draft_binding_matches = (
        workspace.draft_subject_version_id == current.subject_version_id
        and workspace.draft_distillation_set_id == current.distillation_set_id
        and workspace.draft_source_result_id == current.source_result_id
    )
    sync_draft = draft_binding_matches and _formal_rows_match_draft(rows, draft_rows)

    if not remaining:
        if sync_draft:
            QuestionDraftItem.objects.filter(workspace=workspace).delete()
            workspace.draft_source_result = None
        workspace.current_version = None
        workspace.version += 1
        update_fields = ["current_version", "version", "updated_at"]
        if sync_draft:
            update_fields.append("draft_source_result")
        workspace.save(update_fields=update_fields)
        return workspace, None, len(remove_ids)

    payload = [
        {
            "text": row.text,
            "primary_category_id": str(row.primary_category_id),
            "tag_ids": [str(link.tag_id) for link in row.tag_links.all()],
            "keyword_ids": [str(link.keyword_id) for link in row.keyword_links.all()],
            "priority": row.priority,
            "question_type": row.question_type,
            "participates_in_scoring": row.participates_in_scoring,
            "ai_reason": row.ai_reason,
            "sort_order": index,
        }
        for index, row in enumerate(remaining)
    ]
    next_version = current.version_no + 1
    restore_draft_binding = (
        workspace.draft_subject_version_id != current.subject_version_id
        or workspace.draft_distillation_set_id != current.distillation_set_id
    )
    draft_subject_version_id = workspace.draft_subject_version_id
    draft_distillation_set_id = workspace.draft_distillation_set_id
    if restore_draft_binding:
        # PostgreSQL protects each formal version binding against the workspace draft input.
        # Rebind only inside this transaction, then restore the newer unconfirmed draft below.
        workspace.draft_subject_version_id = current.subject_version_id
        workspace.draft_distillation_set_id = current.distillation_set_id
        workspace.version += 1
        workspace.save(
            update_fields=(
                "draft_subject_version",
                "draft_distillation_set",
                "version",
                "updated_at",
            )
        )
    version = QuestionBankVersion.objects.create(
        workspace=workspace,
        user=user,
        subject=subject,
        subject_version=current.subject_version,
        distillation_set=current.distillation_set,
        source_result=current.source_result,
        version_no=next_version,
        content_digest=canonical_digest(
            {
                "subject_version_id": str(current.subject_version_id),
                "distillation_set_id": str(current.distillation_set_id),
                "items": payload,
            }
        ),
        item_count=len(remaining),
        confirmed_by=user,
        confirmed_at=timezone.now(),
    )
    question_ids_by_index = [uuid.uuid4() for _ in remaining]
    Question.objects.bulk_create(
        [
            Question(
                id=question_ids_by_index[index],
                question_bank_version=version,
                text=row.text,
                matching_text=row.matching_text,
                primary_category=row.primary_category,
                primary_category_key=row.primary_category_key,
                primary_category_name=row.primary_category_name,
                primary_category_version=row.primary_category_version,
                priority=row.priority,
                question_type=row.question_type,
                participates_in_scoring=row.participates_in_scoring,
                ai_reason=row.ai_reason,
                sort_order=index,
            )
            for index, row in enumerate(remaining)
        ]
    )
    QuestionTagLink.objects.bulk_create(
        [
            QuestionTagLink(
                question_id=question_ids_by_index[index],
                tag_id=link.tag_id,
                tag_key=link.tag_key,
                tag_name=link.tag_name,
                tag_version=link.tag_version,
            )
            for index, row in enumerate(remaining)
            for link in row.tag_links.all()
        ]
    )
    QuestionKeywordLink.objects.bulk_create(
        [
            QuestionKeywordLink(
                question_id=question_ids_by_index[index],
                keyword_id=link.keyword_id,
                keyword_text=link.keyword_text,
            )
            for index, row in enumerate(remaining)
            for link in row.keyword_links.all()
        ]
    )
    if sync_draft:
        _replace_draft(workspace, _normalized_formal_rows(remaining))
    if restore_draft_binding:
        workspace.draft_subject_version_id = draft_subject_version_id
        workspace.draft_distillation_set_id = draft_distillation_set_id
    workspace.current_version = version
    workspace.version += 1
    update_fields = ["current_version", "version", "updated_at"]
    if restore_draft_binding:
        update_fields.extend(("draft_subject_version", "draft_distillation_set"))
    workspace.save(update_fields=update_fields)
    return workspace, version, len(remove_ids)


def question_bank_versions_for_user(*, user, subject_id):
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    return QuestionBankVersion.objects.filter(subject=subject).order_by("-version_no", "id")


def question_bank_version_for_user_or_404(*, user, subject_id, version_id):
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    try:
        return (
            QuestionBankVersion.objects.select_related(
                "subject_version", "distillation_set", "source_result"
            )
            .prefetch_related(
                "questions__primary_category", "questions__tag_links", "questions__keyword_links"
            )
            .get(pk=version_id, subject=subject)
        )
    except QuestionBankVersion.DoesNotExist as exc:
        raise Http404 from exc


def current_question_bank_for_user_or_404(*, user, subject_id):
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    try:
        workspace = QuestionBankWorkspace.objects.get(subject=subject)
    except QuestionBankWorkspace.DoesNotExist as exc:
        raise Http404 from exc
    if workspace.current_version_id is None:
        raise Http404
    return question_bank_version_for_user_or_404(
        user=user, subject_id=subject_id, version_id=workspace.current_version_id
    )
