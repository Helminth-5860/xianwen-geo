from __future__ import annotations

from django.conf import settings

from .generation_contracts import (
    GeneratedKeyword,
    KeywordGenerationRequest,
    KeywordGenerationResponse,
)
from .generation_exceptions import (
    KeywordGenerationProviderError,
    KeywordGenerationProviderUnavailable,
)


class MockKeywordGenerationProvider:
    key = "mock"
    model_key = "mock-keyword-generation-v1"
    adapter_version = "1"
    prompt_version = "keyword-generation-v1"

    def generate(self, request: KeywordGenerationRequest) -> KeywordGenerationResponse:
        scenario = getattr(settings, "KEYWORD_GENERATION_MOCK_SCENARIO", "success")
        if scenario == "timeout":
            raise KeywordGenerationProviderError(
                "KEYWORD_GENERATION_PROVIDER_TIMEOUT", permanent=False
            )
        if scenario == "rate_limit":
            raise KeywordGenerationProviderError(
                "KEYWORD_GENERATION_PROVIDER_RATE_LIMITED", permanent=False
            )
        if scenario == "temporary":
            raise KeywordGenerationProviderError(
                "KEYWORD_GENERATION_PROVIDER_TEMPORARY", permanent=False
            )
        if scenario == "permanent":
            raise KeywordGenerationProviderError(
                "KEYWORD_GENERATION_PROVIDER_REJECTED", permanent=True
            )

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


class UnavailableKeywordGenerationProvider:
    key = "unavailable"
    model_key = "unavailable"
    adapter_version = "1"
    prompt_version = "keyword-generation-v1"

    def generate(self, request: KeywordGenerationRequest) -> KeywordGenerationResponse:
        raise KeywordGenerationProviderUnavailable


def get_keyword_generation_provider(provider_key: str | None = None):
    key = provider_key or settings.KEYWORD_GENERATION_PROVIDER
    if key == "mock":
        return MockKeywordGenerationProvider()
    if key == "unavailable":
        return UnavailableKeywordGenerationProvider()
    raise KeywordGenerationProviderUnavailable


def require_available_keyword_generation_provider():
    provider = get_keyword_generation_provider()
    if provider.key == "unavailable":
        raise KeywordGenerationProviderUnavailable
    return provider
