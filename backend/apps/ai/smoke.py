from __future__ import annotations

import json

from .contracts import AIAdapterResponse
from .detection import DetectionOutput


def safe_smoke_summary(*, provider_key: str, response: AIAdapterResponse[DetectionOutput]) -> str:
    """Serialize the fixed allowlist for operator smoke output.

    Never add prompts, generated text, credentials, provider payloads, or headers here.
    """

    return json.dumps(
        {
            "status": "PASS",
            "provider": provider_key,
            "model": response.output.provider_model_id,
            "finish_reason": response.finish_reason.value,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "latency_ms": response.timing.latency_ms,
            "answer_chars": len(response.output.raw_text),
            "citation_count": len(response.output.citations),
            "web_search_used": response.output.web_search_used,
            "degraded": response.output.degraded,
            "provider_request_id": response.provider_request_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
