from __future__ import annotations

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


def register_kimi_adapter(registry: AIModelRegistry = model_registry) -> None:
    registry.register(KIMI_DESCRIPTOR, KimiDetectionAdapter)
