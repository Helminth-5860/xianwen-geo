from __future__ import annotations

from unittest.mock import patch

import pytest
from celery.exceptions import Retry

from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.geo.score_aggregation import ScoreAggregationError
from apps.geo.score_orchestration import ScoreOrchestrationError
from apps.geo.tasks import execute_semantic_score_task


@pytest.mark.parametrize(
    "error",
    [
        AIAdapterError(
            AIAdapterErrorCategory.RESPONSE_PARSE,
            stable_code="AI_SEMANTIC_RESPONSE_INVALID",
            retryable=False,
        ),
        ScoreAggregationError("frozen scale mismatch"),
        ScoreOrchestrationError("invalid semantic contract"),
    ],
)
def test_semantic_task_does_not_retry_deterministic_failures(error) -> None:
    with (
        patch("apps.geo.tasks.score_model_response", side_effect=error),
        patch.object(execute_semantic_score_task, "retry") as retry,
    ):
        result = execute_semantic_score_task.run("response-1")

    assert result == {"status": "failed"}
    retry.assert_not_called()


def test_semantic_task_retries_retryable_adapter_failures() -> None:
    error = AIAdapterError(
        AIAdapterErrorCategory.NETWORK,
        stable_code="AI_SEMANTIC_NETWORK",
        retryable=True,
    )
    with (
        patch("apps.geo.tasks.score_model_response", side_effect=error),
        patch.object(execute_semantic_score_task, "retry", side_effect=Retry()) as retry,
        pytest.raises(Retry),
    ):
        execute_semantic_score_task.run("response-1")

    assert retry.call_args.kwargs["args"] == ["response-1"]
