from __future__ import annotations

from apps.ai.registry import AIModelRegistry, model_registry

from .deepseek import register_deepseek_adapter
from .deepseek_content import register_deepseek_content_adapters
from .doubao import register_doubao_adapter
from .glm import register_glm_adapter
from .hunyuan import register_hunyuan_adapter
from .kimi import register_kimi_adapter
from .qwen import register_qwen_adapter
from .spark import register_spark_adapter
from .wenxin import register_wenxin_adapter


def register_real_detection_adapters(registry: AIModelRegistry = model_registry) -> None:
    register_deepseek_adapter(registry)
    register_deepseek_content_adapters(registry)
    register_doubao_adapter(registry)
    register_qwen_adapter(registry)
    register_hunyuan_adapter(registry)
    register_wenxin_adapter(registry)
    register_kimi_adapter(registry)
    register_glm_adapter(registry)
    register_spark_adapter(registry)
