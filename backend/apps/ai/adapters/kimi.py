from __future__ import annotations

from apps.ai.detection import DetectionPayload
from apps.ai.registry import AIModelRegistry, model_registry

from .openai_chat import OpenAIChatProviderSpec, OpenAICompatibleDetectionAdapter

KIMI_SPEC = OpenAIChatProviderSpec(
    provider_key="kimi",
    model_key="kimi",
    base_url="https://api.moonshot.cn/v1",
    adapter_version="kimi-openai-chat-v1",
)
KIMI_DESCRIPTOR = KIMI_SPEC.descriptor()


class KimiDetectionAdapter(OpenAICompatibleDetectionAdapter):
    spec = KIMI_SPEC
    descriptor = KIMI_DESCRIPTOR

    def _request_body(self, payload: DetectionPayload) -> dict[str, object]:
        body = super()._request_body(payload)
        if payload.provider_model_id == "kimi-k2.6":
            # K2.6 rejects arbitrary temperatures. Non-thinking mode is a better fit for
            # short, independent GEO detection questions and avoids unnecessary latency.
            body.pop("temperature", None)
            body["thinking"] = {"type": "disabled"}
        elif payload.provider_model_id == "kimi-k3":
            # K3 has fixed sampling parameters and rejects an explicit non-default value.
            body.pop("temperature", None)
            body["reasoning_effort"] = "low"
        return body


def register_kimi_adapter(registry: AIModelRegistry = model_registry) -> None:
    registry.register(KIMI_DESCRIPTOR, KimiDetectionAdapter)
