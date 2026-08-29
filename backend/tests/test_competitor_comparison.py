from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.http import Http404
from django.utils import timezone

from apps.ai.semantic_scoring import SEMANTIC_SCORING_SCHEMA_VERSION
from apps.geo.competitor_comparison import (
    ComparisonCallFact,
    CompetitorDefinition,
    calculate_competitor_comparison,
    competitor_comparison_payload,
)
from apps.geo.models import (
    GeoReport,
    ModelCall,
    ModelResponse,
    ScoreResult,
    SubjectCompetitor,
)
from apps.users.models import Tenant, User
from tests.test_geo_detection import _create, _mark_job_terminal
from tests.test_geo_detection import geo_facts as geo_facts_fixture

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture
def geo_facts(monkeypatch):
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)
    return geo_facts_fixture.__wrapped__(monkeypatch)


def _competitor(name: str, *, position: int, domain: str = "") -> CompetitorDefinition:
    return CompetitorDefinition(
        id=uuid.uuid4(),
        name=name,
        normalized_name=name.casefold(),
        website=f"https://{domain}" if domain else "",
        website_domain=domain,
        position=position,
    )


def _fact(
    *,
    question_no: int,
    call_no: int,
    raw_text: str,
    subject_mentioned: bool,
    recommendation_score: str = "50.0000",
) -> ComparisonCallFact:
    return ComparisonCallFact(
        call_id=uuid.UUID(int=call_no),
        question_id=uuid.UUID(int=100 + question_no),
        source_question_id=uuid.UUID(int=200 + question_no),
        question=f"问题 {question_no}",
        question_sort_order=question_no,
        model_key=f"model-{call_no}",
        raw_text=raw_text,
        subject_mentioned=subject_mentioned,
        subject_recommendation_score=Decimal(recommendation_score),
    )


def test_six_metrics_keep_answer_counts_and_question_coverage_distinct() -> None:
    competitor_a = _competitor("甲品牌", position=1)
    competitor_b = _competitor("乙品牌", position=2)
    calls = (
        _fact(
            question_no=1,
            call_no=1,
            raw_text="当前主体和甲品牌都值得关注。",
            subject_mentioned=True,
            recommendation_score="75.0000",
        ),
        _fact(
            question_no=1,
            call_no=2,
            raw_text="没有出现已设置的竞品。",
            subject_mentioned=False,
        ),
        _fact(
            question_no=2,
            call_no=3,
            raw_text="甲品牌和乙品牌提供了相关方案。",
            subject_mentioned=False,
        ),
        _fact(
            question_no=2,
            call_no=4,
            raw_text="本回答没有品牌信息。",
            subject_mentioned=False,
        ),
        _fact(
            question_no=3,
            call_no=5,
            raw_text="当前主体与乙品牌共同出现。",
            subject_mentioned=True,
            recommendation_score="100.0000",
        ),
        _fact(
            question_no=3,
            call_no=6,
            raw_text="当前主体继续出现。",
            subject_mentioned=True,
            recommendation_score="25.0000",
        ),
    )

    subject_id = uuid.uuid4()
    report_id = uuid.uuid4()
    detection_id = uuid.uuid4()
    payload = calculate_competitor_comparison(
        subject_id=subject_id,
        subject_name="当前主体",
        competitors=(competitor_a, competitor_b),
        report_id=report_id,
        detection_id=detection_id,
        report_generated_at=datetime(2026, 8, 29, tzinfo=UTC),
        calls=calls,
    )

    assert payload["status"] == "ready"
    assert set(payload) == {
        "subject_id",
        "subject_name",
        "status",
        "competitor_count",
        "report_id",
        "detection_id",
        "generated_at",
        "valid_answer_count",
        "question_count",
        "entities",
        "opportunities",
        "detail_url",
    }
    assert payload["subject_id"] == str(subject_id)
    assert payload["subject_name"] == "当前主体"
    assert payload["competitor_count"] == 2
    assert payload["report_id"] == str(report_id)
    assert payload["detection_id"] == str(detection_id)
    assert payload["generated_at"] == "2026-08-29T00:00:00+00:00"
    assert payload["valid_answer_count"] == 6
    assert payload["question_count"] == 3
    assert payload["detail_url"] == f"/geo/reports/{report_id}"
    by_name = {row["name"]: row["metrics"] for row in payload["entities"]}
    assert by_name["当前主体"] == {
        "mention_count": 3,
        "mention_rate": 50.0,
        "question_coverage_count": 2,
        "question_coverage_rate": 66.67,
        "shared_question_count": None,
        "gap_question_count": None,
        "recommendation_rate": 66.67,
        "citation_count": None,
    }
    assert by_name["甲品牌"]["mention_count"] == 2
    assert by_name["甲品牌"]["question_coverage_count"] == 2
    assert by_name["甲品牌"]["shared_question_count"] == 1
    assert by_name["甲品牌"]["gap_question_count"] == 1
    assert by_name["乙品牌"]["mention_count"] == 2
    assert by_name["乙品牌"]["shared_question_count"] == 1
    assert by_name["乙品牌"]["gap_question_count"] == 1
    assert len(payload["opportunities"]) == 1
    assert payload["opportunities"][0] == {
        "question_id": str(uuid.UUID(int=202)),
        "question": "问题 2",
        "competitor_ids": [str(competitor_a.id), str(competitor_b.id)],
        "competitor_names": ["甲品牌", "乙品牌"],
    }


def test_competitor_matching_normalizes_full_width_case_and_domain_without_embedded_token() -> None:
    acme = _competitor("ACME", position=1, domain="example.com")
    calls = (
        _fact(
            question_no=1,
            call_no=1,
            raw_text="ＡＣＭＥ2 不是 ACME 的独立词边界。",
            subject_mentioned=False,
        ),
        _fact(
            question_no=2,
            call_no=2,
            raw_text="可查看 https://www.example.com/path 获取资料。",
            subject_mentioned=False,
        ),
    )

    payload = calculate_competitor_comparison(
        subject_id=uuid.uuid4(),
        subject_name="当前主体",
        competitors=(acme,),
        report_id=uuid.uuid4(),
        detection_id=uuid.uuid4(),
        report_generated_at=datetime(2026, 8, 29, tzinfo=UTC),
        calls=calls,
    )

    metrics = payload["entities"][1]["metrics"]
    # The first answer contains one valid standalone ACME after the embedded
    # full-width ACME2 token; the second is matched by its exact official domain.
    assert metrics["mention_count"] == 2
    assert metrics["question_coverage_count"] == 2


def test_one_character_name_only_matches_when_a_precise_domain_is_present() -> None:
    name_only = _competitor("甲", position=1)
    domain_backed = _competitor("乙", position=2, domain="rival.example.com")
    payload = calculate_competitor_comparison(
        subject_id=uuid.uuid4(),
        subject_name="当前主体",
        competitors=(name_only, domain_backed),
        report_id=uuid.uuid4(),
        detection_id=uuid.uuid4(),
        report_generated_at=datetime(2026, 8, 29, tzinfo=UTC),
        calls=(
            _fact(
                question_no=1,
                call_no=1,
                raw_text="甲乙都只是句子里的普通单字。",
                subject_mentioned=False,
            ),
            _fact(
                question_no=2,
                call_no=2,
                raw_text="详情见 https://rival.example.com/about。",
                subject_mentioned=False,
            ),
        ),
    )

    by_name = {row["name"]: row["metrics"] for row in payload["entities"]}
    assert by_name["甲"] == {
        "mention_count": None,
        "mention_rate": None,
        "question_coverage_count": None,
        "question_coverage_rate": None,
        "shared_question_count": None,
        "gap_question_count": None,
        "recommendation_rate": None,
        "citation_count": None,
    }
    assert by_name["乙"]["mention_count"] == 1


def test_zero_valid_calls_is_no_detection_data_instead_of_fake_zero_metrics() -> None:
    report_id = uuid.uuid4()
    detection_id = uuid.uuid4()
    payload = calculate_competitor_comparison(
        subject_id=uuid.uuid4(),
        subject_name="当前主体",
        competitors=(_competitor("甲品牌", position=1),),
        report_id=report_id,
        detection_id=detection_id,
        report_generated_at=datetime(2026, 8, 29, tzinfo=UTC),
        calls=(),
    )

    assert payload["status"] == "no_detection_data"
    assert payload["report_id"] == str(report_id)
    assert payload["detection_id"] == str(detection_id)
    assert payload["valid_answer_count"] == 0
    assert payload["question_count"] == 0
    assert payload["entities"] == []
    assert payload["opportunities"] == []


def _managed_competitor(user, subject, *, name: str, position: int, status="active"):
    return SubjectCompetitor.objects.create(
        user=user,
        tenant=user.tenant,
        subject=subject,
        name=name,
        normalized_name=name.casefold(),
        website=f"https://{name.casefold()}.example.com",
        website_domain=f"{name.casefold()}.example.com",
        source="manual",
        position=position,
        status=status,
        removed_at=timezone.now() if status == "removed" else None,
    )


def test_one_and_three_competitors_load_but_without_report_show_no_data(geo_facts) -> None:
    user, subject, *_ = geo_facts
    _managed_competitor(user, subject, name="甲", position=1)

    one = competitor_comparison_payload(user=user, subject_id=subject.pk)

    assert one["status"] == "no_detection_data"
    assert one["competitor_count"] == 1
    assert one["report_id"] is None
    assert one["entities"] == []
    _managed_competitor(user, subject, name="乙", position=2)
    _managed_competitor(user, subject, name="丙", position=3)

    three = competitor_comparison_payload(user=user, subject_id=subject.pk)

    assert three["status"] == "no_detection_data"
    assert three["competitor_count"] == 3
    assert three["entities"] == []


def test_removed_competitor_is_synchronously_excluded(geo_facts) -> None:
    user, subject, *_ = geo_facts
    competitor = _managed_competitor(user, subject, name="甲", position=1)
    assert competitor_comparison_payload(user=user, subject_id=subject.pk)["competitor_count"] == 1

    SubjectCompetitor.objects.filter(pk=competitor.pk).update(
        status="removed",
        removed_at=timezone.now(),
        version=competitor.version + 1,
    )

    payload = competitor_comparison_payload(user=user, subject_id=subject.pk)
    assert payload["status"] == "no_competitors"
    assert payload["competitor_count"] == 0
    assert payload["entities"] == []


def test_other_tenant_cannot_read_subject_comparison(geo_facts) -> None:
    owner, subject, *_ = geo_facts
    owner_tenant = Tenant.objects.create(key=f"owner-{uuid.uuid4().hex}", display_name="甲租户")
    other_tenant = Tenant.objects.create(key=f"other-{uuid.uuid4().hex}", display_name="乙租户")
    owner.tenant = owner_tenant
    owner.save(update_fields=("tenant", "updated_at"))
    _managed_competitor(owner, subject, name="甲", position=1)
    outsider = User.objects.create_user(
        phone=f"138{uuid.uuid4().int % 100000000:08d}",
        nickname="其他租户用户",
        password=PASSWORD,
        tenant=other_tenant,
    )

    with pytest.raises(Http404):
        competitor_comparison_payload(user=outsider, subject_id=subject.pk)


def _score_response(call: ModelCall, *, raw_text: str, subject_mentioned: bool) -> None:
    response = ModelResponse.objects.create(
        model_call=call,
        provider_model_id=call.provider_model_id,
        raw_text=raw_text,
        raw_text_sha256=hashlib.sha256(raw_text.encode()).hexdigest(),
        provider_metadata={},
    )
    ScoreResult.objects.create(
        model_response=response,
        question_type="natural",
        track="geo",
        mention_score=Decimal("100.0000" if subject_mentioned else "0.0000"),
        recommendation_score=Decimal("75.0000"),
        rank_score=Decimal("80.0000" if subject_mentioned else "0.0000"),
        accuracy_score=Decimal("75.0000"),
        sentiment_score=Decimal("50.0000"),
        citation_score=Decimal("0.0000"),
        total_score=Decimal("75.0000" if subject_mentioned else "0.0000"),
        scoring_rule_version=call.job.snapshot.scoring_rule_version,
        semantic_schema_version=SEMANTIC_SCORING_SCHEMA_VERSION,
        semantic_provider_key="deepseek",
        semantic_model_key="deepseek",
        semantic_adapter_version="semantic-test-v1",
        semantic_prompt_version="semantic-prompt-v1",
        semantic_provider_model_id="deepseek-chat",
        semantic_output_digest=hashlib.sha256(f"semantic-{call.pk}".encode()).hexdigest(),
        evidence={"semantic": {"schema_version": SEMANTIC_SCORING_SCHEMA_VERSION}},
    )
    ModelCall.objects.filter(pk=call.pk).update(
        status=ModelCall.Status.SUCCEEDED,
        settlement_status=ModelCall.Settlement.CONSUMED,
        finished_at=timezone.now(),
    )


def test_latest_real_report_drives_ready_payload(geo_facts) -> None:
    user, subject, *_ = geo_facts
    _managed_competitor(user, subject, name="甲公司", position=1)
    _managed_competitor(user, subject, name="乙公司", position=2)
    job, _ = _create(geo_facts, key=f"comparison-{uuid.uuid4()}")
    calls = list(job.model_calls.order_by("question_snapshot__sort_order", "id"))
    assert len(calls) == 2
    natural_call = next(call for call in calls if call.question_snapshot.question_type == "natural")
    _score_response(
        natural_call,
        raw_text="示例企业和甲公司都在回答中出现。",
        subject_mentioned=True,
    )
    report = GeoReport.objects.create(
        job=job,
        user=user,
        subject=subject,
        subject_version=job.snapshot.subject_version,
        question_signature="q" * 64,
        model_signature="m" * 64,
        scoring_rule_version=job.snapshot.scoring_rule_version,
        summary={},
        provenance={},
    )

    payload = competitor_comparison_payload(user=user, subject_id=subject.pk)

    assert payload["status"] == "ready"
    assert payload["report_id"] == str(report.pk)
    assert payload["detection_id"] == str(job.pk)
    assert payload["valid_answer_count"] == 1
    assert payload["question_count"] == 1
    assert payload["detail_url"] == f"/geo/reports/{report.pk}"
    by_name = {row["name"]: row["metrics"] for row in payload["entities"]}
    assert by_name["示例企业"]["mention_count"] == 1
    assert by_name["甲公司"]["shared_question_count"] == 1
    assert by_name["乙公司"]["mention_count"] == 0
    assert payload["opportunities"] == []


def test_user_removed_detection_report_is_not_used(geo_facts) -> None:
    user, subject, *_ = geo_facts
    _managed_competitor(user, subject, name="甲公司", position=1)
    job, _ = _create(geo_facts, key=f"removed-comparison-{uuid.uuid4()}")
    natural_call = next(
        call
        for call in job.model_calls.order_by("question_snapshot__sort_order", "id")
        if call.question_snapshot.question_type == "natural"
    )
    _score_response(
        natural_call,
        raw_text="示例企业和甲公司都在回答中出现。",
        subject_mentioned=True,
    )
    GeoReport.objects.create(
        job=job,
        user=user,
        subject=subject,
        subject_version=job.snapshot.subject_version,
        question_signature="r" * 64,
        model_signature="m" * 64,
        scoring_rule_version=job.snapshot.scoring_rule_version,
        summary={},
        provenance={},
    )
    _mark_job_terminal(job, type(job).Status.SUCCEEDED)
    type(job).objects.filter(pk=job.pk).update(user_removed_at=timezone.now())

    payload = competitor_comparison_payload(user=user, subject_id=subject.pk)

    assert payload["status"] == "no_detection_data"
    assert payload["report_id"] is None
    assert payload["detection_id"] is None
