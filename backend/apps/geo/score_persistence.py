from __future__ import annotations

import copy
from typing import Any

from apps.ai.semantic_scoring import SemanticScoringOutput

from .models import ModelResponse, ModelScoreResult, ScoreResult
from .score_aggregation import ModelScore, QuestionScore


class ScorePersistenceConflict(ValueError):
    pass


def _semantic_output_payload(output: SemanticScoringOutput) -> dict[str, object]:
    return copy.deepcopy(output.as_dict())


def _question_defaults(
    *,
    question_score: QuestionScore,
    scoring_rule_version: str,
    semantic_schema_version: str,
    semantic_provider_key: str,
    semantic_model_key: str,
    semantic_adapter_version: str,
    semantic_prompt_version: str,
    semantic_provider_model_id: str,
    semantic_output_digest: str,
    semantic_output: SemanticScoringOutput,
    programmatic_evidence: dict[str, Any],
) -> dict[str, object]:
    return {
        "question_type": question_score.question_type,
        "track": question_score.track,
        "mention_score": question_score.mention_score,
        "recommendation_score": question_score.recommendation_score,
        "rank_score": question_score.rank_score,
        "accuracy_score": question_score.accuracy_score,
        "sentiment_score": question_score.sentiment_score,
        "citation_score": question_score.citation_score,
        "total_score": question_score.total_score,
        "scoring_rule_version": scoring_rule_version,
        "semantic_schema_version": semantic_schema_version,
        "semantic_provider_key": semantic_provider_key,
        "semantic_model_key": semantic_model_key,
        "semantic_adapter_version": semantic_adapter_version,
        "semantic_prompt_version": semantic_prompt_version,
        "semantic_provider_model_id": semantic_provider_model_id,
        "semantic_output_digest": semantic_output_digest,
        "evidence": {
            "programmatic": copy.deepcopy(programmatic_evidence),
            "semantic": _semantic_output_payload(semantic_output),
        },
    }


def _assert_matches(instance, defaults: dict[str, object], *, label: str) -> None:
    mismatches = [
        field_name
        for field_name, expected in defaults.items()
        if getattr(instance, field_name) != expected
    ]
    if mismatches:
        raise ScorePersistenceConflict(
            f"{label} already exists with different immutable fields: "
            + ", ".join(sorted(mismatches))
        )


def persist_question_score(
    *,
    model_response: ModelResponse,
    question_score: QuestionScore,
    scoring_rule_version: str,
    semantic_schema_version: str,
    semantic_provider_key: str,
    semantic_model_key: str,
    semantic_adapter_version: str,
    semantic_prompt_version: str,
    semantic_provider_model_id: str,
    semantic_output_digest: str,
    semantic_output: SemanticScoringOutput,
    programmatic_evidence: dict[str, Any],
) -> tuple[ScoreResult, bool]:
    defaults = _question_defaults(
        question_score=question_score,
        scoring_rule_version=scoring_rule_version,
        semantic_schema_version=semantic_schema_version,
        semantic_provider_key=semantic_provider_key,
        semantic_model_key=semantic_model_key,
        semantic_adapter_version=semantic_adapter_version,
        semantic_prompt_version=semantic_prompt_version,
        semantic_provider_model_id=semantic_provider_model_id,
        semantic_output_digest=semantic_output_digest,
        semantic_output=semantic_output,
        programmatic_evidence=programmatic_evidence,
    )
    result, created = ScoreResult.objects.get_or_create(
        model_response=model_response,
        defaults=defaults,
    )
    if not created:
        _assert_matches(result, defaults, label="ScoreResult")
    return result, created


def persist_model_score(
    *,
    model_run,
    model_score: ModelScore,
    scoring_rule_version: str,
) -> tuple[ModelScoreResult, bool]:
    defaults: dict[str, object] = {
        "planned_count": model_score.planned_count,
        "successful_count": model_score.successful_count,
        "success_rate": model_score.success_rate,
        "score": model_score.score,
        "status": model_score.status,
        "scoring_rule_version": scoring_rule_version,
    }
    result, created = ModelScoreResult.objects.get_or_create(
        model_run=model_run,
        track=model_score.track,
        defaults=defaults,
    )
    if not created:
        _assert_matches(result, defaults, label="ModelScoreResult")
    return result, created
