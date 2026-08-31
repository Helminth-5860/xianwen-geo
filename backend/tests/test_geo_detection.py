from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

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
from apps.geo.models import GeoDetectionJob, GeoDetectionModelRun, ModelCall, ModelResponse
from apps.geo.services import (
    cancel_detection,
    create_detection_job,
    detection_options,
    due_model_call_ids,
    estimate_detection,
    execute_model_call,
)
from apps.keywords.distillation_services import confirm_distillation, execute_distillation
from apps.keywords.models import DistillationWorkspace
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
                "geo_detection_runs": 20,
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
    assert estimate["required_detection_runs"] == 1
    assert created is True
    assert job.planned_detection_points == 2
    assert job.snapshot.question_bank_version_id
    assert job.snapshot.subject_version_id == subject.current_version_id
    assert job.snapshot.questions.count() == 2
    assert job.model_runs.count() == 1
    assert job.model_calls.count() == 2
    assert job.quota_hold.requested_amount == 1
    account = QuotaAccount.objects.get(
        subscription=subscription, quota_type="geo_detection_runs", subject__isnull=True
    )
    assert account.frozen == 1
    assert account.available == 19
    with pytest.raises(TypeError):
        job.snapshot.save()


def test_detection_keeps_using_current_formal_question_chain_after_new_distillation(geo_facts):
    user, subject, _, _, _ = geo_facts
    question_workspace = QuestionBankWorkspace.objects.select_related(
        "current_version__distillation_set__input_keyword_set_version"
    ).get(subject=subject)
    question_bank = question_workspace.current_version
    original_distillation = question_bank.distillation_set
    original_keyword_version = original_distillation.input_keyword_set_version

    distillation_workspace = DistillationWorkspace.objects.get(subject=subject)
    regeneration, _ = distillation_tests._create(
        user,
        subject,
        original_keyword_version,
        workspace_version=distillation_workspace.version,
        regenerate=True,
    )
    assert execute_distillation(job_id=regeneration.pk) == {"status": "succeeded"}
    distillation_workspace.refresh_from_db()
    _, latest_distillation = confirm_distillation(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=distillation_workspace.version,
    )
    assert latest_distillation.pk != original_distillation.pk

    options = detection_options(user=user, subject_id=subject.pk)
    assert options["question_bank_version_id"] == str(question_bank.pk)
    assert options["question_count"] == question_bank.item_count

    job, created = _create(
        geo_facts,
        key="geo-detection-formal-question-chain-after-new-distillation",
    )
    assert created is True
    assert job.snapshot.question_bank_version_id == question_bank.pk
    assert job.snapshot.distillation_set_id == original_distillation.pk
    assert job.snapshot.keyword_set_version_id == original_keyword_version.pk


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


def test_successful_detection_consumes_once_after_all_calls_finish(geo_facts):
    job, _ = _create(geo_facts)
    call = job.model_calls.order_by("id").first()
    assert call is not None
    with patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()):
        result = execute_model_call(call_id=call.pk, semaphore_store=_FakeSemaphoreStore())
    assert result == {"status": "succeeded", "terminal_transition": True}
    call.refresh_from_db()
    job.quota_hold.refresh_from_db()
    assert call.status == ModelCall.Status.SUCCEEDED
    assert call.settlement_status == ModelCall.Settlement.CONSUMED
    assert call.provider_request_id == "provider-safe-123"
    assert job.quota_hold.consumed_amount == 0
    assert ModelResponse.objects.get(model_call=call).raw_text.startswith("这是一个")
    duplicate = execute_model_call(call_id=call.pk, semaphore_store=_FakeSemaphoreStore())
    assert duplicate == {"status": "succeeded", "terminal_transition": False}
    remaining_call = job.model_calls.exclude(pk=call.pk).get()
    with patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()):
        execute_model_call(call_id=remaining_call.pk, semaphore_store=_FakeSemaphoreStore())
    job.quota_hold.refresh_from_db()
    assert job.quota_hold.consumed_amount == 1

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
    assert result == {"status": "retry_wait", "terminal_transition": False}
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
            "status": "succeeded",
            "terminal_transition": True,
        }
    call.refresh_from_db()
    job.quota_hold.refresh_from_db()
    assert call.attempt_count == 2
    assert job.quota_hold.consumed_amount == 0
    remaining_call = job.model_calls.exclude(pk=call.pk).get()
    with patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()):
        execute_model_call(call_id=remaining_call.pk, semaphore_store=_FakeSemaphoreStore())
    job.quota_hold.refresh_from_db()
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
    assert result == {"status": "failed", "terminal_transition": True}
    remaining_call = job.model_calls.exclude(pk=call.pk).get()
    execute_model_call(call_id=remaining_call.pk, semaphore_store=_FakeSemaphoreStore())
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
    assert job.quota_hold.released_amount == 1
    assert job.quota_hold.consumed_amount == 0


def test_priority_dispatch_order_uses_database_queue_truth(geo_facts):
    job, _ = _create(geo_facts)
    call_ids = list(job.model_calls.order_by("id").values_list("id", flat=True))
    assert due_model_call_ids(limit=10) == call_ids


def test_successful_call_persists_prevalidated_citation_facts(geo_facts):
    from apps.geo.citations import NormalizedCitation
    from apps.geo.models import ModelResponseCitation

    normalized = NormalizedCitation(
        title="Example",
        canonical_url="https://example.com/article",
        source_name="Example",
        source_host="example.com",
        quoted_text="quote",
        provider_rank=1,
        url_status=ModelResponseCitation.UrlStatus.SAFE,
        source_category=ModelResponseCitation.SourceCategory.WEB,
        extraction_method=ModelResponseCitation.ExtractionMethod.PROVIDER,
    )
    job, _ = _create(geo_facts)
    call = job.model_calls.order_by("id").first()
    assert call is not None

    with (
        patch(
            "apps.geo.services.normalize_detection_citations",
            return_value=(normalized,),
        ),
        patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()),
    ):
        result = execute_model_call(
            call_id=call.pk,
            semaphore_store=_FakeSemaphoreStore(),
        )

    assert result == {"status": "succeeded", "terminal_transition": True}
    citation = ModelResponseCitation.objects.get(model_response__model_call=call)
    assert citation.canonical_url == "https://example.com/article"
    assert citation.source_host == "example.com"
    assert citation.url_status == ModelResponseCitation.UrlStatus.SAFE


def test_successful_natural_call_persists_programmatic_zero_for_no_mention(geo_facts):
    from apps.geo.models import ProgrammaticScoreResult

    job, _ = _create(geo_facts)
    call = job.model_calls.filter(question_snapshot__question_type="natural").order_by("id").first()
    assert call is not None

    with patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()):
        result = execute_model_call(
            call_id=call.pk,
            semaphore_store=_FakeSemaphoreStore(),
        )

    assert result == {"status": "succeeded", "terminal_transition": True}
    score = ProgrammaticScoreResult.objects.get(model_response__model_call=call)
    assert score.mention_score == 0
    assert score.rank_score == 0
    assert score.rank_resolution == ProgrammaticScoreResult.RankResolution.DETERMINISTIC
    assert score.scoring_rule_version == call.job.snapshot.scoring_rule_version


def test_progress_apis_restore_owned_job_and_quota_settlement(geo_facts):
    job, _ = _create(geo_facts)
    user = geo_facts[0]
    client = APIClient()
    client.force_authenticate(user)

    detail = client.get(f"/api/v1/geo/detections/{job.pk}")
    progress = client.get(f"/api/v1/geo/detections/{job.pk}/model-progress")

    assert detail.status_code == 200
    assert detail.json()["data"]["progress_percent"] == 0
    assert detail.json()["data"]["quota"] == {
        "quota_type": "geo_detection_runs",
        "status": "open",
        "held": 1,
        "consumed": 0,
        "released": 0,
    }
    assert progress.status_code == 200
    assert (
        progress.json()["data"]["items"][0]
        | {
            "model_key": "deepseek",
            "status": "queued",
            "planned_calls": 2,
            "completed_calls": 0,
        }
        == progress.json()["data"]["items"][0]
    )

    cancel_detection(user=user, detection_id=job.pk)
    terminal = client.get(f"/api/v1/geo/detections/{job.pk}")
    assert terminal.status_code == 200
    assert (
        terminal.json()["data"]
        | {
            "status": "cancelled",
            "completed_calls": 2,
            "cancelled_calls": 2,
            "progress_percent": 100,
            "quota": {
                "quota_type": "geo_detection_runs",
                "status": "settled",
                "held": 1,
                "consumed": 0,
                "released": 1,
            },
        }
        == terminal.json()["data"]
    )


def test_model_progress_api_returns_mixed_stored_run_statuses(geo_facts):
    job, _ = _create(geo_facts)
    user = geo_facts[0]
    original = job.model_runs.get()
    models = list(
        AIModelRuntimeConfig.objects.select_related("model__provider")
        .exclude(model_id=original.model_id)
        .order_by("model__canonical_order")[:3]
    )
    assert len(models) == 3

    original.status = GeoDetectionModelRun.Status.SUCCEEDED
    original.completed_calls = 2
    original.successful_calls = 2
    original.save(update_fields=("status", "completed_calls", "successful_calls", "updated_at"))
    run_facts = (
        (models[0], GeoDetectionModelRun.Status.RUNNING, 2, 1, 1, 0, 0),
        (models[1], GeoDetectionModelRun.Status.FAILED, 2, 2, 0, 2, 0),
        (models[2], GeoDetectionModelRun.Status.CANCELLED, 2, 2, 0, 0, 2),
    )
    for runtime, status, planned, completed, succeeded, failed, cancelled in run_facts:
        GeoDetectionModelRun.objects.create(
            job=job,
            model=runtime.model,
            provider_key=runtime.model.provider.provider_key,
            model_key=runtime.model.model_key,
            provider_model_id=runtime.provider_model_id or f"{runtime.model.model_key}-test",
            runtime_snapshot={},
            adapter_version="progress-test-v1",
            prompt_version="geo-detection-v1",
            status=status,
            planned_calls=planned,
            completed_calls=completed,
            successful_calls=succeeded,
            failed_calls=failed,
            cancelled_calls=cancelled,
        )

    client = APIClient()
    client.force_authenticate(user)
    response = client.get(f"/api/v1/geo/detections/{job.pk}/model-progress")
    assert response.status_code == 200
    items = {item["model_key"]: item for item in response.json()["data"]["items"]}
    assert len(items) == 4
    expected = {
        original.model_key: ("succeeded", 2, 2, 2, 0, 0),
        models[0].model.model_key: ("running", 2, 1, 1, 0, 0),
        models[1].model.model_key: ("failed", 2, 2, 0, 2, 0),
        models[2].model.model_key: ("cancelled", 2, 2, 0, 0, 2),
    }
    for model_key, facts in expected.items():
        item = items[model_key]
        assert item["model_id"]
        assert (
            item["status"],
            item["planned_calls"],
            item["completed_calls"],
            item["successful_calls"],
            item["failed_calls"],
            item["cancelled_calls"],
        ) == facts


def test_progress_apis_hide_other_users_jobs_and_missing_jobs(geo_facts):
    job, _ = _create(geo_facts)
    User = get_user_model()
    other = User.objects.create_user(
        phone="13500135042",
        nickname="Progress reader",
        password="progress-test-password",
    )
    client = APIClient()
    client.force_authenticate(other)

    assert client.get(f"/api/v1/geo/detections/{job.pk}").status_code == 404
    assert client.get(f"/api/v1/geo/detections/{job.pk}/model-progress").status_code == 404
    assert client.get(f"/api/v1/geo/detections/{uuid.uuid4()}").status_code == 404


def _mark_job_terminal(job, status):
    planned = job.planned_detection_points
    now = timezone.now()
    values = {
        "status": status,
        "completed_calls": planned,
        "successful_calls": 0,
        "failed_calls": 0,
        "cancelled_calls": 0,
        "finished_at": now,
    }
    if status == GeoDetectionJob.Status.SUCCEEDED:
        values["successful_calls"] = planned
    elif status == GeoDetectionJob.Status.PARTIAL:
        values["successful_calls"] = 1
        values["failed_calls"] = planned - 1
    elif status == GeoDetectionJob.Status.FAILED:
        values["failed_calls"] = planned
    else:
        values["cancelled_calls"] = planned
        values["cancel_requested_at"] = now
        values["cancelled_at"] = now
    GeoDetectionJob.objects.filter(pk=job.pk).update(**values)
    job.refresh_from_db()


@pytest.mark.parametrize(
    "status",
    (
        GeoDetectionJob.Status.PARTIAL,
        GeoDetectionJob.Status.SUCCEEDED,
        GeoDetectionJob.Status.FAILED,
        GeoDetectionJob.Status.CANCELLED,
    ),
)
def test_terminal_detection_can_be_idempotently_removed_from_subject_history(geo_facts, status):
    job, _ = _create(geo_facts, key=f"geo-remove-{status}-{uuid.uuid4()}")
    _mark_job_terminal(job, status)
    user, subject, *_ = geo_facts
    client = APIClient()
    client.force_authenticate(user)
    url = f"/api/v1/subjects/{subject.pk}/geo/detections/{job.pk}"
    snapshot_id = job.snapshot.pk
    call_ids = list(job.model_calls.order_by("id").values_list("id", flat=True))
    quota_before = (
        job.quota_hold.status,
        job.quota_hold.requested_amount,
        job.quota_hold.consumed_amount,
        job.quota_hold.released_amount,
    )

    removed = client.delete(url)
    repeated = client.delete(url)

    assert removed.status_code == 200
    assert removed.json()["data"] == {"removed": True}
    assert repeated.status_code == 200
    assert repeated.json()["data"] == {"removed": True}
    job.refresh_from_db()
    job.quota_hold.refresh_from_db()
    assert job.user_removed_at is not None
    assert job.snapshot.pk == snapshot_id
    assert list(job.model_calls.order_by("id").values_list("id", flat=True)) == call_ids
    assert (
        job.quota_hold.status,
        job.quota_hold.requested_amount,
        job.quota_hold.consumed_amount,
        job.quota_hold.released_amount,
    ) == quota_before
    history = client.get(f"/api/v1/subjects/{subject.pk}/geo/detections")
    assert history.status_code == 200
    assert history.json()["data"]["items"] == []
    assert client.get(f"/api/v1/geo/detections/{job.pk}").status_code == 404
    assert client.get(f"/api/v1/geo/detections/{job.pk}/model-progress").status_code == 404
    assert client.get(f"/api/v1/geo/detections/{job.pk}/report").status_code == 404


@pytest.mark.parametrize("status", (GeoDetectionJob.Status.QUEUED, GeoDetectionJob.Status.RUNNING))
def test_active_detection_cannot_be_removed(geo_facts, status):
    job, _ = _create(geo_facts, key=f"geo-remove-active-{status}-{uuid.uuid4()}")
    if status == GeoDetectionJob.Status.RUNNING:
        GeoDetectionJob.objects.filter(pk=job.pk).update(
            status=GeoDetectionJob.Status.RUNNING,
            started_at=timezone.now(),
        )
    user, subject, *_ = geo_facts
    client = APIClient()
    client.force_authenticate(user)

    response = client.delete(f"/api/v1/subjects/{subject.pk}/geo/detections/{job.pk}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GEO_DETECTION_STATE_CONFLICT"
    job.refresh_from_db()
    assert job.user_removed_at is None


def test_detection_remove_is_subject_scoped_and_hides_cross_user_objects(geo_facts):
    job, _ = _create(geo_facts, key=f"geo-remove-scope-{uuid.uuid4()}")
    _mark_job_terminal(job, GeoDetectionJob.Status.FAILED)
    user, subject, *_ = geo_facts
    owner = APIClient()
    owner.force_authenticate(user)
    User = get_user_model()
    other = User.objects.create_user(
        phone="13500135043",
        nickname="Detection remove outsider",
        password="progress-test-password",
    )
    outsider = APIClient()
    outsider.force_authenticate(other)

    assert (
        owner.delete(f"/api/v1/subjects/{uuid.uuid4()}/geo/detections/{job.pk}").status_code == 404
    )
    assert (
        outsider.delete(f"/api/v1/subjects/{subject.pk}/geo/detections/{job.pk}").status_code == 404
    )
    job.refresh_from_db()
    assert job.user_removed_at is None


def test_detection_history_is_server_paginated_at_twenty_items(geo_facts):
    user, subject, *_ = geo_facts
    created_ids = []
    for index in range(21):
        job, _ = _create(
            geo_facts,
            key=f"geo-history-page-{index}-{uuid.uuid4()}",
        )
        created_ids.append(str(job.pk))
        cancel_detection(user=user, detection_id=job.pk)
    client = APIClient()
    client.force_authenticate(user)

    first = client.get(f"/api/v1/subjects/{subject.pk}/geo/detections?page=1&page_size=100")
    second = client.get(f"/api/v1/subjects/{subject.pk}/geo/detections?page=2&page_size=20")

    assert first.status_code == 200
    assert len(first.json()["data"]["items"]) == 20
    assert first.json()["data"]["pagination"] == {
        "page": 1,
        "page_size": 20,
        "count": 21,
        "total_pages": 2,
    }
    assert second.status_code == 200
    assert len(second.json()["data"]["items"]) == 1
    assert second.json()["data"]["pagination"] == {
        "page": 2,
        "page_size": 20,
        "count": 21,
        "total_pages": 2,
    }
    returned_ids = [row["id"] for row in first.json()["data"]["items"]]
    returned_ids += [row["id"] for row in second.json()["data"]["items"]]
    assert set(returned_ids) == set(created_ids)
