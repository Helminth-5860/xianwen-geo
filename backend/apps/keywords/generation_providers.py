from __future__ import annotations

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

from .generation_contracts import (
    GeneratedKeyword,
    KeywordGenerationRequest,
    KeywordGenerationResponse,
)
from .generation_exceptions import (
    KeywordGenerationProviderError,
    KeywordGenerationProviderUnavailable,
)


class MockKeywordGenerationProvider(
    DeterministicMockAIAdapter[KeywordGenerationRequest, KeywordGenerationResponse]
):
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="mock", model_key="mock-keyword-generation-v1"),
        capabilities=frozenset({AIModelCapability.KEYWORD_GENERATION}),
        adapter_version="1",
        prompt_version="keyword-generation-v1",
        is_mock=True,
    )
    key = descriptor.identity.provider_key
    model_key = descriptor.identity.model_key
    adapter_version = descriptor.adapter_version
    prompt_version = descriptor.prompt_version

    def _scenario(self) -> str:
        return getattr(settings, "KEYWORD_GENERATION_MOCK_SCENARIO", "success")

    def _build_output(
        self,
        request: KeywordGenerationRequest,
        scenario: str,
    ) -> KeywordGenerationResponse:
        official_name = str(request.subject_values.get("official_name") or "主体")
        structures = []
        if request.include_short:
            structures.append("short")
        if request.include_long_tail:
            structures.append("long_tail")
        if not structures:
            structures.append("general")
        items = []
        start = len(request.historical_exclusions)
        for index in range(request.target_count):
            structure = structures[index % len(structures)]
            regional = request.include_regional and bool(request.regions) and index % 2 == 1
            region = request.regions[index % len(request.regions)] if regional else None
            text = f"{official_name} 关键词 {start + index + 1}"
            if region:
                text = f"{region} {text}"
            items.append(
                GeneratedKeyword(
                    text=text,
                    structure_type=structure,
                    is_regional=regional,
                    region_level="custom" if regional else None,
                    region_text=region,
                    base_keyword=None,
                    business_category="general",
                    search_intent="commercial",
                    relevance_score=max(0, 100 - index),
                    priority="high" if index < 3 else "medium",
                    ai_reason=f"Mock generation reason {index + 1}",
                )
            )
        if scenario == "invalid_response":
            return KeywordGenerationResponse(
                items=(
                    GeneratedKeyword(
                        text="invalid",
                        structure_type="invalid",
                        is_regional=False,
                        region_level=None,
                        region_text=None,
                        base_keyword=None,
                        business_category="",
                        search_intent="invalid",
                        relevance_score=101,
                        priority="invalid",
                        ai_reason="",
                    ),
                ),
                model_key=self.model_key,
                provider_metrics={},
            )
        if scenario == "duplicate" and items:
            items.append(items[0])
        return KeywordGenerationResponse(
            items=tuple(items),
            model_key=self.model_key,
            provider_metrics={"mock": True, "item_count": len(items)},
        )

    def generate(self, request: KeywordGenerationRequest) -> KeywordGenerationResponse:
        normalized = self.normalized_request(
            request,
            request_id=request.job_id,
            timeout_seconds=settings.KEYWORD_GENERATION_PROVIDER_TIMEOUT_SECONDS,
        )
        try:
            response = self.invoke(normalized)
        except AIAdapterError as exc:
            raise KeywordGenerationProviderError(
                domain_provider_error_code(exc, "KEYWORD_GENERATION_PROVIDER"),
                permanent=not exc.retryable,
            ) from None
        return replace(
            response.output,
            provider_metrics=dict(response.sanitized_provider_metadata),
        )


class UnavailableKeywordGenerationProvider:
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="unavailable", model_key="unavailable"),
        capabilities=frozenset({AIModelCapability.KEYWORD_GENERATION}),
        adapter_version="1",
        prompt_version="keyword-generation-v1",
        is_available=False,
    )
    key = descriptor.identity.provider_key
    model_key = descriptor.identity.model_key
    adapter_version = descriptor.adapter_version
    prompt_version = descriptor.prompt_version

    def invoke(
        self,
        request: AIAdapterRequest[KeywordGenerationRequest],
    ) -> AIAdapterResponse[KeywordGenerationResponse]:
        raise AIAdapterError(AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE, retryable=False)

    def generate(self, request: KeywordGenerationRequest) -> KeywordGenerationResponse:
        raise KeywordGenerationProviderUnavailable


model_registry.register(MockKeywordGenerationProvider.descriptor, MockKeywordGenerationProvider)
model_registry.register(
    UnavailableKeywordGenerationProvider.descriptor,
    UnavailableKeywordGenerationProvider,
)


def get_keyword_generation_provider(provider_key: str | None = None):
    key = provider_key or settings.KEYWORD_GENERATION_PROVIDER
    try:
        return model_registry.resolve_provider(
            provider_key=key,
            capability=AIModelCapability.KEYWORD_GENERATION,
        )
    except AIAdapterError:
        raise KeywordGenerationProviderUnavailable from None


def require_available_keyword_generation_provider():
    provider = get_keyword_generation_provider()
    if not provider.descriptor.is_available:
        raise KeywordGenerationProviderUnavailable
    return provider
