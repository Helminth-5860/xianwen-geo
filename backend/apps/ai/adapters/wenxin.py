from __future__ import annotations

from apps.ai.registry import AIModelRegistry, model_registry

from .openai_chat import OpenAIChatProviderSpec, OpenAICompatibleDetectionAdapter

WENXIN_SPEC = OpenAIChatProviderSpec(
    provider_key="wenxin",
    model_key="wenxin",
    base_url="https://qianfan.baidubce.com/v2",
    adapter_version="wenxin-qianfan-chat-v2",
)
WENXIN_DESCRIPTOR = WENXIN_SPEC.descriptor()


class WenxinDetectionAdapter(OpenAICompatibleDetectionAdapter):
    spec = WENXIN_SPEC
    descriptor = WENXIN_DESCRIPTOR


def register_wenxin_adapter(registry: AIModelRegistry = model_registry) -> None:
    registry.register(WENXIN_DESCRIPTOR, WenxinDetectionAdapter)
