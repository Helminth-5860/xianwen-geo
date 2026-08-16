from __future__ import annotations

from abc import ABC, abstractmethod
from time import monotonic

from .contracts import (
    AIAdapterDescriptor,
    AIAdapterRequest,
    AIAdapterResponse,
    AIAdapterTiming,
    AIFinishReason,
    AIUsage,
)
from .errors import AIAdapterError, AIAdapterErrorCategory
from .sanitization import sanitize_provider_metrics

MOCK_ERROR_SCENARIOS = {
    "timeout": AIAdapterErrorCategory.TIMEOUT,
    "rate_limit": AIAdapterErrorCategory.RATE_LIMIT,
    "temporary": AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
    "permanent": AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE,
}
MOCK_OUTPUT_SCENARIOS = frozenset({"success", "invalid_response", "duplicate", "low_confidence"})


class DeterministicMockAIAdapter[RequestT, ResponseT](ABC):
    descriptor: AIAdapterDescriptor

    @abstractmethod
    def _scenario(self) -> str: ...

    @abstractmethod
    def _build_output(self, payload: RequestT, scenario: str) -> ResponseT: ...

    def invoke(self, request: AIAdapterRequest[RequestT]) -> AIAdapterResponse[ResponseT]:
        if (
            request.identity != self.descriptor.identity
            or request.capability not in self.descriptor.capabilities
            or request.adapter_version != self.descriptor.adapter_version
            or request.prompt_version != self.descriptor.prompt_version
        ):
            raise AIAdapterError(AIAdapterErrorCategory.INVALID_REQUEST, retryable=False)

        scenario = self._scenario()
        category = MOCK_ERROR_SCENARIOS.get(scenario)
        if category is not None:
            raise AIAdapterError(category)
        if scenario not in MOCK_OUTPUT_SCENARIOS:
            raise AIAdapterError(
                AIAdapterErrorCategory.INTERNAL_ADAPTER,
                stable_code="AI_MOCK_SCENARIO_INVALID",
                retryable=False,
            )

        started = monotonic()
        output = self._build_output(request.payload, scenario)
        metrics = sanitize_provider_metrics(getattr(output, "provider_metrics", {}))
        latency_ms = max(0, int((monotonic() - started) * 1000))
        if "latency_ms" in metrics:
            latency_ms = int(metrics["latency_ms"])
        usage = AIUsage(
            input_tokens=_int_metric(metrics, "input_tokens"),
            output_tokens=_int_metric(metrics, "output_tokens"),
            total_tokens=_int_metric(metrics, "total_tokens"),
        )
        return AIAdapterResponse(
            request_id=request.request_id,
            identity=self.descriptor.identity,
            output=output,
            usage=usage,
            timing=AIAdapterTiming(latency_ms=latency_ms),
            finish_reason=AIFinishReason.STOP,
            sanitized_provider_metadata=metrics,
        )

    def normalized_request(
        self,
        payload: RequestT,
        *,
        request_id: str,
        timeout_seconds: int,
        correlation_id: str | None = None,
    ) -> AIAdapterRequest[RequestT]:
        return AIAdapterRequest(
            request_id=request_id,
            correlation_id=correlation_id,
            identity=self.descriptor.identity,
            capability=next(iter(self.descriptor.capabilities)),
            adapter_version=self.descriptor.adapter_version,
            prompt_version=self.descriptor.prompt_version,
            timeout_seconds=timeout_seconds,
            payload=payload,
        )


def _int_metric(metrics: dict[str, bool | int], key: str) -> int | None:
    value = metrics.get(key)
    return value if type(value) is int else None
