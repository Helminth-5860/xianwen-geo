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
from .normalization import (
    KeywordNormalizationError,
    normalize_generated_keyword_items,
    normalize_plain_text,
    normalize_region_entries,
)
from .taxonomy import normalize_category, normalize_intents

DEEPSEEK_KEYWORD_SYSTEM_PROMPT = """
你是企业 GEO 关键词规划助手。只返回 JSON 对象，不要解释。
严格格式：{"items":[{"text":"...","category":"entity","intents":["informational"],
"length_type":"short","regions":[],"base_keyword":null,"notes":"",
"relevance_score":90,"priority":"high","ai_reason":"与主体业务直接相关"}]}。
items 数量必须严格等于 target_count；text 不得为空或重复。
category 只能使用请求给出的 14 类 category_catalog key。
intents 必须是数组，只能使用请求给出的 8 类 intent_catalog key。
length_type 只能是 short 或 long_tail，且必须符合请求的长度类型。
regions 只能使用请求提供的 code/name/level 对象；不限地域时必须为空数组。
base_keyword 只能指向同次返回的另一条关键词；无法确认时必须为 null，严禁自引用。
不得生成 exclusions 中已有关键词。不要输出联系人、电话或其他内部资料。
""".strip()

_ROW_ALIASES = {
    "text": ("text", "keyword", "keyword_text", "name"),
    "category": ("category", "business_category", "keyword_category"),
    "intents": ("intents", "user_intents", "intent", "search_intent"),
    "length_type": ("length_type", "structure_type", "keyword_length", "type"),
    "regions": ("regions", "region", "region_text"),
    "base_keyword": ("base_keyword", "base_keyword_text", "root_keyword"),
    "notes": ("notes", "note", "remark"),
    "relevance_score": ("relevance_score", "score"),
    "priority": ("priority",),
    "ai_reason": ("ai_reason", "reason"),
}
_LENGTH_ALIASES = {
    "short": "short",
    "short_keyword": "short",
    "短关键词": "short",
    "短词": "short",
    "短": "short",
    "long_tail": "long_tail",
    "long-tail": "long_tail",
    "long tail": "long_tail",
    "longtail": "long_tail",
    "long": "long_tail",
    "long_tail_keyword": "long_tail",
    "长尾关键词": "long_tail",
    "长尾词": "long_tail",
    "长尾": "long_tail",
    "general": "general",
    "通用": "general",
    "通用词": "general",
    "通用关键词": "general",
}
_PRIORITY_ALIASES = {
    "high": "high",
    "medium": "medium",
    "low": "low",
    "高": "high",
    "中": "medium",
    "低": "low",
}
_LEGACY_INTENT = {
    "informational": "informational",
    "recommendation": "commercial",
    "transactional": "transactional",
    "navigational": "navigational",
}


def _first(row, key, default=None):
    for alias in _ROW_ALIASES[key]:
        if alias in row:
            return row[alias]
    return default


def _structure_diagnostic(content, reason, *, error_fields=()):
    diagnostic = {
        "actual_structure": {"type": type(content).__name__},
        "expected_structure": "keyword-generation-v3",
        "error_fields": sorted({str(value)[:64] for value in error_fields})[:20],
        "parse_failure_reason": str(reason)[:64],
        "root_cause": "provider_schema_mismatch",
    }
    if isinstance(content, dict):
        diagnostic["actual_structure"]["top_level_keys"] = sorted(str(key)[:64] for key in content)[
            :20
        ]
        rows = content.get("items", content.get("keywords", content.get("data")))
        if isinstance(rows, dict):
            rows = rows.get("items", rows.get("keywords"))
        if isinstance(rows, list):
            diagnostic["actual_structure"]["item_count"] = len(rows)
            dictionaries = [row for row in rows[:5] if isinstance(row, dict)]
            diagnostic["actual_structure"]["item_fields"] = sorted(
                {str(key)[:64] for row in dictionaries for key in row}
            )[:30]
            if dictionaries:
                diagnostic["actual_structure"]["first_item_types"] = {
                    str(key)[:64]: type(value).__name__
                    for key, value in list(dictionaries[0].items())[:20]
                }
    return diagnostic


def _invalid(content, reason, *fields):
    raise KeywordGenerationInvalidResponse(
        reason,
        diagnostic=_structure_diagnostic(content, reason, error_fields=fields),
    )


def _normalized_length_type(raw_value, *, text: str, allowed_lengths: set[str]):
    if not isinstance(raw_value, str):
        return None
    normalized = raw_value.strip().lower()
    length_type = _LENGTH_ALIASES.get(normalized)
    if length_type in allowed_lengths:
        return length_type
    if length_type is None:
        return None
    # DeepSeek occasionally emits the documented legacy value ``general`` or
    # the opposite requested length. Length is presentation metadata rather
    # than a security boundary, so coerce only these finite known values.
    if len(allowed_lengths) == 1:
        return next(iter(allowed_lengths))
    if length_type == "general" and {"short", "long_tail"}.issubset(allowed_lengths):
        compact_text = "".join(text.split())
        return "short" if len(compact_text) <= 8 else "long_tail"
    return None


def _historical_duplicate_texts(items, request):
    exclusions = set()
    for value in request.historical_exclusions:
        try:
            exclusions.add(normalize_plain_text(value)[1])
        except KeywordNormalizationError:
            continue
    duplicates = []
    for item in items:
        matching = normalize_plain_text(item.text)[1]
        if matching in exclusions and item.text not in duplicates:
            duplicates.append(item.text)
    return duplicates


def _novelty_diagnostic(content, duplicates):
    diagnostic = _structure_diagnostic(
        content,
        "historical_duplicate",
        error_fields=("text",),
    )
    diagnostic["root_cause"] = "historical_keyword_overlap"
    diagnostic["duplicate_keywords"] = list(duplicates)[:20]
    diagnostic["replacement_count"] = len(duplicates)
    return diagnostic


def _novelty_replacement_request(request, items, duplicates):
    exclusions = list(request.historical_exclusions)
    exclusions.extend(item.text for item in items)
    return replace(
        request,
        target_count=len(duplicates),
        historical_exclusions=tuple(dict.fromkeys(exclusions)),
    )


def _combine_novelty_replacements(original_items, replacement_items, request):
    historical = set()
    for value in request.historical_exclusions:
        try:
            historical.add(normalize_plain_text(value)[1])
        except KeywordNormalizationError:
            continue

    novel = []
    historical_fallback = []
    seen = set()
    for item in original_items:
        matching = normalize_plain_text(item.text)[1]
        seen.add(matching)
        if matching in historical:
            historical_fallback.append(item)
        else:
            novel.append(item)
    for item in replacement_items:
        matching = normalize_plain_text(item.text)[1]
        if matching in historical or matching in seen:
            continue
        seen.add(matching)
        novel.append(item)
    return tuple([*novel, *historical_fallback][: request.target_count])


class DeepSeekKeywordGenerationProvider(DeepSeekStructuredContentAdapter):
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
        capabilities=frozenset({AIModelCapability.KEYWORD_GENERATION}),
        adapter_version="deepseek-keyword-generation-v3",
        prompt_version="keyword-generation-v3",
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
    def _rows(content):
        if not isinstance(content, dict):
            _invalid(content, "top_level_not_object")
        rows = content.get("items", content.get("keywords", content.get("data")))
        if isinstance(rows, dict):
            rows = rows.get("items", rows.get("keywords"))
        if not isinstance(rows, list):
            _invalid(content, "items_not_list", "items")
        return rows

    @classmethod
    def _items(cls, content, request):
        rows = cls._rows(content)
        if len(rows) != request.target_count:
            _invalid(content, "item_count", "items")
        output = []
        allowed_lengths = {
            value
            for value, enabled in (
                ("short", request.include_short),
                ("long_tail", request.include_long_tail),
            )
            if enabled
        }
        if not allowed_lengths:
            allowed_lengths.add("general")
        for row in rows:
            if not isinstance(row, dict):
                _invalid(content, "item_not_object", "items")
            text = _first(row, "text")
            if not isinstance(text, str) or not text.strip():
                _invalid(content, "keyword_text", "text")
            try:
                category = normalize_category(_first(row, "category"))
                intents = normalize_intents(_first(row, "intents"))
            except ValueError as exc:
                _invalid(content, str(exc), "category", "intents")
            if request.categories and category not in request.categories:
                _invalid(content, "category_not_requested", "category")
            if request.intents and not set(intents).issubset(request.intents):
                _invalid(content, "intent_not_requested", "intents")
            length_type = _normalized_length_type(
                _first(row, "length_type"),
                text=text,
                allowed_lengths=allowed_lengths,
            )
            if length_type not in allowed_lengths:
                _invalid(content, "length_type", "length_type")
            raw_regions = _first(row, "regions", [])
            if raw_regions is None:
                raw_regions = []
            if isinstance(raw_regions, (str, dict)):
                raw_regions = [raw_regions]
            try:
                regions = normalize_region_entries(raw_regions)
            except KeywordNormalizationError as exc:
                _invalid(content, str(exc), "regions")
            base_keyword = _first(row, "base_keyword")
            if base_keyword is not None and not isinstance(base_keyword, str):
                _invalid(content, "base_keyword_type", "base_keyword")
            if (
                isinstance(base_keyword, str)
                and base_keyword.strip().casefold() == text.strip().casefold()
            ):
                base_keyword = None
            notes = _first(row, "notes", "")
            if notes is None:
                notes = ""
            if not isinstance(notes, str):
                _invalid(content, "notes_type", "notes")
            relevance_score = _first(row, "relevance_score")
            if isinstance(relevance_score, str) and relevance_score.isdigit():
                relevance_score = int(relevance_score)
            if relevance_score is not None and (
                type(relevance_score) is not int or not 0 <= relevance_score <= 100
            ):
                _invalid(content, "relevance_score", "relevance_score")
            raw_priority = _first(row, "priority")
            priority = None
            if raw_priority is not None:
                if not isinstance(raw_priority, str):
                    _invalid(content, "priority_type", "priority")
                priority = _PRIORITY_ALIASES.get(raw_priority.strip().lower())
                if priority is None:
                    _invalid(content, "priority_value", "priority")
            ai_reason = _first(row, "ai_reason")
            if ai_reason is not None and not isinstance(ai_reason, str):
                _invalid(content, "ai_reason_type", "ai_reason")
            first_region = regions[0] if regions else None
            output.append(
                GeneratedKeyword(
                    text=text.strip(),
                    structure_type=length_type,
                    is_regional=bool(regions),
                    region_level=str(first_region["level"]) if first_region else None,
                    region_text=str(first_region["name"]) if first_region else None,
                    base_keyword=base_keyword.strip() if base_keyword else None,
                    business_category=category,
                    search_intent=_LEGACY_INTENT.get(intents[0]),
                    relevance_score=relevance_score,
                    priority=priority,
                    ai_reason=ai_reason,
                    search_intents=intents,
                    regions=tuple(regions),
                    notes=notes,
                )
            )
        validation_rows = [
            {
                "text": item.text,
                "structure_type": item.structure_type,
                "is_regional": item.is_regional,
                "region_level": item.region_level or "",
                "region_text": item.region_text or "",
                "regions": list(item.regions),
                "base_keyword_text": item.base_keyword,
                "business_category": item.business_category,
                "search_intent": item.search_intent,
                "search_intents": list(item.search_intents),
                "source": "custom_generation"
                if request.generation_mode == "custom"
                else "smart_generation",
                "notes": item.notes,
                "relevance_score": item.relevance_score,
                "priority": item.priority,
                "ai_reason": item.ai_reason,
            }
            for item in output
        ]
        try:
            normalized = normalize_generated_keyword_items(
                validation_rows,
                target_count=request.target_count,
            )
        except KeywordNormalizationError as exc:
            _invalid(content, str(exc), "items")
        if len(normalized) != request.target_count:
            _invalid(content, "item_count", "items")
        return tuple(output)

    def _adapter_request(self, runtime, request, *, repair_output=None, diagnostic=None):
        novelty_repair = bool(
            diagnostic and diagnostic.get("root_cause") == "historical_keyword_overlap"
        )
        user_payload = {
            "task": (
                "repair_geo_keyword_candidates"
                if novelty_repair
                else "repair_geo_keyword_json"
                if repair_output is not None
                else "generate_geo_keywords"
            ),
            "subject": request.subject_values,
            "target_count": request.target_count,
            "include_short": request.include_short,
            "include_long_tail": request.include_long_tail,
            "region_mode": request.region_mode,
            "regions": list(request.regions),
            "selected_categories": list(request.categories),
            "selected_intents": list(request.intents),
            "category_catalog": [
                "entity",
                "industry",
                "product_category",
                "product",
                "service",
                "capability",
                "goal",
                "pain_point",
                "solution",
                "scenario",
                "audience",
                "competitor",
                "trust",
                "knowledge",
            ],
            "intent_catalog": [
                "informational",
                "recommendation",
                "comparison",
                "transactional",
                "local",
                "navigational",
                "trust",
                "usage",
            ],
            "exclusions": list(request.historical_exclusions),
        }
        if repair_output is not None:
            user_payload["validation_diagnostic"] = diagnostic or {}
            if novelty_repair:
                user_payload["duplicate_keywords"] = list(
                    (diagnostic or {}).get("duplicate_keywords", [])
                )
            else:
                user_payload["invalid_output"] = repair_output
            user_payload["repair_instruction"] = (
                "只生成用于补足缺口的全新关键词；不得复用 exclusions 或 "
                "duplicate_keywords，数量必须等于 target_count，且只返回要求的 JSON 结构。"
                if novelty_repair
                else "只修正为要求的 JSON 结构，不增加解释。"
            )
        return AIAdapterRequest(
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
                user_payload=user_payload,
                max_output_tokens=min(16_000, max(1_200, request.target_count * 180)),
                temperature=0.6 if novelty_repair else 0.2,
            ),
        )

    def generate(self, request: KeywordGenerationRequest) -> KeywordGenerationResponse:
        runtime = self.ensure_available()
        repair_output = None
        diagnostic = None
        response = None
        items = None
        fallback_response = None
        fallback_items = None
        active_request = request
        for request_index in range(2):
            normalized = self._adapter_request(
                runtime,
                active_request,
                repair_output=repair_output,
                diagnostic=diagnostic,
            )
            try:
                response = self.invoke(normalized)
            except AIAdapterError as exc:
                if fallback_response is not None and fallback_items is not None:
                    response = fallback_response
                    items = fallback_items
                    break
                if exc.schema_failure and request_index == 0:
                    repair_output = {}
                    diagnostic = _structure_diagnostic(None, "json_parse")
                    continue
                if exc.schema_failure:
                    raise KeywordGenerationInvalidResponse(
                        "json_parse",
                        diagnostic=_structure_diagnostic(None, "json_parse"),
                    ) from None
                raise KeywordGenerationProviderError(
                    domain_provider_error_code(exc, "KEYWORD_GENERATION_PROVIDER"),
                    permanent=not exc.retryable,
                ) from None
            try:
                items = self._items(response.output.content, active_request)
            except KeywordGenerationInvalidResponse as exc:
                if fallback_response is not None and fallback_items is not None:
                    response = fallback_response
                    items = fallback_items
                    break
                if request_index == 0:
                    repair_output = response.output.content
                    diagnostic = exc.diagnostic
                    continue
                raise
            if fallback_items is not None:
                items = _combine_novelty_replacements(fallback_items, items, request)
                break
            duplicates = _historical_duplicate_texts(items, request)
            if duplicates and request_index == 0:
                # One bounded repair request asks the provider to replace old
                # words. If that repair is malformed, retain the first valid
                # response so persistence can still keep its novel subset.
                fallback_response = response
                fallback_items = items
                active_request = _novelty_replacement_request(request, items, duplicates)
                repair_output = {}
                diagnostic = _novelty_diagnostic(response.output.content, duplicates)
                continue
            break
        if response is None or items is None:
            raise KeywordGenerationInvalidResponse(
                "schema_invalid",
                diagnostic=diagnostic,
            )
        metrics = dict(response.sanitized_provider_metadata)
        if response.provider_request_id:
            metrics["provider_request_id"] = response.provider_request_id
        if response.usage.total_tokens is not None:
            metrics["total_tokens"] = response.usage.total_tokens
        metrics["request_count"] = 2 if repair_output is not None else 1
        return KeywordGenerationResponse(
            items=items,
            model_key=self.model_key,
            provider_metrics=metrics,
        )


class MockKeywordGenerationProvider(
    DeterministicMockAIAdapter[KeywordGenerationRequest, KeywordGenerationResponse]
):
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="mock", model_key="mock-keyword-generation-v1"),
        capabilities=frozenset({AIModelCapability.KEYWORD_GENERATION}),
        adapter_version="2",
        prompt_version="keyword-generation-v2",
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
            region_name = str(region.get("name")) if region else None
            text = f"{official_name} 关键词 {start + index + 1}"
            if region_name:
                text = f"{region_name} {text}"
            category = (
                request.categories[index % len(request.categories)]
                if request.categories
                else "entity"
            )
            intents = request.intents or ("recommendation",)
            items.append(
                GeneratedKeyword(
                    text=text,
                    structure_type=structure,
                    is_regional=regional,
                    region_level=str(region.get("level")) if region else None,
                    region_text=region_name,
                    base_keyword=None,
                    business_category=category,
                    search_intent=_LEGACY_INTENT.get(intents[0]),
                    relevance_score=max(0, 100 - index),
                    priority="high" if index < 3 else "medium",
                    ai_reason=f"Mock generation reason {index + 1}",
                    search_intents=tuple(intents),
                    regions=(dict(region),) if region else (),
                    source=(
                        "custom_generation"
                        if request.generation_mode == "custom"
                        else "smart_generation"
                    ),
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
                        business_category="invalid",
                        search_intent="invalid",
                        relevance_score=101,
                        priority="invalid",
                        ai_reason="",
                        search_intents=("invalid",),
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
        prompt_version="keyword-generation-v2",
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
