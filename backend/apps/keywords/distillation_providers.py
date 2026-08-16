from __future__ import annotations

import uuid
from dataclasses import replace

from django.conf import settings

from apps.ai.contracts import (
    AIAdapterDescriptor,
    AIAdapterRequest,
    AIAdapterResponse,
    AIModelCapability,
    AIModelIdentity,
)
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory, domain_provider_error_code
from apps.ai.mock import DeterministicMockAIAdapter
from apps.ai.registry import model_registry

from .distillation_contracts import DistillationRequest, DistillationResponse, DistilledKeyword
from .distillation_exceptions import DistillationProviderError, DistillationProviderUnavailable


class MockDistillationProvider(
    DeterministicMockAIAdapter[DistillationRequest, DistillationResponse]
):
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(
            provider_key="mock",
            model_key="mock-keyword-distillation-v1",
        ),
        capabilities=frozenset({AIModelCapability.KEYWORD_DISTILLATION}),
        adapter_version="1",
        prompt_version="keyword-distillation-v1",
        is_mock=True,
    )
    key = descriptor.identity.provider_key
    model_key = descriptor.identity.model_key
    adapter_version = descriptor.adapter_version
    prompt_version = descriptor.prompt_version

    def _scenario(self) -> str:
        return getattr(settings, "DISTILLATION_MOCK_SCENARIO", "success")

    def _build_output(
        self,
        request: DistillationRequest,
        scenario: str,
    ) -> DistillationResponse:
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

    def distill(self, request: DistillationRequest) -> DistillationResponse:
        normalized = self.normalized_request(
            request,
            request_id=request.job_id,
            timeout_seconds=settings.DISTILLATION_PROVIDER_TIMEOUT_SECONDS,
        )
        try:
            response = self.invoke(normalized)
        except AIAdapterError as exc:
            raise DistillationProviderError(
                domain_provider_error_code(exc, "DISTILLATION_PROVIDER"),
                permanent=not exc.retryable,
            ) from None
        return replace(
            response.output,
            provider_metrics=dict(response.sanitized_provider_metadata),
        )


class UnavailableDistillationProvider:
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="unavailable", model_key="unavailable"),
        capabilities=frozenset({AIModelCapability.KEYWORD_DISTILLATION}),
        adapter_version="1",
        prompt_version="keyword-distillation-v1",
        is_available=False,
    )
    key = descriptor.identity.provider_key
    model_key = descriptor.identity.model_key
    adapter_version = descriptor.adapter_version
    prompt_version = descriptor.prompt_version

    def invoke(
        self,
        request: AIAdapterRequest[DistillationRequest],
    ) -> AIAdapterResponse[DistillationResponse]:
        raise AIAdapterError(AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE, retryable=False)

    def distill(self, request: DistillationRequest) -> DistillationResponse:
        raise DistillationProviderUnavailable


model_registry.register(MockDistillationProvider.descriptor, MockDistillationProvider)
model_registry.register(
    UnavailableDistillationProvider.descriptor,
    UnavailableDistillationProvider,
)


def get_distillation_provider(provider_key: str | None = None):
    key = provider_key or settings.DISTILLATION_PROVIDER
    try:
        return model_registry.resolve_provider(
            provider_key=key,
            capability=AIModelCapability.KEYWORD_DISTILLATION,
        )
    except AIAdapterError:
        raise DistillationProviderUnavailable from None


def require_available_distillation_provider():
    provider = get_distillation_provider()
    if not provider.descriptor.is_available:
        raise DistillationProviderUnavailable
    return provider
