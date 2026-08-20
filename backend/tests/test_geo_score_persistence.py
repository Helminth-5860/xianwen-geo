from __future__ import annotations

import pytest

from apps.geo.models import ModelScoreResult, ScoreResult


def test_score_result_schema_is_immutable_and_track_frozen() -> None:
    assert ScoreResult._meta.db_table == "score_results"
    assert ScoreResult._meta.get_field("model_response").one_to_one is True
    assert {value for value, _ in ScoreResult.Track.choices} == {
        "geo",
        "brand_reputation",
    }

    instance = ScoreResult()
    instance._state.adding = False
    with pytest.raises(TypeError, match="immutable"):
        instance.save()
    with pytest.raises(TypeError, match="immutable"):
        instance.delete()


def test_model_score_schema_is_immutable_and_unique_per_track() -> None:
    assert ModelScoreResult._meta.db_table == "model_scores"
    constraint_names = {constraint.name for constraint in ModelScoreResult._meta.constraints}
    assert "model_score_unique" in constraint_names

    instance = ModelScoreResult()
    instance._state.adding = False
    with pytest.raises(TypeError, match="immutable"):
        instance.save()
    with pytest.raises(TypeError, match="immutable"):
        instance.delete()
