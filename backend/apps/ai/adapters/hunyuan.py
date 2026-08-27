from __future__ import annotations

from apps.ai.registry import AIModelRegistry, model_registry

from .openai_chat import OpenAIChatProviderSpec, OpenAICompatibleDetectionAdapter

HUNYUAN_SPEC = OpenAIChatProviderSpec(
    provider_key="hunyuan",
    model_key="hunyuan",
    base_url="https://tokenhub.tencentmaas.com/v1",
    adapter_version="hunyuan-openai-chat-v1",
)
HUNYUAN_DESCRIPTOR = HUNYUAN_SPEC.descriptor()


class HunyuanDetectionAdapter(OpenAICompatibleDetectionAdapter):
    spec = HUNYUAN_SPEC
    descriptor = HUNYUAN_DESCRIPTOR


def register_hunyuan_adapter(registry: AIModelRegistry = model_registry) -> None:
    registry.register(HUNYUAN_DESCRIPTOR, HunyuanDetectionAdapter)
