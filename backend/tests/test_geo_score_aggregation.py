from __future__ import annotations

from decimal import Decimal

import pytest

from apps.geo.score_aggregation import (
    ModelScore,
    QuestionAggregationInput,
    ScoreAggregationError,
    aggregate_composite_score,
    aggregate_model_score,
    aggregate_question_score,
    score_grade,
)


def _natural(**overrides) -> QuestionAggregationInput:
    values = {
        "question_type": "natural",
        "mention_score": 100,
        "rank_score": 80,
        "rank_resolution": "deterministic",
        "citation_base_score": None,
        "citation_resolution": "semantic_required",
        "recommendation_level": "recommendation",
        "semantic_recommendation_score": 63,
        "accuracy_score": 75,
        "sentiment_score": 50,
        "auxiliary_rank_position": None,
        "source_classifications": ("mainstream_media",),
    }
    values.update(overrides)
    return QuestionAggregationInput(**values)


def _brand(**overrides) -> QuestionAggregationInput:
    values = {
        "question_type": "brand_directed",
        "mention_score": None,
        "rank_score": None,
        "rank_resolution": "not_applicable",
        "citation_base_score": None,
        "citation_resolution": "semantic_required",
        "recommendation_level": "recommendation",
        "semantic_recommendation_score": 75,
        "accuracy_score": 75,
        "sentiment_score": 50,
        "auxiliary_rank_position": None,
        "source_classifications": ("mainstream_media",),
    }
    values.update(overrides)
    return QuestionAggregationInput(**values)


def test_natural_question_uses_frozen_six_dimension_weights() -> None:
    score = aggregate_question_score(_natural())
    assert score.track == "geo"
    assert score.mention_score == Decimal("100.0000")
    assert score.recommendation_score == Decimal("75.0000")
    assert score.rank_score == Decimal("80.0000")
    assert score.accuracy_score == Decimal("75.0000")
    assert score.sentiment_score == Decimal("50.0000")
    assert score.citation_score == Decimal("80.0000")
    assert score.total_score == Decimal("80.0000")


def test_natural_unmentioned_forces_whole_question_to_zero() -> None:
    score = aggregate_question_score(
        _natural(
            mention_score=0,
            rank_score=None,
            rank_resolution="semantic_required",
            auxiliary_rank_position=2,
        )
    )
    assert score.rank_score == Decimal("0.0000")
    assert score.total_score == Decimal("0.0000")


def test_brand_directed_uses_four_dimensions_proportionally() -> None:
    score = aggregate_question_score(_brand())
    assert score.track == "brand_reputation"
    assert score.mention_score is None
    assert score.rank_score is None
    assert score.total_score == Decimal("71.6667")


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        (1, Decimal("100.0000")),
        (2, Decimal("80.0000")),
        (4, Decimal("60.0000")),
        (6, Decimal("40.0000")),
        (11, Decimal("20.0000")),
    ],
)
def test_semantic_rank_position_uses_frozen_mapping(position: int, expected: Decimal) -> None:
    score = aggregate_question_score(
        _natural(
            rank_score=None,
            rank_resolution="semantic_required",
            auxiliary_rank_position=position,
        )
    )
    assert score.rank_score == expected


def test_semantic_rank_without_list_position_is_body_mention_score_10() -> None:
    score = aggregate_question_score(
        _natural(
            rank_score=None,
            rank_resolution="semantic_required",
            auxiliary_rank_position=None,
        )
    )
    assert score.rank_score == Decimal("10.0000")


def test_citation_uses_highest_quality_valid_semantic_source() -> None:
    score = aggregate_question_score(
        _natural(source_classifications=("ordinary_website", "subject_official", "self_media"))
    )
    assert score.citation_score == Decimal("100.0000")


def test_deterministic_unverifiable_citation_keeps_base_20() -> None:
    score = aggregate_question_score(
        _natural(
            citation_resolution="deterministic",
            citation_base_score=20,
            source_classifications=(),
        )
    )
    assert score.citation_score == Decimal("20.0000")


@pytest.mark.parametrize("value", [10, 50, 74, 76, 99])
def test_accuracy_rejects_non_frozen_scores(value: int) -> None:
    with pytest.raises(ScoreAggregationError):
        aggregate_question_score(_natural(accuracy_score=value))


@pytest.mark.parametrize("value", [10, 40, 60, 80, 90])
def test_sentiment_rejects_non_frozen_scores(value: int) -> None:
    with pytest.raises(ScoreAggregationError):
        aggregate_question_score(_natural(sentiment_score=value))


def test_model_80_percent_boundary_is_formal() -> None:
    result = aggregate_model_score(
        track="geo",
        planned_count=20,
        successful_question_scores=tuple(Decimal("80.0000") for _ in range(16)),
    )
    assert result.success_rate == Decimal("80.0000")
    assert result.score == Decimal("80.0000")
    assert result.status == "formal"


def test_model_75_percent_boundary_is_reference() -> None:
    result = aggregate_model_score(
        track="geo",
        planned_count=20,
        successful_question_scores=tuple(Decimal("80.0000") for _ in range(15)),
    )
    assert result.success_rate == Decimal("75.0000")
    assert result.status == "reference"


def test_zero_questions_generate_no_model_score() -> None:
    result = aggregate_model_score(
        track="brand_reputation",
        planned_count=0,
        successful_question_scores=(),
    )
    assert result.status == "not_generated"
    assert result.score is None
    assert result.success_rate is None


def _formal(score: str, *, track: str = "geo") -> ModelScore:
    return ModelScore(
        track=track,
        planned_count=10,
        successful_count=10,
        success_rate=Decimal("100.0000"),
        score=Decimal(score),
        status="formal",
    )


def _reference(score: str, *, track: str = "geo") -> ModelScore:
    return ModelScore(
        track=track,
        planned_count=10,
        successful_count=7,
        success_rate=Decimal("70.0000"),
        score=Decimal(score),
        status="reference",
    )


def test_six_formal_models_generate_formal_composite() -> None:
    result = aggregate_composite_score(
        track="geo",
        model_scores=tuple(_formal("80.0000") for _ in range(6)),
    )
    assert result.formal_model_count == 6
    assert result.score == Decimal("80.0000")
    assert result.status == "formal"


def test_five_formal_models_generate_reference_composite() -> None:
    result = aggregate_composite_score(
        track="geo",
        model_scores=tuple(_formal("80.0000") for _ in range(5)),
    )
    assert result.formal_model_count == 5
    assert result.status == "reference"


def test_reference_models_do_not_enter_composite_average() -> None:
    result = aggregate_composite_score(
        track="geo",
        model_scores=(
            _formal("80.0000"),
            _formal("60.0000"),
            _reference("100.0000"),
            _formal("70.0000", track="brand_reputation"),
        ),
    )
    assert result.formal_model_count == 2
    assert result.score == Decimal("70.0000")
    assert result.status == "reference"


def test_zero_formal_models_is_failed_composite() -> None:
    result = aggregate_composite_score(
        track="geo",
        model_scores=(_reference("80.0000"),),
    )
    assert result.formal_model_count == 0
    assert result.score is None
    assert result.status == "failed"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("100.0000", "卓越"),
        ("90.0000", "卓越"),
        ("89.9999", "优秀"),
        ("75.0000", "优秀"),
        ("74.9999", "一般"),
        ("60.0000", "一般"),
        ("59.9999", "较弱"),
        ("40.0000", "较弱"),
        ("39.9999", "薄弱"),
        ("0.0000", "薄弱"),
    ],
)
def test_score_grade_uses_frozen_bands(value: str, expected: str) -> None:
    assert score_grade(Decimal(value)) == expected


@pytest.mark.parametrize("value", ["-0.0001", "100.0001"])
def test_score_grade_rejects_out_of_range_values(value: str) -> None:
    with pytest.raises(ScoreAggregationError):
        score_grade(Decimal(value))
