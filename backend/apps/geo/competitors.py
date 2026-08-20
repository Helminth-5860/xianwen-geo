from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import OuterRef, QuerySet, Subquery

from apps.ai.semantic_scoring import SEMANTIC_SCORING_SCHEMA_VERSION
from apps.keywords.normalization import normalize_plain_text

from .models import (
    CompetitorDisposition,
    CompetitorEntity,
    CompetitorMention,
    GeoDetectionJob,
    ScoreResult,
)


class CompetitorReferenceError(ValueError):
    pass


@dataclass(frozen=True)
class CompetitorMentionFact:
    score_result_id: UUID
    canonical_name: str
    canonical_key: str
    aliases: tuple[str, ...]
    entity_type: str
    question: str
    model_key: str
    occurrence: int
    recommendation_score: Decimal
    subject_rank: int | None
    competitor_rank: int | None
    rank_gap: int | None
    evidence: dict[str, object]
    provenance: dict[str, object]


@dataclass(frozen=True)
class CompetitorReferenceEntity:
    canonical_name: str
    canonical_key: str
    aliases: tuple[str, ...]
    entity_type: str
    mentions: tuple[CompetitorMentionFact, ...]


def _safe_semantic_competitors(score: ScoreResult) -> tuple[dict[str, Any], ...]:
    if score.semantic_schema_version != SEMANTIC_SCORING_SCHEMA_VERSION:
        return ()
    evidence = score.evidence
    if not isinstance(evidence, dict):
        return ()
    semantic = evidence.get("semantic")
    if (
        not isinstance(semantic, dict)
        or semantic.get("schema_version") != SEMANTIC_SCORING_SCHEMA_VERSION
    ):
        return ()
    competitors = semantic.get("competitors")
    if not isinstance(competitors, list):
        return ()
    required = {
        "canonical_name",
        "aliases",
        "evidence_snippets",
        "entity_type",
        "competitor_eligible",
        "exclusion_reason",
        "classification_evidence",
    }
    return tuple(item for item in competitors if isinstance(item, dict) and set(item) == required)


def aggregate_competitor_reference(
    *, scores: tuple[ScoreResult, ...]
) -> tuple[CompetitorReferenceEntity, ...]:
    grouped: dict[str, list[CompetitorMentionFact]] = {}
    entity_names: dict[str, str] = {}
    entity_types: dict[str, str] = {}
    entity_aliases: dict[str, dict[str, str]] = {}

    for score in scores:
        call = score.model_response.model_call
        programmatic = score.evidence.get("programmatic", {})
        subject_rank = programmatic.get("rank_position") if isinstance(programmatic, dict) else None
        if type(subject_rank) is not int or subject_rank < 1:
            subject_rank = None
        for occurrence, item in enumerate(_safe_semantic_competitors(score), start=1):
            if item.get("competitor_eligible") is not True:
                continue
            entity_type = item.get("entity_type")
            if entity_type not in {"brand", "company", "product"}:
                continue
            canonical = item.get("canonical_name")
            aliases = item.get("aliases")
            snippets = item.get("evidence_snippets")
            classification = item.get("classification_evidence")
            if (
                not isinstance(canonical, str)
                or not isinstance(aliases, list)
                or not all(isinstance(value, str) for value in aliases)
                or not isinstance(snippets, list)
                or not all(isinstance(value, str) for value in snippets)
                or not isinstance(classification, list)
                or not all(isinstance(value, str) for value in classification)
            ):
                continue
            canonical_name, canonical_key = normalize_plain_text(canonical, max_length=255)
            if canonical_key in entity_types and entity_types[canonical_key] != entity_type:
                raise CompetitorReferenceError(
                    "one canonical competitor has conflicting frozen entity types."
                )
            entity_names.setdefault(canonical_key, canonical_name)
            entity_types[canonical_key] = entity_type
            alias_map = entity_aliases.setdefault(canonical_key, {})
            for alias in aliases:
                display, key = normalize_plain_text(alias, max_length=255)
                if key != canonical_key:
                    alias_map.setdefault(key, display)
            fact = CompetitorMentionFact(
                score_result_id=score.pk,
                canonical_name=canonical_name,
                canonical_key=canonical_key,
                aliases=tuple(alias_map.values()),
                entity_type=entity_type,
                question=call.question_snapshot.text,
                model_key=call.model_key,
                occurrence=occurrence,
                recommendation_score=score.recommendation_score,
                subject_rank=subject_rank,
                competitor_rank=None,
                rank_gap=None,
                evidence={
                    "evidence_snippets": list(snippets),
                    "classification_evidence": list(classification),
                },
                provenance={
                    "semantic_schema_version": score.semantic_schema_version,
                    "semantic_output_digest": score.semantic_output_digest,
                    "semantic_provider_key": score.semantic_provider_key,
                    "semantic_model_key": score.semantic_model_key,
                    "semantic_adapter_version": score.semantic_adapter_version,
                    "semantic_prompt_version": score.semantic_prompt_version,
                    "rank_status": "unavailable",
                },
            )
            grouped.setdefault(canonical_key, []).append(fact)

    return tuple(
        CompetitorReferenceEntity(
            canonical_name=entity_names[key],
            canonical_key=key,
            aliases=tuple(
                value for _, value in sorted(entity_aliases[key].items(), key=lambda pair: pair[0])
            ),
            entity_type=entity_types[key],
            mentions=tuple(grouped[key]),
        )
        for key in sorted(grouped)
    )


def competitor_reference_for_job(*, job: GeoDetectionJob) -> tuple[CompetitorReferenceEntity, ...]:
    scores = tuple(
        ScoreResult.objects.filter(model_response__model_call__job=job)
        .select_related(
            "model_response__model_call__question_snapshot",
            "model_response__model_call__model_run",
        )
        .order_by(
            "model_response__model_call__question_snapshot__sort_order",
            "model_response__model_call__model_run_id",
            "id",
        )
    )
    return aggregate_competitor_reference(scores=scores)


@transaction.atomic
def persist_competitor_reference(*, job: GeoDetectionJob) -> tuple[CompetitorEntity, ...]:
    reference = competitor_reference_for_job(job=job)
    if CompetitorEntity.objects.filter(job=job).exists():
        raise CompetitorReferenceError("competitor reference already exists for this detection.")
    entities: list[CompetitorEntity] = []
    for item in reference:
        entity = CompetitorEntity.objects.create(
            job=job,
            canonical_name=item.canonical_name,
            canonical_key=item.canonical_key,
            aliases=list(item.aliases),
            entity_type=item.entity_type,
            semantic_schema_version=SEMANTIC_SCORING_SCHEMA_VERSION,
        )
        CompetitorMention.objects.bulk_create(
            [
                CompetitorMention(
                    entity=entity,
                    score_result_id=mention.score_result_id,
                    question=mention.question,
                    model_key=mention.model_key,
                    occurrence=mention.occurrence,
                    recommendation_score=mention.recommendation_score,
                    subject_rank=mention.subject_rank,
                    competitor_rank=mention.competitor_rank,
                    rank_gap=mention.rank_gap,
                    evidence=mention.evidence,
                    provenance=mention.provenance,
                )
                for mention in item.mentions
            ]
        )
        entities.append(entity)
    return tuple(entities)


def record_competitor_disposition(
    *, entity: CompetitorEntity, actor, decision: str, note: str = ""
) -> CompetitorDisposition:
    if actor.pk != entity.job.user_id:
        raise CompetitorReferenceError("actor does not own this detection.")
    if decision not in {
        CompetitorDisposition.Decision.COMPETITOR,
        CompetitorDisposition.Decision.NOT_COMPETITOR,
    }:
        raise CompetitorReferenceError("competitor disposition decision is invalid.")
    normalized_note = normalize_plain_text(note, max_length=1000)[0] if note.strip() else ""
    return CompetitorDisposition.objects.create(
        entity=entity, actor=actor, decision=decision, note=normalized_note
    )


def active_competitor_entities(*, job: GeoDetectionJob) -> QuerySet[CompetitorEntity]:
    latest = CompetitorDisposition.objects.filter(entity_id=OuterRef("pk")).order_by(
        "-created_at", "-id"
    )
    return (
        CompetitorEntity.objects.filter(job=job)
        .annotate(latest_decision=Subquery(latest.values("decision")[:1]))
        .exclude(latest_decision=CompetitorDisposition.Decision.NOT_COMPETITOR)
    )
