from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction

from apps.ai.semantic_scoring import SEMANTIC_SCORING_SCHEMA_VERSION
from apps.geo.competitors import (
    active_competitor_entities,
    aggregate_competitor_reference,
    persist_competitor_reference,
    record_competitor_disposition,
)
from apps.geo.models import (
    CompetitorDisposition,
    CompetitorEntity,
    CompetitorMention,
    ModelResponse,
    ScoreResult,
)
from tests.test_geo_detection import _create
from tests.test_geo_detection import geo_facts as geo_facts_fixture


def _score(
    *,
    canonical="Beta",
    aliases=("Beta Pro",),
    entity_type="brand",
    eligible=True,
    reason=None,
    question="Which one?",
    model="deepseek",
    schema=SEMANTIC_SCORING_SCHEMA_VERSION,
):
    competitor = {
        "canonical_name": canonical,
        "aliases": list(aliases),
        "evidence_snippets": [f"{canonical} is compared."],
        "entity_type": entity_type,
        "competitor_eligible": eligible,
        "exclusion_reason": reason,
        "classification_evidence": ["A direct competitive relationship is stated."],
    }
    call = SimpleNamespace(question_snapshot=SimpleNamespace(text=question), model_key=model)
    return SimpleNamespace(
        pk=uuid4(),
        model_response=SimpleNamespace(model_call=call),
        recommendation_score=Decimal("75.0000"),
        semantic_schema_version=schema,
        semantic_output_digest="a" * 64,
        semantic_provider_key="deepseek",
        semantic_model_key="deepseek",
        semantic_adapter_version="deepseek-semantic-scoring-v2",
        semantic_prompt_version="geo-semantic-scoring-v2",
        evidence={
            "programmatic": {"rank_position": 2},
            "semantic": {"schema_version": schema, "competitors": [competitor]},
        },
    )


def test_only_eligible_entities_are_aggregated_and_exclusions_remain_out() -> None:
    scores = (
        _score(),
        _score(
            canonical="Industry", entity_type="industry", eligible=False, reason="industry_term"
        ),
        _score(
            canonical="Platform", entity_type="platform", eligible=False, reason="platform_name"
        ),
        _score(
            canonical="Generic",
            entity_type="generic_product",
            eligible=False,
            reason="generic_product_term",
        ),
    )
    with patch(
        "apps.geo.competitors.normalize_plain_text",
        wraps=__import__(
            "apps.keywords.normalization", fromlist=["normalize_plain_text"]
        ).normalize_plain_text,
    ):
        result = aggregate_competitor_reference(scores=scores)
    assert [item.canonical_name for item in result] == ["Beta"]


def test_canonical_entity_merges_across_questions_models_and_aliases() -> None:
    result = aggregate_competitor_reference(
        scores=(
            _score(question="Question A", model="deepseek", aliases=("Beta Pro",)),
            _score(question="Question B", model="qwen", aliases=("BETA PRO", "Beta Cloud")),
        )
    )
    assert len(result) == 1
    assert result[0].aliases == ("Beta Cloud", "Beta Pro")
    assert {item.question for item in result[0].mentions} == {"Question A", "Question B"}
    assert {item.model_key for item in result[0].mentions} == {"deepseek", "qwen"}
    assert result[0].mentions[0].evidence["classification_evidence"]
    assert result[0].mentions[0].subject_rank == 2
    assert result[0].mentions[0].competitor_rank is None
    assert result[0].mentions[0].rank_gap is None


def test_historical_v1_fails_closed_without_provider_invocation() -> None:
    with patch("apps.geo.competitors.normalize_plain_text") as normalization:
        result = aggregate_competitor_reference(
            scores=(_score(schema="geo-semantic-score-schema-v1"),)
        )
    assert result == ()
    normalization.assert_not_called()


def test_competitor_evidence_models_are_immutable() -> None:
    for instance in (CompetitorEntity(), CompetitorMention(), CompetitorDisposition()):
        instance._state.adding = False
        with pytest.raises(TypeError):
            instance.save()
        with pytest.raises(TypeError):
            instance.delete()


@pytest.mark.django_db
def test_disposition_is_append_only_and_latest_decision_controls_active_filter(monkeypatch) -> None:
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)
    facts = geo_facts_fixture.__wrapped__(monkeypatch)
    job, _ = _create(facts, key="geo-" + "competitor-" + "disposition-" + "0001")
    call = job.model_calls.filter(question_snapshot__question_type="natural").first()
    assert call is not None
    response = ModelResponse.objects.create(
        model_call=call,
        provider_model_id=call.provider_model_id,
        raw_text="Beta is a comparison.",
        raw_text_sha256="b" * 64,
        provider_metadata={},
    )
    semantic = _score()
    score = ScoreResult.objects.create(
        model_response=response,
        question_type="natural",
        track="geo",
        mention_score=Decimal("100.0000"),
        recommendation_score=Decimal("75.0000"),
        rank_score=Decimal("80.0000"),
        accuracy_score=Decimal("75.0000"),
        sentiment_score=Decimal("50.0000"),
        citation_score=Decimal("0.0000"),
        total_score=Decimal("75.0000"),
        scoring_rule_version="geo-scoring-v1",
        semantic_schema_version=SEMANTIC_SCORING_SCHEMA_VERSION,
        semantic_provider_key="deepseek",
        semantic_model_key="deepseek",
        semantic_adapter_version="deepseek-semantic-scoring-v2",
        semantic_prompt_version="geo-semantic-scoring-v2",
        semantic_provider_model_id="deepseek-chat",
        semantic_output_digest="a" * 64,
        evidence=semantic.evidence,
    )
    entity = persist_competitor_reference(job=job)[0]
    mention = CompetitorMention.objects.get(entity=entity, score_result=score)
    evidence_count = CompetitorMention.objects.filter(entity=entity).count()
    first = record_competitor_disposition(
        entity=entity, actor=job.user, decision="not_competitor", note="Not relevant"
    )
    assert not active_competitor_entities(job=job).filter(pk=entity.pk).exists()
    second = record_competitor_disposition(
        entity=entity, actor=job.user, decision="competitor", note="Restored"
    )
    assert first.pk != second.pk
    assert second.pk.int > first.pk.int
    assert CompetitorDisposition.objects.filter(entity=entity).count() == 2
    assert CompetitorMention.objects.filter(entity=entity).count() == evidence_count
    assert active_competitor_entities(job=job).filter(pk=entity.pk).exists()

    if connection.vendor == "postgresql":
        for table, row_id in (
            ("competitor_entities", entity.pk),
            ("competitor_mentions", mention.pk),
            ("competitor_dispositions", first.pk),
        ):
            with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {table} SET created_at = created_at WHERE id = %s", [row_id]
                )
            with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table} WHERE id = %s", [row_id])
