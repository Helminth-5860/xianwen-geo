from __future__ import annotations

from apps.ai.registry import AIModelRegistry, model_registry

from .deepseek import register_deepseek_adapter
from .doubao import register_doubao_adapter


def register_real_detection_adapters(registry: AIModelRegistry = model_registry) -> None:
    register_deepseek_adapter(registry)
    register_doubao_adapter(registry)
