from __future__ import annotations

from types import SimpleNamespace

from apps.ai.semantic_scoring import SemanticScoringOutput
from apps.geo.score_orchestration import (
    build_question_aggregation_input,
    semantic_output_digest,
)


def _semantic() -> SemanticScoringOutput:
    return SemanticScoringOutput(
        schema_version="geo-semantic-score-schema-v2",
        recommendation_level="recommendation",
        recommendation_score=75,
        accuracy_score=75,
        sentiment_label="neutral",
        sentiment_score=50,
        auxiliary_rank_position=2,
        source_classifications=({"citation_index": 0, "category": "mainstream_media"},),
        competitors=(),
        evidence={
            "recommendation": ("listed",),
            "accuracy": ("mostly accurate",),
            "sentiment": ("neutral",),
            "rank": ("second",),
            "source": ("mainstream",),
            "competitors": (),
        },
        reason="Stable semantic result.",
    )


def test_semantic_output_digest_is_stable() -> None:
    output = _semantic()
    assert semantic_output_digest(output) == semantic_output_digest(output)
    assert len(semantic_output_digest(output)) == 64


def test_question_aggregation_input_preserves_programmatic_authority() -> None:
    programmatic = SimpleNamespace(
        question_type="natural",
        mention_score=100,
        rank_score=None,
        rank_resolution="semantic_required",
        citation_base_score=None,
        citation_resolution="semantic_required",
    )
    result = build_question_aggregation_input(
        programmatic=programmatic,
        semantic=_semantic(),
    )
    assert result.question_type == "natural"
    assert result.mention_score == 100
    assert result.rank_score is None
    assert result.rank_resolution == "semantic_required"
    assert result.auxiliary_rank_position == 2
    assert result.source_classifications == ("mainstream_media",)


def test_brand_directed_keeps_programmatic_na_shape() -> None:
    programmatic = SimpleNamespace(
        question_type="brand_directed",
        mention_score=None,
        rank_score=None,
        rank_resolution="not_applicable",
        citation_base_score=0,
        citation_resolution="deterministic",
    )
    result = build_question_aggregation_input(
        programmatic=programmatic,
        semantic=_semantic(),
    )
    assert result.question_type == "brand_directed"
    assert result.mention_score is None
    assert result.rank_score is None
    assert result.rank_resolution == "not_applicable"
