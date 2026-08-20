from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast
from uuid import UUID

from django.apps import apps
from django.db import connection

from apps.ai.contracts import AIAdapterRequest, AIModelCapability
from apps.ai.registry import model_registry
from apps.ai.semantic_scoring import SemanticScoringOutput, SemanticScoringPayload

from .models import (
    ModelCall,
    ModelResponse,
    ProgrammaticScoreResult,
    ScoreResult,
)
from .score_aggregation import (
    QuestionAggregationInput,
    QuestionType,
    Track,
    aggregate_model_score,
    aggregate_question_score,
)
from .score_persistence import persist_model_score, persist_question_score

SEMANTIC_SCORING_PROVIDER_KEY = "deepseek"
SEMANTIC_SCORING_MODEL_KEY = "deepseek"
SEMANTIC_SCORING_TIMEOUT_SECONDS = 60
TERMINAL_CALL_STATUSES = (
    ModelCall.Status.SUCCEEDED,
    ModelCall.Status.FAILED,
    ModelCall.Status.CANCELLED,
)


class ScoreOrchestrationError(ValueError):
    pass


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def _serialize_model(instance, *, excluded: frozenset[str] = frozenset()) -> dict[str, object]:
    payload: dict[str, object] = {}
    for field in instance._meta.concrete_fields:
        if field.name in excluded:
            continue
        payload[field.name] = _json_safe(getattr(instance, field.attname))
    return payload


def _subject_snapshot(model_response: ModelResponse) -> dict[str, object]:
    subject_version = model_response.model_call.job.snapshot.subject_version
    snapshot: dict[str, object] = {
        "subject_version": _serialize_model(subject_version),
        "names": [],
        "products": [],
    }
    for model_name, key in (("SubjectName", "names"), ("SubjectProduct", "products")):
        model = apps.get_model("subjects", model_name)
        rows = model.objects.filter(subject_version_id=subject_version.pk).order_by("pk")
        snapshot[key] = [
            _serialize_model(
                row,
                excluded=frozenset({"subject_version"}),
            )
            for row in rows
        ]
    return snapshot


def _citation_payload(model_response: ModelResponse) -> tuple[dict[str, object], ...]:
    return tuple(
        _serialize_model(
            citation,
            excluded=frozenset({"model_response"}),
        )
        for citation in model_response.citations.all()
    )


def _programmatic_context(programmatic: ProgrammaticScoreResult) -> dict[str, object]:
    return {
        "scoring_rule_version": programmatic.scoring_rule_version,
        "question_type": programmatic.question_type,
        "mention_score": programmatic.mention_score,
        "matched_kind": programmatic.matched_kind,
        "matched_value": programmatic.matched_value,
        "rank_position": programmatic.rank_position,
        "rank_score": programmatic.rank_score,
        "rank_resolution": programmatic.rank_resolution,
        "citation_base_score": programmatic.citation_base_score,
        "citation_resolution": programmatic.citation_resolution,
        "citation_evidence_count": programmatic.citation_evidence_count,
        "evidence": _json_safe(programmatic.evidence),
    }


def semantic_output_digest(output: SemanticScoringOutput) -> str:
    rendered = json.dumps(
        output.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def build_question_aggregation_input(
    *,
    programmatic: ProgrammaticScoreResult,
    semantic: SemanticScoringOutput,
) -> QuestionAggregationInput:
    categories = tuple(
        str(item["category"])
        for item in semantic.source_classifications
        if isinstance(item.get("category"), str)
    )
    return QuestionAggregationInput(
        question_type=cast(QuestionType, programmatic.question_type),
        mention_score=programmatic.mention_score,
        rank_score=programmatic.rank_score,
        rank_resolution=programmatic.rank_resolution,
        citation_base_score=programmatic.citation_base_score,
        citation_resolution=programmatic.citation_resolution,
        recommendation_level=semantic.recommendation_level,
        semantic_recommendation_score=semantic.recommendation_score,
        accuracy_score=semantic.accuracy_score,
        sentiment_score=semantic.sentiment_score,
        auxiliary_rank_position=semantic.auxiliary_rank_position,
        source_classifications=categories,
    )


@contextmanager
def _semantic_response_lock(model_response_id) -> Any:
    if connection.vendor != "postgresql":
        yield
        return

    lock_key = f"geo-semantic-score:{model_response_id}"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
            [lock_key],
        )
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                [lock_key],
            )


def due_semantic_score_response_ids(limit: int = 100) -> list:
    if type(limit) is not int or limit < 1:
        raise ScoreOrchestrationError("limit must be a positive integer.")
    return list(
        ModelResponse.objects.filter(
            model_call__status=ModelCall.Status.SUCCEEDED,
            model_call__question_snapshot__participates_in_scoring=True,
            programmatic_score__isnull=False,
            score_result__isnull=True,
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)[:limit]
    )


def _semantic_payload(
    *,
    model_response: ModelResponse,
    programmatic: ProgrammaticScoreResult,
) -> SemanticScoringPayload:
    question = model_response.model_call.question_snapshot
    return SemanticScoringPayload(
        question=question.text,
        question_type=question.question_type,
        raw_response=model_response.raw_text,
        subject_snapshot=_subject_snapshot(model_response),
        programmatic_context=_programmatic_context(programmatic),
        citations=_citation_payload(model_response),
        scoring_rule_version=programmatic.scoring_rule_version,
    )


def score_model_response(
    *,
    model_response_id,
    adapter=None,
) -> ScoreResult | None:
    with _semantic_response_lock(model_response_id):
        existing = ScoreResult.objects.filter(model_response_id=model_response_id).first()
        if existing is not None:
            return existing

        model_response = (
            ModelResponse.objects.select_related(
                "model_call__question_snapshot",
                "model_call__job__snapshot__subject_version",
                "model_call__model_run",
                "programmatic_score",
            )
            .prefetch_related("citations")
            .get(pk=model_response_id)
        )
        call = model_response.model_call
        question = call.question_snapshot

        if call.status != ModelCall.Status.SUCCEEDED:
            raise ScoreOrchestrationError("Only succeeded detection responses can be scored.")
        if not question.participates_in_scoring:
            return None

        programmatic = model_response.programmatic_score
        semantic_adapter = adapter or model_registry.resolve(
            provider_key=SEMANTIC_SCORING_PROVIDER_KEY,
            model_key=SEMANTIC_SCORING_MODEL_KEY,
            capability=AIModelCapability.SEMANTIC_SCORING,
        )
        payload = _semantic_payload(
            model_response=model_response,
            programmatic=programmatic,
        )
        request = AIAdapterRequest(
            request_id=f"score-{model_response.pk}",
            correlation_id=str(call.job_id),
            identity=semantic_adapter.descriptor.identity,
            capability=AIModelCapability.SEMANTIC_SCORING,
            adapter_version=semantic_adapter.descriptor.adapter_version,
            prompt_version=semantic_adapter.descriptor.prompt_version,
            timeout_seconds=SEMANTIC_SCORING_TIMEOUT_SECONDS,
            payload=payload,
            metadata={
                "model_response_id": str(model_response.pk),
                "model_call_id": str(call.pk),
                "scoring_rule_version": programmatic.scoring_rule_version,
            },
        )
        semantic_response = semantic_adapter.invoke(request)
        semantic_output = semantic_response.output
        if not isinstance(semantic_output, SemanticScoringOutput):
            raise ScoreOrchestrationError(
                "Semantic scoring adapter returned an unexpected output contract."
            )

        provider_model_id = semantic_response.sanitized_provider_metadata.get("provider_model_id")
        if not isinstance(provider_model_id, str) or not provider_model_id:
            raise ScoreOrchestrationError("Semantic scoring provider model provenance is missing.")

        question_score = aggregate_question_score(
            build_question_aggregation_input(
                programmatic=programmatic,
                semantic=semantic_output,
            )
        )
        result, _ = persist_question_score(
            model_response=model_response,
            question_score=question_score,
            scoring_rule_version=programmatic.scoring_rule_version,
            semantic_schema_version=semantic_output.schema_version,
            semantic_provider_key=semantic_adapter.descriptor.identity.provider_key,
            semantic_model_key=semantic_adapter.descriptor.identity.model_key,
            semantic_adapter_version=semantic_adapter.descriptor.adapter_version,
            semantic_prompt_version=semantic_adapter.descriptor.prompt_version,
            semantic_provider_model_id=provider_model_id,
            semantic_output_digest=semantic_output_digest(semantic_output),
            semantic_output=semantic_output,
            programmatic_evidence=programmatic.evidence,
        )

    finalize_model_run_scores(model_run_id=call.model_run_id)
    return result


def finalize_model_run_scores(*, model_run_id) -> dict[str, str]:
    model_run_model = apps.get_model("geo", "GeoDetectionModelRun")
    model_run = model_run_model.objects.get(pk=model_run_id)
    statuses: dict[str, str] = {}

    track_specs: tuple[tuple[QuestionType, Track], ...] = (
        ("natural", "geo"),
        ("brand_directed", "brand_reputation"),
    )
    for question_type, track in track_specs:
        calls = model_run.calls.filter(
            question_snapshot__participates_in_scoring=True,
            question_snapshot__question_type=question_type,
        )
        planned_count = calls.count()
        if planned_count == 0:
            statuses[track] = "not_generated"
            continue

        if calls.exclude(status__in=TERMINAL_CALL_STATUSES).exists():
            statuses[track] = "pending_detection"
            continue

        successful_calls = calls.filter(status=ModelCall.Status.SUCCEEDED)
        if successful_calls.filter(response__score_result__isnull=True).exists():
            statuses[track] = "pending_scoring"
            continue

        successful_scores = tuple(
            Decimal(str(value))
            for value in successful_calls.order_by(
                "question_snapshot__sort_order", "id"
            ).values_list("response__score_result__total_score", flat=True)
        )
        model_score = aggregate_model_score(
            track=track,
            planned_count=planned_count,
            successful_question_scores=successful_scores,
        )
        persist_model_score(
            model_run=model_run,
            model_score=model_score,
            scoring_rule_version=model_run.job.snapshot.scoring_rule_version,
        )
        statuses[track] = model_score.status

    return statuses
