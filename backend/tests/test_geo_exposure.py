from decimal import Decimal

import pytest

from apps.geo.exposure import (
    EXPOSURE_DISCLAIMER,
    ExposureCallFact,
    calculate_exposure,
    exposure_grade,
)


def _fact(model: str, mention: int, recommendation: int, rank: int) -> ExposureCallFact:
    return ExposureCallFact(
        model_run_id=model,
        mention_score=Decimal(mention),
        recommendation_score=Decimal(recommendation),
        rank_score=Decimal(rank),
    )


def test_exposure_uses_frozen_40_25_20_15_formula_and_decimal_precision() -> None:
    result = calculate_exposure(
        successful_natural_calls=(
            _fact("a", 100, 100, 100),
            _fact("b", 100, 40, 80),
            _fact("c", 0, 100, 100),
            _fact("d", 0, 75, 80),
        ),
        successful_model_ids=frozenset({"a", "b", "c", "d"}),
        formal_geo_model_count=6,
    )
    assert result.mention_rate_score == Decimal("50.0000")
    assert result.recommendation_rate_score == Decimal("50.0000")
    assert result.ranking_performance_score == Decimal("45.0000")
    assert result.model_coverage_score == Decimal("50.0000")
    assert result.exposure_index == Decimal("49.0000")
    assert result.status == "formal"


def test_no_mentions_and_zero_denominators_are_conservative_zero() -> None:
    no_mentions = calculate_exposure(
        successful_natural_calls=(_fact("a", 0, 100, 80),),
        successful_model_ids=frozenset({"a"}),
        formal_geo_model_count=0,
    )
    assert no_mentions.mention_rate_score == 0
    assert no_mentions.recommendation_rate_score == 0
    assert no_mentions.ranking_performance_score == 0
    empty = calculate_exposure(
        successful_natural_calls=(),
        successful_model_ids=frozenset(),
        formal_geo_model_count=0,
    )
    assert empty.exposure_index == Decimal("0.0000")


def test_only_75_and_100_are_explicit_recommendations() -> None:
    result = calculate_exposure(
        successful_natural_calls=tuple(
            _fact(str(value), 100, value, 100) for value in (0, 40, 74, 75, 100)
        ),
        successful_model_ids=frozenset(str(value) for value in (0, 40, 74, 75, 100)),
        formal_geo_model_count=5,
    )
    assert result.recommendation_rate_score == Decimal("40.0000")
    assert result.status == "reference"


def test_unmentioned_calls_remain_in_rank_denominator_and_model_coverage_uses_models() -> None:
    result = calculate_exposure(
        successful_natural_calls=(
            _fact("a", 100, 75, 80),
            _fact("a", 0, 100, 100),
            _fact("b", 0, 100, 100),
        ),
        successful_model_ids=frozenset({"a", "b", "c"}),
        formal_geo_model_count=0,
    )
    assert result.ranking_performance_score == Decimal("26.6667")
    assert result.model_coverage_score == Decimal("33.3333")


def test_model_coverage_excludes_models_that_did_not_successfully_complete() -> None:
    result = calculate_exposure(
        successful_natural_calls=(
            _fact("succeeded", 100, 75, 100),
            _fact("partial", 100, 75, 100),
        ),
        successful_model_ids=frozenset({"succeeded"}),
        formal_geo_model_count=0,
    )
    assert result.model_coverage_score == Decimal("100.0000")


@pytest.mark.parametrize(
    ("value", "grade"),
    [
        ("100", "极高"),
        ("90", "极高"),
        ("89.9999", "高"),
        ("75", "高"),
        ("74.9999", "中"),
        ("60", "中"),
        ("59.9999", "较低"),
        ("40", "较低"),
        ("39.9999", "低"),
        ("0", "低"),
    ],
)
def test_exposure_grade_boundaries(value: str, grade: str) -> None:
    assert exposure_grade(Decimal(value)) == grade


def test_exposure_disclaimer_is_stable() -> None:
    assert EXPOSURE_DISCLAIMER == "曝光潜力指数是系统评估指数，不是实际曝光人数。"
