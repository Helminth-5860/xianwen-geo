from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command

from apps.ai.adapters.deepseek import DeepSeekDetectionAdapter
from apps.ai.contracts import (
    AIAdapterResponse,
    AIAdapterTiming,
    AIFinishReason,
    AIUsage,
)
from apps.ai.detection import DetectionOutput
from apps.ai.management.commands import smoke_deepseek_detection


def test_deepseek_smoke_success_prints_only_safe_summary(monkeypatch):
    sensitive_question = "QUESTION_BODY_MUST_NOT_LEAK"
    sensitive_answer = "ANSWER_BODY_MUST_NOT_LEAK"
    sensitive_raw_provider_value = "RAW_PROVIDER_JSON_MUST_NOT_LEAK"
    adapter = DeepSeekDetectionAdapter()
    captured = {}

    def fake_invoke(request):
        captured["request"] = request
        return AIAdapterResponse(
            request_id=request.request_id,
            identity=request.identity,
            output=DetectionOutput(
                provider_model_id="deepseek-v4-safe",
                raw_text=sensitive_answer,
                citations=(),
                web_search_requested=False,
                web_search_used=False,
                degraded=True,
            ),
            provider_request_id="safe-provider-request-id",
            usage=AIUsage(input_tokens=7, output_tokens=5, total_tokens=12),
            timing=AIAdapterTiming(latency_ms=19),
            finish_reason=AIFinishReason.STOP,
            sanitized_provider_metadata={"safe_marker": sensitive_raw_provider_value},
        )

    monkeypatch.setattr(adapter, "invoke", fake_invoke)
    monkeypatch.setattr(
        smoke_deepseek_detection,
        "resolve_detection_adapter",
        lambda **kwargs: (
            SimpleNamespace(timeout_seconds=10, provider_model_id="deepseek-v4-safe"),
            adapter,
        ),
    )
    stdout = StringIO()

    call_command(
        "smoke_deepseek_detection",
        question=sensitive_question,
        stdout=stdout,
    )

    output = stdout.getvalue()
    assert captured["request"].payload.user_question == sensitive_question
    assert "DeepSeek smoke PASS" in output
    assert "degraded=True" in output
    assert "provider_request_id=safe-provider-request-id" in output
    for forbidden in (
        sensitive_question,
        sensitive_answer,
        sensitive_raw_provider_value,
        "Authorization",
        "system_prompt",
        "user_question",
        "raw_text",
        "reasoning_content",
    ):
        assert forbidden not in output
