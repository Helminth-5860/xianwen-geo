from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

SCORE_QUANTUM = Decimal("0.0001")
FORMAL_MODEL_SUCCESS_RATE = Decimal("80.0000")
FORMAL_COMPOSITE_MODEL_COUNT = 6
MAX_DETECTION_MODELS = 8

NATURAL_WEIGHTS = {
    "mention": Decimal("0.25"),
    "recommendation": Decimal("0.20"),
    "rank": Decimal("0.15"),
    "accuracy": Decimal("0.20"),
    "sentiment": Decimal("0.10"),
    "citation": Decimal("0.10"),
}
BRAND_RAW_WEIGHTS = {
    "recommendation": Decimal("20"),
    "accuracy": Decimal("20"),
    "sentiment": Decimal("10"),
    "citation": Decimal("10"),
}
BRAND_WEIGHT_TOTAL = sum(BRAND_RAW_WEIGHTS.values(), Decimal("0"))

RECOMMENDATION_SCORES = {
    "strong_recommendation": 100,
    "recommendation": 75,
    "neutral": 40,
    "discouraged": 0,
    "strongly_discouraged": 0,
}
ACCURACY_SCORES = frozenset({0, 40, 75, 100})
SENTIMENT_SCORES = frozenset({0, 25, 50, 75, 100})
SOURCE_CLASSIFICATION_SCORES = {
    "subject_official": 100,
    "government": 100,
    "authoritative_industry": 100,
    "mainstream_media": 80,
    "vertical_authority": 80,
    "ordinary_website": 50,
    "self_media": 50,
    "unverifiable": 20,
}

QuestionType = Literal["natural", "brand_directed"]
Track = Literal["geo", "brand_reputation"]
ModelScoreStatus = Literal["formal", "reference", "not_generated"]
CompositeScoreStatus = Literal["formal", "reference", "failed"]
ScoreGrade = Literal["卓越", "优秀", "一般", "较弱", "薄弱"]


class ScoreAggregationError(ValueError):
    pass


@dataclass(frozen=True)
class QuestionAggregationInput:
    question_type: QuestionType
    mention_score: int | None
    rank_score: int | None
    rank_resolution: str
    citation_base_score: int | None
    citation_resolution: str
    recommendation_level: str
    semantic_recommendation_score: int
    accuracy_score: int
    sentiment_score: int
    auxiliary_rank_position: int | None
    source_classifications: tuple[str, ...]


@dataclass(frozen=True)
class QuestionScore:
    question_type: QuestionType
    track: Track
    mention_score: Decimal | None
    recommendation_score: Decimal
    rank_score: Decimal | None
    accuracy_score: Decimal
    sentiment_score: Decimal
    citation_score: Decimal
    total_score: Decimal


@dataclass(frozen=True)
class ModelScore:
    track: Track
    planned_count: int
    successful_count: int
    success_rate: Decimal | None
    score: Decimal | None
    status: ModelScoreStatus


@dataclass(frozen=True)
class CompositeScore:
    track: Track
    formal_model_count: int
    score: Decimal | None
    status: CompositeScoreStatus


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def score_grade(value: Decimal) -> ScoreGrade:
    if not isinstance(value, Decimal):
        raise ScoreAggregationError("grade value must be Decimal.")
    if value < Decimal("0") or value > Decimal("100"):
        raise ScoreAggregationError("grade value must be from 0 to 100.")
    if value >= Decimal("90"):
        return "卓越"
    if value >= Decimal("75"):
        return "优秀"
    if value >= Decimal("60"):
        return "一般"
    if value >= Decimal("40"):
        return "较弱"
    return "薄弱"


def _as_score(value: int, *, field_name: str) -> Decimal:
    if type(value) is not int or not 0 <= value <= 100:
        raise ScoreAggregationError(f"{field_name} must be an integer from 0 to 100.")
    return _quantize(Decimal(value))


def recommendation_score(level: str, semantic_score: int) -> Decimal:
    expected = RECOMMENDATION_SCORES.get(level)
    if expected is None:
        raise ScoreAggregationError("recommendation_level is invalid.")
    if type(semantic_score) is not int or not 0 <= semantic_score <= 100:
        raise ScoreAggregationError("semantic_recommendation_score is invalid.")
    return _quantize(Decimal(expected))


def accuracy_score(value: int) -> Decimal:
    if value not in ACCURACY_SCORES:
        raise ScoreAggregationError("accuracy_score must use the frozen 100/75/40/0 scale.")
    return _as_score(value, field_name="accuracy_score")


def sentiment_score(value: int) -> Decimal:
    if value not in SENTIMENT_SCORES:
        raise ScoreAggregationError("sentiment_score must use the frozen 100/75/50/25/0 scale.")
    return _as_score(value, field_name="sentiment_score")


def _rank_from_position(position: int) -> int:
    if type(position) is not int or position < 1:
        raise ScoreAggregationError("auxiliary_rank_position is invalid.")
    if position == 1:
        return 100
    if position <= 3:
        return 80
    if position <= 5:
        return 60
    if position <= 10:
        return 40
    return 20


def resolved_rank_score(value: QuestionAggregationInput) -> Decimal | None:
    if value.question_type == "brand_directed":
        if (
            value.rank_resolution != "not_applicable"
            or value.rank_score is not None
            or value.auxiliary_rank_position is not None
        ):
            raise ScoreAggregationError("brand-directed rank must be N/A.")
        return None

    if value.mention_score == 0:
        return _quantize(Decimal(0))

    if value.rank_resolution == "deterministic":
        if value.rank_score not in {0, 10, 20, 40, 60, 80, 100}:
            raise ScoreAggregationError("deterministic rank_score is invalid.")
        return _as_score(value.rank_score, field_name="rank_score")

    if value.rank_resolution == "semantic_required":
        if value.rank_score is not None:
            raise ScoreAggregationError(
                "semantic-required rank must not carry a programmatic rank_score."
            )
        if value.auxiliary_rank_position is None:
            return _quantize(Decimal(10))
        return _quantize(Decimal(_rank_from_position(value.auxiliary_rank_position)))

    raise ScoreAggregationError("natural question rank_resolution is invalid.")


def resolved_citation_score(value: QuestionAggregationInput) -> Decimal:
    if value.citation_resolution == "deterministic":
        if value.citation_base_score not in {0, 20}:
            raise ScoreAggregationError("deterministic citation_base_score is invalid.")
        return _as_score(value.citation_base_score, field_name="citation_base_score")

    if value.citation_resolution != "semantic_required":
        raise ScoreAggregationError("citation_resolution is invalid.")
    if value.citation_base_score is not None:
        raise ScoreAggregationError(
            "semantic-required citation must not carry a programmatic base score."
        )
    if not value.source_classifications:
        raise ScoreAggregationError(
            "semantic-required citation needs at least one source classification."
        )

    try:
        score = max(
            SOURCE_CLASSIFICATION_SCORES[category] for category in value.source_classifications
        )
    except KeyError as exc:
        raise ScoreAggregationError("source classification is invalid.") from exc
    return _quantize(Decimal(score))


def aggregate_question_score(value: QuestionAggregationInput) -> QuestionScore:
    recommendation = recommendation_score(
        value.recommendation_level,
        value.semantic_recommendation_score,
    )
    accuracy = accuracy_score(value.accuracy_score)
    sentiment = sentiment_score(value.sentiment_score)
    citation = resolved_citation_score(value)
    rank = resolved_rank_score(value)

    if value.question_type == "natural":
        if value.mention_score not in {0, 100}:
            raise ScoreAggregationError("natural mention_score must be 0 or 100.")
        mention = _as_score(value.mention_score, field_name="mention_score")
        if rank is None:
            raise ScoreAggregationError("natural rank_score must be resolved.")

        if value.mention_score == 0:
            total = _quantize(Decimal(0))
        else:
            total = _quantize(
                mention * NATURAL_WEIGHTS["mention"]
                + recommendation * NATURAL_WEIGHTS["recommendation"]
                + rank * NATURAL_WEIGHTS["rank"]
                + accuracy * NATURAL_WEIGHTS["accuracy"]
                + sentiment * NATURAL_WEIGHTS["sentiment"]
                + citation * NATURAL_WEIGHTS["citation"]
            )
        return QuestionScore(
            question_type="natural",
            track="geo",
            mention_score=mention,
            recommendation_score=recommendation,
            rank_score=rank,
            accuracy_score=accuracy,
            sentiment_score=sentiment,
            citation_score=citation,
            total_score=total,
        )

    if value.question_type != "brand_directed":
        raise ScoreAggregationError("question_type is invalid.")
    if value.mention_score is not None:
        raise ScoreAggregationError("brand-directed mention_score must be N/A.")
    if rank is not None:
        raise ScoreAggregationError("brand-directed rank_score must be N/A.")

    total = _quantize(
        (
            recommendation * BRAND_RAW_WEIGHTS["recommendation"]
            + accuracy * BRAND_RAW_WEIGHTS["accuracy"]
            + sentiment * BRAND_RAW_WEIGHTS["sentiment"]
            + citation * BRAND_RAW_WEIGHTS["citation"]
        )
        / BRAND_WEIGHT_TOTAL
    )
    return QuestionScore(
        question_type="brand_directed",
        track="brand_reputation",
        mention_score=None,
        recommendation_score=recommendation,
        rank_score=None,
        accuracy_score=accuracy,
        sentiment_score=sentiment,
        citation_score=citation,
        total_score=total,
    )


def aggregate_model_score(
    *,
    track: Track,
    planned_count: int,
    successful_question_scores: tuple[Decimal, ...],
) -> ModelScore:
    if type(planned_count) is not int or planned_count < 0:
        raise ScoreAggregationError("planned_count must be a non-negative integer.")
    if planned_count == 0:
        if successful_question_scores:
            raise ScoreAggregationError("zero planned questions cannot have successes.")
        return ModelScore(
            track=track,
            planned_count=0,
            successful_count=0,
            success_rate=None,
            score=None,
            status="not_generated",
        )

    successful_count = len(successful_question_scores)
    if successful_count > planned_count:
        raise ScoreAggregationError("successful_count cannot exceed planned_count.")
    for value in successful_question_scores:
        if not Decimal(0) <= value <= Decimal(100):
            raise ScoreAggregationError("question score must be from 0 to 100.")

    success_rate = _quantize(Decimal(successful_count) * Decimal(100) / Decimal(planned_count))
    score = (
        _quantize(sum(successful_question_scores, Decimal(0)) / Decimal(successful_count))
        if successful_count
        else None
    )
    status: ModelScoreStatus = (
        "formal" if success_rate >= FORMAL_MODEL_SUCCESS_RATE else "reference"
    )
    return ModelScore(
        track=track,
        planned_count=planned_count,
        successful_count=successful_count,
        success_rate=success_rate,
        score=score,
        status=status,
    )


def aggregate_composite_score(
    *,
    track: Track,
    model_scores: tuple[ModelScore, ...],
) -> CompositeScore:
    formal_scores = [
        item.score
        for item in model_scores
        if item.track == track and item.status == "formal" and item.score is not None
    ]
    formal_count = len(formal_scores)
    if formal_count > MAX_DETECTION_MODELS:
        raise ScoreAggregationError("formal model count exceeds the frozen eight-model set.")
    if formal_count == 0:
        return CompositeScore(
            track=track,
            formal_model_count=0,
            score=None,
            status="failed",
        )

    score = _quantize(sum(formal_scores, Decimal(0)) / Decimal(formal_count))
    status: CompositeScoreStatus = (
        "formal" if formal_count >= FORMAL_COMPOSITE_MODEL_COUNT else "reference"
    )
    return CompositeScore(
        track=track,
        formal_model_count=formal_count,
        score=score,
        status=status,
    )
