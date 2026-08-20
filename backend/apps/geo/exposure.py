from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, cast

from .models import GeoDetectionJob, ModelScoreResult, ScoreResult

EXPOSURE_DISCLAIMER = "曝光潜力指数是系统评估指数，不是实际曝光人数。"
EXPOSURE_RULE_VERSION = "geo-exposure-v1"
_QUANTUM = Decimal("0.0001")

ExposureStatus = Literal["formal", "reference"]


@dataclass(frozen=True)
class ExposureCallFact:
    model_run_id: object
    mention_score: Decimal
    recommendation_score: Decimal
    rank_score: Decimal


@dataclass(frozen=True)
class ExposureResult:
    mention_rate_score: Decimal
    recommendation_rate_score: Decimal
    ranking_performance_score: Decimal
    model_coverage_score: Decimal
    exposure_index: Decimal
    grade: str
    status: ExposureStatus
    successful_model_count: int
    formal_model_count: int
    scoring_rule_version: str = EXPOSURE_RULE_VERSION
    disclaimer: str = EXPOSURE_DISCLAIMER


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_UP)


def _percentage(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.0000")
    return _quantize(Decimal(numerator) * Decimal(100) / Decimal(denominator))


def exposure_grade(value: Decimal) -> str:
    if not Decimal(0) <= value <= Decimal(100):
        raise ValueError("exposure index must be from 0 to 100.")
    if value >= Decimal(90):
        return "极高"
    if value >= Decimal(75):
        return "高"
    if value >= Decimal(60):
        return "中"
    if value >= Decimal(40):
        return "较低"
    return "低"


def calculate_exposure(
    *,
    successful_natural_calls: tuple[ExposureCallFact, ...],
    successful_model_ids: frozenset[object],
    formal_geo_model_count: int,
) -> ExposureResult:
    if formal_geo_model_count < 0:
        raise ValueError("formal_geo_model_count cannot be negative.")
    mentioned = tuple(item for item in successful_natural_calls if item.mention_score == 100)
    for item in successful_natural_calls:
        if item.mention_score not in {Decimal(0), Decimal(100)}:
            raise ValueError("mention score must be a frozen 0 or 100 fact.")
        if not Decimal(0) <= item.recommendation_score <= Decimal(100):
            raise ValueError("recommendation score must be from 0 to 100.")
        if not Decimal(0) <= item.rank_score <= Decimal(100):
            raise ValueError("rank score must be from 0 to 100.")

    call_count = len(successful_natural_calls)
    mention_rate = _percentage(len(mentioned), call_count)
    explicit_recommendations = sum(
        item.recommendation_score in {Decimal(75), Decimal(100)} for item in mentioned
    )
    recommendation_rate = _percentage(explicit_recommendations, len(mentioned))
    ranking = (
        _quantize(
            sum(
                (item.rank_score if item.mention_score == 100 else Decimal(0))
                for item in successful_natural_calls
            )
            / Decimal(call_count)
        )
        if call_count
        else Decimal("0.0000")
    )
    covered_models = {item.model_run_id for item in mentioned} & successful_model_ids
    coverage = _percentage(len(covered_models), len(successful_model_ids))
    index = _quantize(
        mention_rate * Decimal("0.40")
        + recommendation_rate * Decimal("0.25")
        + ranking * Decimal("0.20")
        + coverage * Decimal("0.15")
    )
    return ExposureResult(
        mention_rate_score=mention_rate,
        recommendation_rate_score=recommendation_rate,
        ranking_performance_score=ranking,
        model_coverage_score=coverage,
        exposure_index=index,
        grade=exposure_grade(index),
        status="formal" if formal_geo_model_count >= 6 else "reference",
        successful_model_count=len(successful_model_ids),
        formal_model_count=formal_geo_model_count,
    )


def exposure_for_job(*, job: GeoDetectionJob) -> ExposureResult:
    successful_model_ids = frozenset(
        job.model_runs.filter(status="succeeded").values_list("id", flat=True)
    )
    scores = ScoreResult.objects.filter(
        model_response__model_call__job=job,
        model_response__model_call__status="succeeded",
        question_type="natural",
    ).values_list(
        "model_response__model_call__model_run_id",
        "mention_score",
        "recommendation_score",
        "rank_score",
    )
    facts = tuple(
        ExposureCallFact(
            model_run_id=model_run_id,
            mention_score=cast(Decimal, mention_score),
            recommendation_score=recommendation_score,
            rank_score=cast(Decimal, rank_score),
        )
        for model_run_id, mention_score, recommendation_score, rank_score in scores
    )
    formal_count = ModelScoreResult.objects.filter(
        model_run__job=job,
        track=ModelScoreResult.Track.GEO,
        status=ModelScoreResult.Status.FORMAL,
    ).count()
    return calculate_exposure(
        successful_natural_calls=facts,
        successful_model_ids=successful_model_ids,
        formal_geo_model_count=formal_count,
    )
