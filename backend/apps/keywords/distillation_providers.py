from __future__ import annotations

import uuid

from django.conf import settings

from .distillation_contracts import DistillationRequest, DistillationResponse, DistilledKeyword
from .distillation_exceptions import DistillationProviderError, DistillationProviderUnavailable


class MockDistillationProvider:
    key = "mock"
    model_key = "mock-keyword-distillation-v1"
    adapter_version = "1"
    prompt_version = "keyword-distillation-v1"

    def distill(self, request: DistillationRequest) -> DistillationResponse:
        scenario = getattr(settings, "DISTILLATION_MOCK_SCENARIO", "success")
        if scenario == "timeout":
            raise DistillationProviderError("DISTILLATION_PROVIDER_TIMEOUT", permanent=False)
        if scenario == "rate_limit":
            raise DistillationProviderError("DISTILLATION_PROVIDER_RATE_LIMITED", permanent=False)
        if scenario == "temporary":
            raise DistillationProviderError("DISTILLATION_PROVIDER_TEMPORARY", permanent=False)
        if scenario == "permanent":
            raise DistillationProviderError("DISTILLATION_PROVIDER_REJECTED", permanent=True)

        group_key = str(uuid.uuid5(uuid.UUID(request.job_id), "merge-group-1"))
        canonical = request.keywords[1].id if len(request.keywords) >= 5 else None
        items = []
        for index, keyword in enumerate(request.keywords):
            action = "keep"
            canonical_id = None
            merge_key = None
            if len(request.keywords) >= 5:
                if index in (1, 2):
                    action = "merge"
                    canonical_id = canonical
                    merge_key = group_key
                elif index == 3:
                    action = "delete"
                elif index >= 4:
                    action = "low_value"
            items.append(
                DistilledKeyword(
                    source_keyword_id=keyword.id,
                    action=action,
                    canonical_keyword_id=canonical_id,
                    merge_group_key=merge_key,
                    reason=f"Mock distillation reason {index + 1}",
                )
            )
        if scenario == "invalid_response" and items:
            items = items[:-1]
        return DistillationResponse(
            items=tuple(items),
            model_key=self.model_key,
            provider_metrics={"mock": True, "item_count": len(items)},
        )


class UnavailableDistillationProvider:
    key = "unavailable"
    model_key = "unavailable"
    adapter_version = "1"
    prompt_version = "keyword-distillation-v1"

    def distill(self, request: DistillationRequest) -> DistillationResponse:
        raise DistillationProviderUnavailable


def get_distillation_provider(provider_key: str | None = None):
    key = provider_key or settings.DISTILLATION_PROVIDER
    if key == "mock":
        return MockDistillationProvider()
    if key == "unavailable":
        return UnavailableDistillationProvider()
    raise DistillationProviderUnavailable


def require_available_distillation_provider():
    provider = get_distillation_provider()
    if provider.key == "unavailable":
        raise DistillationProviderUnavailable
    return provider
