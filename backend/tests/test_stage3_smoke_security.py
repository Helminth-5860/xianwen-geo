import json
from pathlib import Path

from apps.ai.contracts import (
    AIAdapterResponse,
    AIAdapterTiming,
    AIFinishReason,
    AIModelIdentity,
    AIUsage,
)
from apps.ai.detection import DetectionOutput
from apps.ai.smoke import safe_smoke_summary


def test_smoke_summary_serializes_only_frozen_safe_fields():
    secret_answer = "do-not-print-answer-body"
    response = AIAdapterResponse(
        request_id="request-1",
        identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
        output=DetectionOutput(provider_model_id="deepseek-chat", raw_text=secret_answer),
        provider_request_id="provider-request-1",
        usage=AIUsage(input_tokens=12, output_tokens=8, total_tokens=20),
        timing=AIAdapterTiming(latency_ms=320),
        finish_reason=AIFinishReason.STOP,
    )

    serialized = safe_smoke_summary(provider_key="deepseek", response=response)
    payload = json.loads(serialized)

    assert payload == {
        "answer_chars": len(secret_answer),
        "citation_count": 0,
        "degraded": False,
        "finish_reason": "stop",
        "input_tokens": 12,
        "latency_ms": 320,
        "model": "deepseek-chat",
        "output_tokens": 8,
        "provider": "deepseek",
        "provider_request_id": "provider-request-1",
        "status": "PASS",
        "web_search_used": False,
    }
    assert secret_answer not in serialized
    for forbidden in ("prompt", "authorization", "api_key", "reasoning_content", "raw_text"):
        assert forbidden not in serialized.lower()


def test_deepseek_smoke_keeps_input_compatibility_but_never_prints_the_question():
    command = (
        Path(__file__).resolve().parents[1]
        / "apps/ai/management/commands/smoke_deepseek_detection.py"
    ).read_text(encoding="utf-8")
    assert 'parser.add_argument("--question", default=SMOKE_QUESTION)' in command
    assert 'user_question=options["question"]' in command
    assert 'f"question=' not in command
