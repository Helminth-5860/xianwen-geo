from __future__ import annotations

from apps.ai.contracts import AIAdapterRequest
from apps.ai.detection import DetectionPayload
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.registry import AIModelRegistry, model_registry

from .openai_chat import OpenAIChatProviderSpec, OpenAICompatibleDetectionAdapter

SPARK_SPEC = OpenAIChatProviderSpec(
    provider_key="spark",
    model_key="spark",
    base_url="https://spark-api-open.xf-yun.com/v1",
    adapter_version="spark-openai-chat-v1",
)
SPARK_DESCRIPTOR = SPARK_SPEC.descriptor()


class SparkDetectionAdapter(OpenAICompatibleDetectionAdapter):
    spec = SPARK_SPEC
    descriptor = SPARK_DESCRIPTOR

    def _provider_success_guard(self, data: dict[str, object]) -> None:
        code = data.get("code")
        if code in (None, 0):
            return
        if code in {10013, 10014, 10019}:
            category = AIAdapterErrorCategory.CONTENT_POLICY
            stable_code = "AI_SPARK_CONTENT_POLICY"
        elif code in {11201, 11202, 11203, 10007}:
            category = AIAdapterErrorCategory.RATE_LIMIT
            stable_code = "AI_SPARK_RATE_LIMIT"
        elif code == 11200:
            category = AIAdapterErrorCategory.PERMISSION
            stable_code = "AI_SPARK_PERMISSION"
        elif code == 10907:
            category = AIAdapterErrorCategory.INVALID_REQUEST
            stable_code = "AI_SPARK_INVALID_REQUEST"
        else:
            category = AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE
            stable_code = "AI_SPARK_REQUEST_REJECTED"
        raise AIAdapterError(category, stable_code=stable_code)

    def _provider_model_id(
        self,
        data: dict[str, object],
        request: AIAdapterRequest[DetectionPayload],
    ) -> str | None:
        provider_model_id = super()._provider_model_id(data, request)
        return provider_model_id or request.payload.provider_model_id

    def _provider_request_id(self, data: dict[str, object]) -> str | None:
        return super()._provider_request_id(data) or self._safe_sid(data)

    @staticmethod
    def _safe_sid(data: dict[str, object]) -> str | None:
        sid = data.get("sid")
        if not isinstance(sid, str) or not sid or len(sid) > 128:
            return None
        if any(ord(character) < 32 for character in sid):
            return None
        return sid


def register_spark_adapter(registry: AIModelRegistry = model_registry) -> None:
    registry.register(SPARK_DESCRIPTOR, SparkDetectionAdapter)
