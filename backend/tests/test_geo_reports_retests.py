from __future__ import annotations

import hashlib
import uuid
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai.semantic_scoring import SEMANTIC_SCORING_SCHEMA_VERSION
from apps.geo.models import (
    DetectionRetest,
    GeoDetectionJob,
    GeoDetectionModelRun,
    GeoReport,
    ModelCall,
    ModelResponse,
    ReportExport,
    ScoreResult,
)
from apps.geo.reports import (
    comparison,
    execute_export,
    prepare_report,
    question_group_page,
    report_trends,
)
from apps.geo.retests import QuickRetestBlocked, create_adjusted_retest, create_quick_retest
from apps.questions.bank_models import Question, QuestionBankVersion, QuestionBankWorkspace
from apps.quotas.models import QuotaAccount, QuotaHoldGroup
from apps.subjects.models import SubjectName, SubjectProduct, SubjectVersion
from tests.test_geo_detection import _create, _SuccessAdapter
from tests.test_geo_detection import geo_facts as geo_facts_fixture

pytestmark = pytest.mark.django_db


@pytest.fixture
def report_facts(monkeypatch):
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)
    facts = geo_facts_fixture.__wrapped__(monkeypatch)
    job, _ = _create(facts, key=f"geo-report-baseline-{uuid.uuid4()}")
    _complete_scoring(job)
    report = prepare_report(job=job)
    assert report is not None
    return (*facts, job, report)


def _complete_scoring(job: GeoDetectionJob) -> None:
    now = timezone.now()
    for index, call in enumerate(job.model_calls.select_related("question_snapshot"), start=1):
        response = ModelResponse.objects.create(
            model_call=call,
            provider_model_id=call.provider_model_id,
            raw_text=f"完整回答 {index}，包含可供报告懒加载的稳定事实。",
            raw_text_sha256=hashlib.sha256(f"answer-{call.pk}".encode()).hexdigest(),
            provider_metadata={},
        )
        natural = call.question_snapshot.question_type == "natural"
        ScoreResult.objects.create(
            model_response=response,
            question_type=call.question_snapshot.question_type,
            track="geo" if natural else "brand_reputation",
            mention_score=Decimal("100.0000") if natural else None,
            recommendation_score=Decimal("75.0000"),
            rank_score=Decimal("80.0000") if natural else None,
            accuracy_score=Decimal("75.0000"),
            sentiment_score=Decimal("50.0000"),
            citation_score=Decimal("20.0000"),
            total_score=Decimal("72.5000"),
            scoring_rule_version=job.snapshot.scoring_rule_version,
            semantic_schema_version=SEMANTIC_SCORING_SCHEMA_VERSION,
            semantic_provider_key="deepseek",
            semantic_model_key="deepseek",
            semantic_adapter_version="semantic-test-v1",
            semantic_prompt_version="semantic-prompt-v1",
            semantic_provider_model_id="deepseek-chat",
            semantic_output_digest=hashlib.sha256(f"semantic-{call.pk}".encode()).hexdigest(),
            evidence={
                "semantic": {
                    "schema_version": SEMANTIC_SCORING_SCHEMA_VERSION,
                    "competitors": [],
                }
            },
        )
        ModelCall.objects.filter(pk=call.pk).update(
            status=ModelCall.Status.SUCCEEDED,
            settlement_status=ModelCall.Settlement.CONSUMED,
            finished_at=now,
        )
    for run in job.model_runs.all():
        GeoDetectionModelRun.objects.filter(pk=run.pk).update(
            status=GeoDetectionModelRun.Status.SUCCEEDED,
            completed_calls=run.planned_calls,
            successful_calls=run.planned_calls,
            failed_calls=0,
            cancelled_calls=0,
        )
    GeoDetectionJob.objects.filter(pk=job.pk).update(
        status=GeoDetectionJob.Status.SUCCEEDED,
        completed_calls=job.planned_detection_points,
        successful_calls=job.planned_detection_points,
        failed_calls=0,
        cancelled_calls=0,
        finished_at=now,
    )
    job.refresh_from_db()


def _quick(report: GeoReport, *, key: str | None = None):
    with (
        patch("apps.geo.retests._credential_configured", return_value=True),
        patch("apps.geo.retests.model_registry.resolve", return_value=_SuccessAdapter()),
    ):
        return create_quick_retest(
            user_id=report.user_id,
            baseline_report_id=report.pk,
            idempotency_key=key or f"quick-retest-{uuid.uuid4()}",
            request_id=uuid.uuid4(),
        )


def _adjusted(report: GeoReport, *, question_ids, model_ids, key: str):
    with (
        patch("apps.geo.services._credential_configured", return_value=True),
        patch("apps.geo.services.model_registry.resolve", return_value=_SuccessAdapter()),
    ):
        return create_adjusted_retest(
            user_id=report.user_id,
            baseline_report_id=report.pk,
            question_ids=question_ids,
            model_ids=model_ids,
            idempotency_key=key,
            request_id=uuid.uuid4(),
        )


def _change_current_question_bank(user, subject) -> QuestionBankVersion:
    workspace = QuestionBankWorkspace.objects.select_related(
        "current_version__distillation_set"
    ).get(subject=subject)
    old_version = workspace.current_version
    assert old_version is not None
    old_question = old_version.questions.order_by("sort_order", "id").first()
    assert old_question is not None
    new_version = QuestionBankVersion.objects.create(
        workspace=workspace,
        user=user,
        subject=subject,
        subject_version=subject.current_version,
        distillation_set=old_version.distillation_set,
        version_no=old_version.version_no + 1,
        content_digest=hashlib.sha256(b"changed-current-question-bank").hexdigest(),
        item_count=1,
        confirmed_by=user,
        confirmed_at=timezone.now(),
    )
    Question.objects.create(
        question_bank_version=new_version,
        text="这是当前题库中全新的问题，历史问题不再属于当前版本？",
        matching_text="这是当前题库中全新的问题，历史问题不再属于当前版本?",
        primary_category=old_question.primary_category,
        primary_category_key=old_question.primary_category_key,
        primary_category_name=old_question.primary_category_name,
        primary_category_version=old_question.primary_category_version,
        priority=old_question.priority,
        question_type=old_question.question_type,
        participates_in_scoring=True,
        sort_order=0,
    )
    workspace.current_version = new_version
    workspace.version += 1
    workspace.save(update_fields=("current_version", "version", "updated_at"))
    return new_version


def _advance_subject_version(subject, user) -> SubjectVersion:
    old = subject.current_version
    assert old is not None
    current = SubjectVersion.objects.create(
        subject=subject,
        version_no=old.version_no + 1,
        field_values=deepcopy(old.field_values),
        schema_version=old.schema_version,
        schema_snapshot_format_version=old.schema_snapshot_format_version,
        schema_snapshot=deepcopy(old.schema_snapshot),
        schema_digest=old.schema_digest,
        field_values_digest=old.field_values_digest,
        semantic_digest=old.semantic_digest,
        official_name=old.official_name,
        created_by=user,
    )
    SubjectName.objects.bulk_create(
        [
            SubjectName(
                subject_version=current,
                role=row.role,
                display_value=row.display_value,
                matching_value=row.matching_value,
                source_field_key=row.source_field_key,
            )
            for row in old.names.all()
        ]
    )
    SubjectProduct.objects.bulk_create(
        [
            SubjectProduct(
                subject_version=current,
                candidate_key=row.candidate_key,
                display_value=row.display_value,
                matching_value=row.matching_value,
                source_field_key=row.source_field_key,
                uniqueness_confirmed=row.uniqueness_confirmed,
                include_in_mention=row.include_in_mention,
            )
            for row in old.products.all()
        ]
    )
    subject.current_version = current
    subject.version += 1
    subject.retest_required = True
    subject.save(update_fields=("current_version", "version", "retest_required", "updated_at"))
    return current


def test_quick_retest_reuses_historical_frozen_questions_after_current_bank_changes(
    report_facts,
):
    user, subject, _, _, _, _, baseline = report_facts
    current_bank = _change_current_question_bank(user, subject)

    retest, created = _quick(baseline)

    assert created is True
    assert (
        retest.snapshot.question_bank_version_id == baseline.job.snapshot.question_bank_version_id
    )
    assert retest.snapshot.question_bank_version_id != current_bank.pk
    baseline_rows = list(
        baseline.job.snapshot.questions.values_list(
            "source_question_id", "text", "question_type", "sort_order"
        )
    )
    retest_rows = list(
        retest.snapshot.questions.values_list(
            "source_question_id", "text", "question_type", "sort_order"
        )
    )
    assert retest_rows == baseline_rows
    assert not current_bank.questions.filter(pk__in=[row[0] for row in baseline_rows]).exists()


def test_quick_retest_uses_current_subject_version_and_remains_fact_comparable(report_facts):
    user, subject, _, _, _, _, baseline = report_facts
    current_version = _advance_subject_version(subject, user)
    retest, _ = _quick(baseline)

    assert retest.snapshot.subject_version_id == current_version.pk
    assert retest.snapshot.subject_version_id != baseline.subject_version_id
    _complete_scoring(retest)
    current = prepare_report(job=retest)
    assert current is not None
    facts = comparison(current, baseline)
    assert facts is not None
    assert facts["status"] == "comparable"
    assert facts["subject_version_changed"] is True
    assert facts["geo_score_delta"] == "0.0000"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("not_entitled", "model_not_entitled"),
        ("paused", "model_paused"),
        ("disabled", "model_disabled"),
    ],
)
def test_quick_retest_model_preflight_fails_atomically(report_facts, change, reason, monkeypatch):
    _, _, subscription, runtime, _, _, baseline = report_facts
    if change == "not_entitled":
        monkeypatch.setattr("apps.geo.retests._model_permissions", lambda _subscription: [])
    else:
        runtime.paused = change == "paused"
        runtime.pause_reason = "maintenance" if runtime.paused else ""
        runtime.enabled = change != "disabled"
        runtime.version += 1
        runtime.save()
    account = QuotaAccount.objects.get(
        subscription=subscription, quota_type="detection_points", subject__isnull=True
    )
    before = {
        "jobs": GeoDetectionJob.objects.count(),
        "runs": GeoDetectionModelRun.objects.count(),
        "holds": QuotaHoldGroup.objects.count(),
        "available": account.available,
        "frozen": account.frozen,
    }

    with pytest.raises(QuickRetestBlocked) as caught:
        _quick(baseline)

    account.refresh_from_db()
    assert caught.value.model_key == baseline.provenance["models"][0]["model_key"]
    assert caught.value.reason == reason
    assert GeoDetectionJob.objects.count() == before["jobs"]
    assert GeoDetectionModelRun.objects.count() == before["runs"]
    assert QuotaHoldGroup.objects.count() == before["holds"]
    assert (account.available, account.frozen) == (before["available"], before["frozen"])


def test_quick_retest_keeps_exact_logical_model_set_without_substitution(report_facts):
    *_, baseline = report_facts
    retest, _ = _quick(baseline)
    assert list(retest.model_runs.values_list("model_id", "model_key")) == [
        (uuid.UUID(row["model_id"]), row["model_key"]) for row in baseline.provenance["models"]
    ]


def test_scoring_rule_change_keeps_report_but_suppresses_formal_deltas(report_facts):
    *_, baseline = report_facts
    with patch("apps.geo.retests.GEO_SCORING_RULE_VERSION", "geo-scoring-v2"):
        retest, _ = _quick(baseline)
    _complete_scoring(retest)
    current = prepare_report(job=retest)
    assert current is not None
    facts = comparison(current, baseline)
    assert facts is not None
    assert facts["status"] == "not_comparable"
    assert facts["scoring_version_changed"] is True
    assert facts["geo_score_delta"] is None
    assert facts["dimension_deltas"] == {}


def test_adjusted_retests_are_independent_and_comparability_uses_facts(report_facts):
    user, _, _, runtime, questions, _, baseline = report_facts
    different_job, created = _adjusted(
        baseline,
        question_ids=[questions[0].pk],
        model_ids=[runtime.model_id],
        key=f"adjusted-different-{uuid.uuid4()}",
    )
    assert created is True
    _complete_scoring(different_job)
    different = prepare_report(job=different_job)
    assert different is not None
    assert different.pk != baseline.pk
    assert comparison(different, baseline)["status"] == "not_comparable"

    same_job, created = _adjusted(
        baseline,
        question_ids=[question.pk for question in questions],
        model_ids=[runtime.model_id],
        key=f"adjusted-same-{uuid.uuid4()}",
    )
    assert created is True
    _complete_scoring(same_job)
    same = prepare_report(job=same_job)
    assert same is not None
    assert same.retest_mode == DetectionRetest.Mode.ADJUSTED
    assert comparison(same, baseline)["status"] == "comparable"


def test_report_read_model_lazy_details_history_trends_exports_and_permissions(report_facts):
    user, _, _, _, _, _, report = report_facts
    payload = question_group_page(report=report, page=1)
    assert payload["pagination"]["page_size"] == 10
    assert payload["results"][0]["results"][0]["snippet"].startswith("完整回答")
    assert "answer" not in payload["results"][0]["results"][0]
    assert set(report.summary["dimensions"]) == {
        "mention",
        "recommendation",
        "rank",
        "accuracy",
        "sentiment",
        "citation",
    }
    assert report_trends(user=user, subject_id=report.subject_id)[0]["report_id"] == str(report.pk)
    with pytest.raises(TypeError):
        report.save()

    for export_format, prefix in (("pdf", b"%PDF"), ("word", b"PK"), ("excel", b"PK")):
        export = ReportExport.objects.create(
            report=report,
            user=user,
            format=export_format,
            brand_snapshot={"brand_name": "显问 GEO"},
        )
        with patch("apps.geo.reports.storage_provider") as provider:
            execute_export(export_id=export.pk)
        export.refresh_from_db()
        assert export.status == ReportExport.Status.SUCCEEDED
        stored = provider.return_value.put_system_object.call_args.kwargs["data"]
        assert stored.startswith(prefix)

    client = APIClient()
    client.force_authenticate(user)
    assert client.get(f"/api/v1/geo/reports/{report.pk}").status_code == 200
    answer_call = report.job.model_calls.first()
    assert answer_call is not None
    answer = client.get(f"/api/v1/geo/reports/{report.pk}/answers/{answer_call.pk}")
    assert answer.status_code == 200
    assert answer.json()["data"]["answer"].startswith("完整回答")

    other = user.__class__.objects.create_user(
        phone=f"138{uuid.uuid4().int % 100000000:08d}",
        nickname="Other",
        password="Other-user-password-1!",
    )
    other.account_status = other.AccountStatus.ACTIVE
    other.save(update_fields=("account_status", "updated_at"))
    client.force_authenticate(other)
    assert client.get(f"/api/v1/geo/reports/{report.pk}").status_code == 404


def test_quick_retest_api_returns_machine_readable_blocking_model_reason(report_facts):
    user, _, _, runtime, _, _, report = report_facts
    runtime.paused = True
    runtime.pause_reason = "maintenance"
    runtime.version += 1
    runtime.save(update_fields=("paused", "pause_reason", "version", "updated_at"))
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(
        f"/api/v1/geo/reports/{report.pk}/quick-retest",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"quick-blocked-{uuid.uuid4()}",
    )
    assert response.status_code == 409
    assert (
        response.json()["error"]["details"]
        | {
            "model_key": runtime.model.model_key,
            "reason": "model_paused",
        }
        == response.json()["error"]["details"]
    )
    assert "use_adjusted_retest" in response.json()["error"]["details"]["suggested_actions"]


def test_standard_report_endpoints_and_unified_quick_retest_flow(
    report_facts, django_capture_on_commit_callbacks
):
    user, _, _, _, _, job, report = report_facts
    client = APIClient()
    client.force_authenticate(user)

    assert client.get(f"/api/v1/geo/detections/{job.pk}/report").json()["data"]["id"] == str(
        report.pk
    )
    question = report.job.snapshot.questions.order_by("sort_order", "id").first()
    call = report.job.model_calls.order_by("id").first()
    assert question is not None and call is not None
    assert client.get(f"/api/v1/geo/reports/{report.pk}/questions").status_code == 200
    assert client.get(f"/api/v1/geo/reports/{report.pk}/questions/{question.pk}").status_code == 200
    assert client.get(f"/api/v1/geo/model-calls/{call.pk}/response").status_code == 200
    assert client.get(f"/api/v1/subjects/{report.subject_id}/geo/reports").status_code == 200
    assert client.get(f"/api/v1/subjects/{report.subject_id}/geo/trends").status_code == 200

    with (
        patch("apps.geo.retests._credential_configured", return_value=True),
        patch("apps.geo.retests.model_registry.resolve", return_value=_SuccessAdapter()),
        patch("apps.geo.views.dispatch_model_calls_task.apply_async") as dispatch,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = client.post(
            f"/api/v1/geo/reports/{report.pk}/retest",
            {"mode": "quick"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"unified-quick-{uuid.uuid4()}",
        )
    assert response.status_code == 202
    created_id = response.json()["data"]["detection_id"]
    assert GeoDetectionJob.objects.filter(pk=created_id).exists()
    dispatch.assert_called_once()


def test_postgresql_report_retest_and_export_history_guards(report_facts):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-specific report history evidence")
    user, _, _, _, _, _, report = report_facts
    retest_job, _ = _quick(report)
    retest = DetectionRetest.objects.get(job=retest_job)
    export = ReportExport.objects.create(report=report, user=user, format="pdf")

    for table, row_id in (
        ("geo_reports", report.pk),
        ("geo_detection_retests", retest.pk),
    ):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"UPDATE {table} SET id = id WHERE id = %s", [row_id])
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table} WHERE id = %s", [row_id])

    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM report_exports WHERE id = %s", [export.pk])
