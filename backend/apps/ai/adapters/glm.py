from __future__ import annotations

from apps.ai.registry import AIModelRegistry, model_registry

from .openai_chat import OpenAIChatProviderSpec, OpenAICompatibleDetectionAdapter

GLM_SPEC = OpenAIChatProviderSpec(
    provider_key="glm",
    model_key="glm",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    adapter_version="glm-openai-chat-v4",
)
GLM_DESCRIPTOR = GLM_SPEC.descriptor()


class GLMDetectionAdapter(OpenAICompatibleDetectionAdapter):
    spec = GLM_SPEC
    descriptor = GLM_DESCRIPTOR


def register_glm_adapter(registry: AIModelRegistry = model_registry) -> None:
    registry.register(GLM_DESCRIPTOR, GLMDetectionAdapter)
