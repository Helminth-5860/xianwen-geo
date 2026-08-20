from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db


def test_postgresql_geo_tables_constraints_and_immutability_triggers_are_installed():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-specific integration evidence")
    expected_tables = {
        "geo_detection_jobs",
        "geo_detection_snapshots",
        "geo_detection_question_snapshots",
        "geo_detection_model_runs",
        "model_calls",
        "model_call_attempts",
        "model_responses",
        "model_response_citations",
        "programmatic_score_results",
        "score_results",
        "model_scores",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() "
            "AND tablename = ANY(%s)",
            [sorted(expected_tables)],
        )
        assert {row[0] for row in cursor.fetchall()} == expected_tables
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
            "AND tgname LIKE 'geo_%' ORDER BY tgname"
        )
        triggers = {row[0] for row in cursor.fetchall()}
    assert {
        "geo_detection_jobs_no_delete",
        "geo_detection_snapshots_immutable",
        "geo_question_snapshots_immutable",
        "geo_model_runs_no_delete",
        "geo_model_calls_no_delete",
        "geo_model_call_attempts_no_delete",
        "geo_model_responses_immutable",
        "geo_model_response_citations_immutable",
        "geo_programmatic_scores_immutable",
        "geo_score_results_immutable",
        "geo_model_scores_immutable",
    }.issubset(triggers)
