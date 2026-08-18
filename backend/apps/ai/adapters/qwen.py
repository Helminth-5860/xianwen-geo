from __future__ import annotations

from apps.ai.registry import AIModelRegistry, model_registry

from .openai_chat import OpenAIChatProviderSpec, OpenAICompatibleDetectionAdapter

QWEN_SPEC = OpenAIChatProviderSpec(
    provider_key="qwen",
    model_key="qwen",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    adapter_version="qwen-openai-chat-v1",
)
QWEN_DESCRIPTOR = QWEN_SPEC.descriptor()


class QwenDetectionAdapter(OpenAICompatibleDetectionAdapter):
    spec = QWEN_SPEC
    descriptor = QWEN_DESCRIPTOR


def register_qwen_adapter(registry: AIModelRegistry = model_registry) -> None:
    registry.register(QWEN_DESCRIPTOR, QwenDetectionAdapter)
