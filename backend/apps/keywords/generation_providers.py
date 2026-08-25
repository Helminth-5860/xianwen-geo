from __future__ import annotations

from dataclasses import replace

from django.conf import settings

from apps.ai.adapters.deepseek_content import DeepSeekStructuredContentAdapter
from apps.ai.content import StructuredContentPayload
from apps.ai.contracts import (
    AIAdapterDescriptor,
    AIAdapterRequest,
    AIAdapterResponse,
    AIModelCapability,
    AIModelIdentity,
)
from apps.ai.credentials import CapabilityDatabaseCredentialResolver
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory, domain_provider_error_code
from apps.ai.mock import DeterministicMockAIAdapter
from apps.ai.registry import model_registry
from apps.ai.runtime import get_capability_runtime_snapshot

from .generation_contracts import (
    GeneratedKeyword,
    KeywordGenerationRequest,
    KeywordGenerationResponse,
)
from .generation_exceptions import (
    KeywordGenerationInvalidResponse,
    KeywordGenerationProviderError,
    KeywordGenerationProviderUnavailable,
)

DEEPSEEK_KEYWORD_SYSTEM_PROMPT = """
你是企业 GEO 关键词规划助手。只返回一个 JSON 对象，不要返回 Markdown 或解释文字。
顶层格式必须是 {"items": [...]}，items 数量必须严格等于 target_count。
每项必须包含：text、structure_type、is_regional、region_level、region_text、
base_keyword、business_category、search_intent、relevance_score、priority、ai_reason。
structure_type 只能是 short、long_tail、general；search_intent 只能是
informational、navigational、commercial、transactional；priority 只能是 high、medium、low；
relevance_score 必须是 0 到 100 的整数。未使用的可选字段返回 null。
不得生成 exclusions 中已经存在的关键词；地域词只能使用请求提供的 regions。
""".strip()


def _required_text(row, key):
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise KeywordGenerationInvalidResponse
    return value


def _optional_text(row, key):
    value = row.get(key)
    if value is not None and not isinstance(value, str):
        raise KeywordGenerationInvalidResponse
    return value


class DeepSeekKeywordGenerationProvider(DeepSeekStructuredContentAdapter):
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
        capabilities=frozenset({AIModelCapability.KEYWORD_GENERATION}),
        adapter_version="deepseek-keyword-generation-v1",
        prompt_version="keyword-generation-v1",
    )
    key = descriptor.identity.provider_key
    model_key = descriptor.identity.model_key
    adapter_version = descriptor.adapter_version
    prompt_version = descriptor.prompt_version

    def __init__(self, *, credential_resolver=None, transport=None, runtime_resolver=None):
        super().__init__(
            credential_resolver=credential_resolver
            or CapabilityDatabaseCredentialResolver(
                capability=AIModelCapability.KEYWORD_GENERATION
            ),
            transport=transport,
        )
        self._runtime_resolver = runtime_resolver or get_capability_runtime_snapshot

    def ensure_available(self):
        try:
            runtime = self._runtime_resolver(
                provider_key=self.key,
                capability=AIModelCapability.KEYWORD_GENERATION,
            )
            self._credential()
        except AIAdapterError:
            raise KeywordGenerationProviderUnavailable from None
        return runtime

    @staticmethod
    def _items(content):
        if not isinstance(content, dict) or not isinstance(content.get("items"), list):
            raise KeywordGenerationInvalidResponse
        output = []
        for row in content["items"]:
            if not isinstance(row, dict):
                raise KeywordGenerationInvalidResponse
            is_regional = row.get("is_regional")
            relevance_score = row.get("relevance_score")
            if type(is_regional) is not bool or type(relevance_score) is not int:
                raise KeywordGenerationInvalidResponse
            output.append(
                GeneratedKeyword(
                    text=_required_text(row, "text"),
                    structure_type=_required_text(row, "structure_type"),
                    is_regional=is_regional,
                    region_level=_optional_text(row, "region_level"),
                    region_text=_optional_text(row, "region_text"),
                    base_keyword=_optional_text(row, "base_keyword"),
                    business_category=_required_text(row, "business_category"),
                    search_intent=_required_text(row, "search_intent"),
                    relevance_score=relevance_score,
                    priority=_required_text(row, "priority"),
                    ai_reason=_required_text(row, "ai_reason"),
                )
            )
        return tuple(output)

    def generate(self, request: KeywordGenerationRequest) -> KeywordGenerationResponse:
        runtime = self.ensure_available()
        normalized = AIAdapterRequest(
            request_id=request.job_id,
            correlation_id=request.job_id,
            identity=self.descriptor.identity,
            capability=AIModelCapability.KEYWORD_GENERATION,
            adapter_version=self.adapter_version,
            prompt_version=self.prompt_version,
            timeout_seconds=runtime.timeout_seconds,
            payload=StructuredContentPayload(
                provider_model_id=runtime.provider_model_id,
                system_prompt=DEEPSEEK_KEYWORD_SYSTEM_PROMPT,
                user_payload={
                    "task": "generate_geo_keywords",
                    "subject": request.subject_values,
                    "target_count": request.target_count,
                    "include_short": request.include_short,
                    "include_long_tail": request.include_long_tail,
                    "include_regional": request.include_regional,
                    "regions": list(request.regions),
                    "exclusions": list(request.historical_exclusions),
                },
                max_output_tokens=min(16_000, max(1_200, request.target_count * 180)),
                temperature=0.2,
            ),
        )
        try:
            response = self.invoke(normalized)
        except AIAdapterError as exc:
            raise KeywordGenerationProviderError(
                domain_provider_error_code(exc, "KEYWORD_GENERATION_PROVIDER"),
                permanent=not exc.retryable,
            ) from None
        metrics = dict(response.sanitized_provider_metadata)
        if response.provider_request_id:
            metrics["provider_request_id"] = response.provider_request_id
        if response.usage.total_tokens is not None:
            metrics["total_tokens"] = response.usage.total_tokens
        return KeywordGenerationResponse(
            items=self._items(response.output.content),
            model_key=self.model_key,
            provider_metrics=metrics,
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
    DeepSeekKeywordGenerationProvider.descriptor,
    DeepSeekKeywordGenerationProvider,
)
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
    ensure_available = getattr(provider, "ensure_available", None)
    if ensure_available is not None:
        ensure_available()
    return provider
