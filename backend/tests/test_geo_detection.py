from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.ai.contracts import (
    AIAdapterDescriptor,
    AIAdapterResponse,
    AIAdapterTiming,
    AIFinishReason,
    AIModelCapability,
    AIModelIdentity,
    AIUsage,
)
from apps.ai.detection import DetectionOutput
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.models import AIModelRuntimeConfig
from apps.geo.exceptions import (
    GeoDetectionConcurrencyLimit,
    GeoDetectionIdempotencyConflict,
)
from apps.geo.models import GeoDetectionJob, ModelCall, ModelResponse
from apps.geo.services import (
    cancel_detection,
    create_detection_job,
    due_model_call_ids,
    estimate_detection,
    execute_model_call,
)
from apps.questions.bank_models import QuestionBankWorkspace
from apps.questions.generation_services import confirm_question_bank, execute_question_generation
from apps.quotas.models import QuotaAccount, QuotaLedgerEntry
from tests import test_distillation as distillation_tests
from tests.test_question_bank import create_job as create_question_job
from tests.test_question_bank import facts as question_facts

pytestmark = pytest.mark.django_db


class _FakeSemaphoreStore:
    def acquire(self, **kwargs):
        del kwargs
        return object()

    def release(self, lease):
        del lease


class _SuccessAdapter:
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
        capabilities=frozenset({AIModelCapability.GEO_DETECTION}),
        adapter_version="geo-test-v1",
        prompt_version="geo-detection-v1",
    )

    def invoke(self, request):
        return AIAdapterResponse(
            request_id=request.request_id,
            identity=request.identity,
            provider_request_id="provider-safe-123",
            output=DetectionOutput(
                provider_model_id=request.payload.provider_model_id,
                raw_text="这是一个用于检测执行测试的安全中文回答。",
                web_search_requested=request.payload.web_search_requested,
                web_search_used=False,
                degraded=request.payload.web_search_requested,
            ),
            usage=AIUsage(input_tokens=11, output_tokens=13, total_tokens=24),
            timing=AIAdapterTiming(latency_ms=120),
            finish_reason=AIFinishReason.STOP,
            sanitized_provider_metadata={"model": request.payload.provider_model_id},
        )


class _RetryAdapter(_SuccessAdapter):
    def invoke(self, request):
        del request
        raise AIAdapterError(
            AIAdapterErrorCategory.TIMEOUT,
            stable_code="AI_GEO_TEST_TIMEOUT",
            retryable=True,
        )


@pytest.fixture(autouse=True)
def _catalogs():
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)


@pytest.fixture
def geo_facts(monkeypatch):
    original_limits = distillation_tests._limits

    def geo_limits(*args, **kwargs):
        values = original_limits(*args, **kwargs)
        values.update(
            {
                "detection_points": 20,
                "max_models_per_detection": 2,
                "max_questions_per_detection": 3,
                "concurrent_detection_jobs": 1,
                "allow_user_model_selection": True,
            }
        )
        return values

    monkeypatch.setattr(distillation_tests, "_limits", geo_limits)
    user, subject, _, subscription, distilled = question_facts(
        limit=3,
        model_permissions=[{"model_key": "deepseek", "selected_by_default": True, "sort_order": 0}],
    )
    generation_job, _ = create_question_job(user, subject, distilled)
    assert execute_question_generation(job_id=generation_job.pk) == {"status": "succeeded"}
    workspace = QuestionBankWorkspace.objects.get(subject=subject)
    _, question_bank = confirm_question_bank(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=workspace.version,
    )

    runtime = AIModelRuntimeConfig.objects.select_related("model__provider").get(
        model__model_key="deepseek"
    )
    runtime.enabled = True
    runtime.paused = False
    runtime.provider_model_id = "deepseek-v4-flash"
    runtime.network_access_enabled = False
    runtime.timeout_seconds = 30
    runtime.max_retries = 1
    runtime.retry_base_seconds = 1
    runtime.retry_backoff = "exponential"
    runtime.max_concurrency = 1
    runtime.version += 1
    runtime.save()

    questions = list(question_bank.questions.order_by("sort_order", "id")[:2])
    assert len(questions) == 2
    return user, subject, subscription, runtime, questions


def _create(geo_facts, *, key="geo-detection-idempotency-0001"):
    user, subject, _, runtime, questions = geo_facts
    with (
        patch("apps.geo.services._credential_configured", return_value=True),
        patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()),
    ):
        return create_detection_job(
            user_id=user.pk,
            subject_id=subject.pk,
            question_ids=[question.pk for question in questions],
            model_ids=[runtime.model_id],
            mode="new",
            idempotency_key=key,
            request_id=uuid.uuid4(),
        )


def test_estimate_and_create_freeze_immutable_snapshot_and_matrix(geo_facts):
    user, subject, subscription, runtime, questions = geo_facts
    with (
        patch("apps.geo.services._credential_configured", return_value=True),
        patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()),
    ):
        estimate = estimate_detection(
            user=user,
            subject_id=subject.pk,
            question_ids=[question.pk for question in questions],
            model_ids=[runtime.model_id],
        )
        job, created = create_detection_job(
            user_id=user.pk,
            subject_id=subject.pk,
            question_ids=[question.pk for question in questions],
            model_ids=[runtime.model_id],
            mode="new",
            idempotency_key="geo-detection-idempotency-0001",
            request_id=uuid.uuid4(),
        )
    assert estimate["required_detection_points"] == 2
    assert created is True
    assert job.planned_detection_points == 2
    assert job.snapshot.question_bank_version_id
    assert job.snapshot.subject_version_id == subject.current_version_id
    assert job.snapshot.questions.count() == 2
    assert job.model_runs.count() == 1
    assert job.model_calls.count() == 2
    assert job.quota_hold.requested_amount == 2
    account = QuotaAccount.objects.get(
        subscription=subscription, quota_type="detection_points", subject__isnull=True
    )
    assert account.frozen == 2
    assert account.available == 18
    with pytest.raises(TypeError):
        job.snapshot.save()


def test_create_idempotency_replays_and_mismatched_payload_conflicts(geo_facts):
    first, created = _create(geo_facts)
    replay, replay_created = _create(geo_facts)
    assert created is True
    assert replay_created is False
    assert replay.pk == first.pk

    user, subject, _, runtime, questions = geo_facts
    with (
        patch("apps.geo.services._credential_configured", return_value=True),
        patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()),
        pytest.raises(GeoDetectionIdempotencyConflict),
    ):
        create_detection_job(
            user_id=user.pk,
            subject_id=subject.pk,
            question_ids=[questions[0].pk],
            model_ids=[runtime.model_id],
            mode="new",
            idempotency_key="geo-detection-idempotency-0001",
            request_id=uuid.uuid4(),
        )


def test_user_concurrency_limit_is_enforced_transactionally(geo_facts):
    _create(geo_facts)
    user, subject, _, runtime, questions = geo_facts
    with (
        patch("apps.geo.services._credential_configured", return_value=True),
        patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()),
        pytest.raises(GeoDetectionConcurrencyLimit),
    ):
        create_detection_job(
            user_id=user.pk,
            subject_id=subject.pk,
            question_ids=[question.pk for question in questions],
            model_ids=[runtime.model_id],
            mode="new",
            idempotency_key="geo-detection-idempotency-0002",
            request_id=uuid.uuid4(),
        )


def test_successful_call_consumes_exactly_one_point_and_persists_safe_response(geo_facts):
    job, _ = _create(geo_facts)
    call = job.model_calls.order_by("id").first()
    assert call is not None
    with patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()):
        result = execute_model_call(call_id=call.pk, semaphore_store=_FakeSemaphoreStore())
    assert result == {"status": "succeeded"}
    call.refresh_from_db()
    job.quota_hold.refresh_from_db()
    assert call.status == ModelCall.Status.SUCCEEDED
    assert call.settlement_status == ModelCall.Settlement.CONSUMED
    assert call.provider_request_id == "provider-safe-123"
    assert job.quota_hold.consumed_amount == 1
    assert ModelResponse.objects.get(model_call=call).raw_text.startswith("这是一个")
    assert (
        QuotaLedgerEntry.objects.filter(
            hold__group=job.quota_hold,
            action=QuotaLedgerEntry.Action.CONSUME,
        ).count()
        == 1
    )


def test_retryable_failure_reuses_same_logical_point_and_worker_retry_boundary(geo_facts):
    job, _ = _create(geo_facts)
    call = job.model_calls.order_by("id").first()
    assert call is not None
    with patch("apps.geo.services.model_registry.resolve", return_value=_RetryAdapter()):
        result = execute_model_call(call_id=call.pk, semaphore_store=_FakeSemaphoreStore())
    assert result == {"status": "retry_wait"}
    call.refresh_from_db()
    job.quota_hold.refresh_from_db()
    assert call.status == ModelCall.Status.RETRY_WAIT
    assert call.attempt_count == 1
    assert call.settlement_status == ModelCall.Settlement.PENDING
    assert job.quota_hold.consumed_amount == 0
    assert job.quota_hold.released_amount == 0

    ModelCall.objects.filter(pk=call.pk).update(next_attempt_at=timezone.now())
    with patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()):
        assert execute_model_call(call_id=call.pk, semaphore_store=_FakeSemaphoreStore()) == {
            "status": "succeeded"
        }
    call.refresh_from_db()
    job.quota_hold.refresh_from_db()
    assert call.attempt_count == 2
    assert job.quota_hold.consumed_amount == 1


def test_pause_before_attempt_fails_closed_and_releases_point(geo_facts):
    job, _ = _create(geo_facts)
    call = job.model_calls.order_by("id").first()
    assert call is not None
    runtime = AIModelRuntimeConfig.objects.get(model_id=call.model_id)
    runtime.paused = True
    runtime.pause_reason = "detection execution pause test"
    runtime.version += 1
    runtime.save(update_fields=("paused", "pause_reason", "version", "updated_at"))
    result = execute_model_call(call_id=call.pk, semaphore_store=_FakeSemaphoreStore())
    assert result == {"status": "failed"}
    call.refresh_from_db()
    job.quota_hold.refresh_from_db()
    assert call.stable_error_code == "GEO_DETECTION_MODEL_PAUSED_OR_DISABLED"
    assert call.settlement_status == ModelCall.Settlement.RELEASED
    assert job.quota_hold.released_amount == 1


def test_user_cancel_only_cancels_unstarted_calls_and_releases_remaining_points(geo_facts):
    job, _ = _create(geo_facts)
    user, *_ = geo_facts
    job = cancel_detection(user=user, detection_id=job.pk)
    assert job.cancel_requested_at is not None
    assert job.status == GeoDetectionJob.Status.CANCELLED
    assert set(job.model_calls.values_list("status", flat=True)) == {ModelCall.Status.CANCELLED}
    job.quota_hold.refresh_from_db()
    assert job.quota_hold.released_amount == job.planned_detection_points
    assert job.quota_hold.consumed_amount == 0


def test_priority_dispatch_order_uses_database_queue_truth(geo_facts):
    job, _ = _create(geo_facts)
    call_ids = list(job.model_calls.order_by("id").values_list("id", flat=True))
    assert due_model_call_ids(limit=10) == call_ids
