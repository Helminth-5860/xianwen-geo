from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from apps.keywords.normalization import KeywordNormalizationError, normalize_plain_text

from .competitor_management import (
    active_competitors,
    subject_for_competitors,
    subject_version_for_competitors,
)
from .models import GeoReport, ModelCall, ScoreResult
from .scoring import MatchCandidate, find_subject_mention

_PERCENT_QUANTUM = Decimal("0.01")
_EXPLICIT_RECOMMENDATION_SCORES = frozenset({Decimal("75.0000"), Decimal("100.0000")})


@dataclass(frozen=True)
class CompetitorDefinition:
    id: UUID
    name: str
    normalized_name: str
    website: str
    website_domain: str
    position: int


@dataclass(frozen=True)
class ComparisonCallFact:
    call_id: UUID
    question_id: UUID
    source_question_id: UUID
    question: str
    question_sort_order: int
    model_key: str
    raw_text: str
    subject_mentioned: bool
    subject_recommendation_score: Decimal


def _percentage(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        raise ValueError("comparison percentage requires a positive denominator")
    value = (Decimal(numerator) * Decimal(100) / Decimal(denominator)).quantize(
        _PERCENT_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    return float(value)


def _blank_metrics() -> dict[str, int | float | None]:
    return {
        "mention_count": None,
        "mention_rate": None,
        "question_coverage_count": None,
        "question_coverage_rate": None,
        "shared_question_count": None,
        "gap_question_count": None,
        "recommendation_rate": None,
        "citation_count": None,
    }


def _subject_entity(*, subject_id: UUID, subject_name: str) -> dict[str, object]:
    return {
        "id": str(subject_id),
        "kind": "subject",
        "name": subject_name,
        "website": "",
        "metrics": _blank_metrics(),
    }


def _competitor_entity(competitor: CompetitorDefinition) -> dict[str, object]:
    return {
        "id": str(competitor.id),
        "kind": "competitor",
        "name": competitor.name,
        "website": competitor.website,
        "metrics": _blank_metrics(),
    }


def _base_payload(
    *,
    status: str,
    subject_id: UUID,
    subject_name: str,
    competitors: tuple[CompetitorDefinition, ...],
    report_id: UUID | None = None,
    detection_id: UUID | None = None,
    generated_at: datetime | None = None,
    valid_answer_count: int = 0,
    question_count: int = 0,
    entities: list[dict[str, object]] | None = None,
    opportunities: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "subject_id": str(subject_id),
        "subject_name": subject_name,
        "status": status,
        "competitor_count": len(competitors),
        "report_id": str(report_id) if report_id is not None else None,
        "detection_id": str(detection_id) if detection_id is not None else None,
        "generated_at": generated_at.isoformat() if generated_at is not None else None,
        "valid_answer_count": valid_answer_count,
        "question_count": question_count,
        "entities": entities or [],
        "opportunities": opportunities or [],
        "detail_url": f"/geo/reports/{report_id}" if report_id is not None else None,
    }


def _normalized_domain(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold().rstrip(".")
    if normalized.startswith("www."):
        normalized = normalized[4:]
    return normalized


def _match_candidates(competitor: CompetitorDefinition) -> tuple[MatchCandidate, ...]:
    normalized_domain = _normalized_domain(competitor.website_domain)
    try:
        _, normalized_name = normalize_plain_text(
            competitor.normalized_name or competitor.name,
            max_length=255,
        )
    except KeywordNormalizationError:
        normalized_name = ""

    # One-character names are too broad for deterministic full-text matching.
    # A configured domain still gives the competitor a precise, usable signal.
    if len(normalized_name) < 2 and not normalized_domain:
        return ()

    candidates: list[MatchCandidate] = []
    if len(normalized_name) >= 2:
        candidates.append(
            MatchCandidate(
                kind="competitor_name",
                display_value=competitor.name,
                matching_value=normalized_name,
                priority=0,
            )
        )
    if normalized_domain:
        candidates.append(
            MatchCandidate(
                kind="competitor_domain",
                display_value=competitor.website_domain,
                matching_value=normalized_domain,
                priority=1,
            )
        )
    return tuple(candidates)


def calculate_competitor_comparison(
    *,
    subject_id: UUID,
    subject_name: str,
    competitors: tuple[CompetitorDefinition, ...],
    report_id: UUID,
    detection_id: UUID,
    report_generated_at: datetime,
    calls: tuple[ComparisonCallFact, ...],
) -> dict[str, object]:
    """Build one deterministic comparison from an immutable detection report."""

    valid_question_ids = {item.question_id for item in calls}
    if not calls or not valid_question_ids:
        return _base_payload(
            status="no_detection_data",
            subject_id=subject_id,
            subject_name=subject_name,
            competitors=competitors,
            report_id=report_id,
            detection_id=detection_id,
            generated_at=report_generated_at,
        )

    question_meta: dict[UUID, ComparisonCallFact] = {}
    subject_call_ids: set[UUID] = set()
    subject_question_ids: set[UUID] = set()
    explicit_subject_recommendations = 0

    for item in calls:
        question_meta.setdefault(item.question_id, item)
        if not item.subject_mentioned:
            continue
        subject_call_ids.add(item.call_id)
        subject_question_ids.add(item.question_id)
        if item.subject_recommendation_score in _EXPLICIT_RECOMMENDATION_SCORES:
            explicit_subject_recommendations += 1

    competitor_call_ids: dict[UUID, set[UUID]] = {item.id: set() for item in competitors}
    competitor_question_ids: dict[UUID, set[UUID]] = {item.id: set() for item in competitors}
    candidates = {item.id: _match_candidates(item) for item in competitors}

    for call in calls:
        for competitor in competitors:
            entity_candidates = candidates[competitor.id]
            if not entity_candidates:
                continue
            if find_subject_mention(call.raw_text, entity_candidates) is None:
                continue
            competitor_call_ids[competitor.id].add(call.call_id)
            competitor_question_ids[competitor.id].add(call.question_id)

    subject_metrics: dict[str, int | float | None] = {
        "mention_count": len(subject_call_ids),
        "mention_rate": _percentage(len(subject_call_ids), len(calls)),
        "question_coverage_count": len(subject_question_ids),
        "question_coverage_rate": _percentage(len(subject_question_ids), len(valid_question_ids)),
        "shared_question_count": None,
        "gap_question_count": None,
        "recommendation_rate": (
            _percentage(explicit_subject_recommendations, len(subject_call_ids))
            if subject_call_ids
            else 0.0
        ),
        # Citations belong to a whole response and cannot be bound to one entity.
        "citation_count": None,
    }
    entities: list[dict[str, object]] = [
        {
            **_subject_entity(subject_id=subject_id, subject_name=subject_name),
            "metrics": subject_metrics,
        }
    ]

    for competitor in competitors:
        mention_calls = competitor_call_ids[competitor.id]
        mention_questions = competitor_question_ids[competitor.id]
        competitor_metrics: dict[str, int | float | None]
        if not candidates[competitor.id]:
            # A one-character name without an official domain cannot be matched
            # reliably. Preserve it in the managed list, but do not turn an
            # unverifiable identity into misleading zero-performance metrics.
            competitor_metrics = _blank_metrics()
        else:
            competitor_metrics = {
                "mention_count": len(mention_calls),
                "mention_rate": _percentage(len(mention_calls), len(calls)),
                "question_coverage_count": len(mention_questions),
                "question_coverage_rate": _percentage(
                    len(mention_questions), len(valid_question_ids)
                ),
                "shared_question_count": len(subject_question_ids & mention_questions),
                "gap_question_count": len(mention_questions - subject_question_ids),
                # Frozen recommendation/citation facts describe the subject
                # or whole response, never a configured competitor.
                "recommendation_rate": None,
                "citation_count": None,
            }
        entities.append(
            {
                **_competitor_entity(competitor),
                "metrics": competitor_metrics,
            }
        )

    opportunity_question_ids = set().union(
        *(competitor_question_ids[item.id] - subject_question_ids for item in competitors)
    )
    opportunities: list[dict[str, object]] = []
    for question_id in sorted(
        opportunity_question_ids,
        key=lambda value: (question_meta[value].question_sort_order, str(value)),
    ):
        question = question_meta[question_id]
        mentioned_competitors = [
            competitor
            for competitor in competitors
            if question_id in competitor_question_ids[competitor.id]
        ]
        opportunities.append(
            {
                "question_id": str(question.source_question_id),
                "question": question.question,
                "competitor_ids": [str(item.id) for item in mentioned_competitors],
                "competitor_names": [item.name for item in mentioned_competitors],
            }
        )

    return _base_payload(
        status="ready",
        subject_id=subject_id,
        subject_name=subject_name,
        competitors=competitors,
        report_id=report_id,
        detection_id=detection_id,
        generated_at=report_generated_at,
        valid_answer_count=len(calls),
        question_count=len(valid_question_ids),
        entities=entities,
        opportunities=opportunities,
    )


def _active_competitor_definitions(*, user, subject) -> tuple[CompetitorDefinition, ...]:
    rows = active_competitors(subject=subject)
    return tuple(
        CompetitorDefinition(
            id=row.pk,
            name=row.name,
            normalized_name=row.normalized_name,
            website=row.website,
            website_domain=row.website_domain,
            position=row.position,
        )
        for row in rows[:3]
    )


def _latest_report(*, user, subject_id: UUID) -> GeoReport | None:
    return (
        GeoReport.objects.filter(
            subject_id=subject_id,
            job__subject_id=subject_id,
            job__user_removed_at__isnull=True,
        )
        .select_related("job")
        .order_by("-generated_at", "-id")
        .first()
    )


def _call_facts(*, user, subject_id: UUID, report: GeoReport) -> tuple[ComparisonCallFact, ...]:
    calls = (
        ModelCall.objects.filter(
            job_id=report.job_id,
            job__subject_id=subject_id,
            job__user_removed_at__isnull=True,
            status=ModelCall.Status.SUCCEEDED,
            question_snapshot__participates_in_scoring=True,
            question_snapshot__question_type="natural",
            response__score_result__track=ScoreResult.Track.GEO,
        )
        .select_related(
            "question_snapshot",
            "response__score_result",
            "model_run__model",
        )
        .order_by(
            "question_snapshot__sort_order",
            "model_run__model__canonical_order",
            "id",
        )
    )
    return tuple(
        ComparisonCallFact(
            call_id=call.pk,
            question_id=call.question_snapshot_id,
            source_question_id=call.question_snapshot.source_question_id,
            question=call.question_snapshot.text,
            question_sort_order=call.question_snapshot.sort_order,
            model_key=call.model_key,
            raw_text=call.response.raw_text,
            subject_mentioned=call.response.score_result.mention_score == Decimal("100.0000"),
            subject_recommendation_score=call.response.score_result.recommendation_score,
        )
        for call in calls
    )


def competitor_comparison_payload(*, user, subject_id: UUID) -> dict[str, Any]:
    """Return the active subject's manual competitors and latest real comparison."""

    subject = subject_for_competitors(user=user, subject_id=subject_id)
    subject_name = subject_version_for_competitors(subject=subject).official_name
    competitors = _active_competitor_definitions(user=user, subject=subject)
    if not competitors:
        return _base_payload(
            status="no_competitors",
            subject_id=subject.pk,
            subject_name=subject_name,
            competitors=(),
        )

    report = _latest_report(user=user, subject_id=subject.pk)
    if report is None:
        return _base_payload(
            status="no_detection_data",
            subject_id=subject.pk,
            subject_name=subject_name,
            competitors=competitors,
        )

    return calculate_competitor_comparison(
        subject_id=subject.pk,
        subject_name=subject_name,
        competitors=competitors,
        report_id=report.pk,
        detection_id=report.job_id,
        report_generated_at=report.generated_at,
        calls=_call_facts(user=user, subject_id=subject.pk, report=report),
    )
