from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
from django.db import DatabaseError, connection, transaction

from apps.ai.runtime import get_runtime_snapshot
from apps.geo.assistant import respond_to_assistant
from apps.geo.strategy import (
    claim_strategy_report,
    create_strategy_report,
    execute_strategy_report,
    put_strategy_note,
)
from apps.questions.catalog import BUILTIN_QUESTION_CATEGORIES
from apps.questions.models import QuestionCategory
from tests.test_geo_strategy_assistant import (
    _ContentAdapter,
)
from tests.test_geo_strategy_assistant import (
    stage_facts as stage_facts_fixture,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def postgres_stage_facts(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-specific integration evidence")
    for item in BUILTIN_QUESTION_CATEGORIES:
        QuestionCategory.objects.get_or_create(
            key=item.key,
            defaults={
                "name": item.name,
                "normalized_name": item.name.casefold(),
                "description": item.description,
                "generation_guidance": item.generation_guidance,
                "sort_order": item.sort_order,
                "is_builtin": True,
            },
        )
    return stage_facts_fixture.__wrapped__(monkeypatch)


def _create(stage_facts, adapter, *, regenerate=False):
    user, _, _, _, _, _, report = stage_facts
    runtime = get_runtime_snapshot(model_key="deepseek", require_available=True)
    with patch("apps.geo.strategy.resolve_strategy_runtime", return_value=(runtime, adapter)):
        return create_strategy_report(
            user_id=user.pk,
            report_id=report.pk,
            period="30d",
            custom_days=None,
            regenerate=regenerate,
            idempotency_key=f"postgres-strategy-{uuid.uuid4()}",
            request_id=uuid.uuid4(),
        )[0]


def _execute(strategy, adapter):
    runtime = get_runtime_snapshot(model_key="deepseek", require_available=True)
    with patch("apps.geo.strategy.resolve_strategy_runtime", return_value=(runtime, adapter)):
        return execute_strategy_report(strategy_id=strategy.pk)


def test_postgresql_strategy_output_and_assistant_usage_are_no_delete_terminal_evidence(
    postgres_stage_facts,
):
    user, subject, _, _, _, _, _ = postgres_stage_facts
    strategy_adapter = _ContentAdapter()
    strategy = _create(postgres_stage_facts, strategy_adapter)
    assert _execute(strategy, strategy_adapter) == {"status": "succeeded"}
    note = put_strategy_note(
        user=user, strategy_id=strategy.pk, text="可编辑备注", expected_version=0
    )

    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE strategy_reports SET ai_body = %s::jsonb WHERE id = %s",
            [json.dumps({"tampered": True}), strategy.pk],
        )
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM strategy_reports WHERE id = %s", [strategy.pk])

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE strategy_notes SET text = %s, version = version + 1 WHERE id = %s",
            ["数据库允许用户备注更新", note.pk],
        )
        cursor.execute("DELETE FROM strategy_notes WHERE id = %s", [note.pk])

    assistant_adapter = _ContentAdapter(assistant=True)
    runtime = get_runtime_snapshot(model_key="deepseek", require_available=True)
    with patch(
        "apps.geo.assistant.resolve_assistant_runtime",
        return_value=(runtime, assistant_adapter),
    ):
        reply = respond_to_assistant(
            user_id=user.pk,
            subject_id=subject.pk,
            messages=[{"role": "user", "content": "分析当前主体"}],
            idempotency_key="postgres-assistant-success",
            request_id=uuid.uuid4(),
        )
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE assistant_usage_events SET safe_error_code = 'tampered' WHERE id = %s",
            [reply.usage_event_id],
        )
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM assistant_usage_events WHERE id = %s", [reply.usage_event_id])


def test_postgresql_regeneration_cannot_be_marked_success_before_quota_consumption(
    postgres_stage_facts,
):
    first_adapter = _ContentAdapter()
    first = _create(postgres_stage_facts, first_adapter)
    _execute(first, first_adapter)
    regeneration = _create(postgres_stage_facts, _ContentAdapter(), regenerate=True)
    assert claim_strategy_report(strategy_id=regeneration.pk) is not None

    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE strategy_reports
               SET status = 'succeeded', ai_body = %s::jsonb,
                   usage_summary = %s::jsonb, generated_at = NOW(), finished_at = NOW()
             WHERE id = %s
            """,
            [
                json.dumps(
                    {
                        "overview": "forged",
                        "priorities": [],
                        "schedule": [],
                        "article_topics": [],
                    }
                ),
                json.dumps({"request_count": 1}),
                regeneration.pk,
            ],
        )
