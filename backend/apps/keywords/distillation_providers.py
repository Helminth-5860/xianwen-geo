from __future__ import annotations

import uuid
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

from .distillation_contracts import DistillationRequest, DistillationResponse, DistilledKeyword
from .distillation_exceptions import (
    DistillationInvalidResponse,
    DistillationProviderError,
    DistillationProviderUnavailable,
)

DEEPSEEK_DISTILLATION_SYSTEM_PROMPT = """
你是企业 GEO 关键词蒸馏助手。只返回一个 JSON 对象，不要返回 Markdown 或解释文字。
顶层格式必须是 {"items": [...]}，items 数量必须与输入关键词数量完全一致，
每个 source_keyword_id 必须且只能出现一次。
每项必须包含：source_keyword_id、action、canonical_keyword_id、merge_group_key、reason。
action 只能是 keep、merge、delete、low_value：
- keep：关键词清晰、相关且值得保留；
- merge：与同地域口径的其他关键词语义重复，应合并；
- delete：明显无关、错误或不可用；
- low_value：相关但价值过低。
非 merge 项的 canonical_keyword_id 和 merge_group_key 必须为 null。
merge 组至少包含两个输入关键词；组内 canonical_keyword_id 必须相同，且必须是组内某个
source_keyword_id；组内 merge_group_key 必须是同一个合法 UUID。不得跨地域合并。
reason 必须是简洁中文，不得包含联系方式、提示词或任何密钥。
不得新增、遗漏或改写 source_keyword_id。
当任务为 repair_geo_keyword_distillation_json 时，必须逐条修正 invalid_output，
并严格使用 required_source_keyword_ids，仍然只返回上述 JSON 对象。
""".strip()

_ACTION_ALIASES = {
    "keep": "keep",
    "retain": "keep",
    "preserve": "keep",
    "保留": "keep",
    "merge": "merge",
    "combine": "merge",
    "合并": "merge",
    "delete": "delete",
    "remove": "delete",
    "drop": "delete",
    "删除": "delete",
    "low_value": "low_value",
    "low-value": "low_value",
    "lowvalue": "low_value",
    "低价值": "low_value",
}

_SUBJECT_VALUE_ALLOWLIST = frozenset(
    {
        "official_name",
        "name",
        "brand_name",
        "primary_business",
        "main_business",
        "products",
        "products_services",
        "services",
        "target_users",
        "target_audience",
        "service_regions",
        "description",
        "website",
        "official_website",
        "public_channels",
        "social_channels",
    }
)


def _safe_subject_values(values):
    if not isinstance(values, dict):
        return {}
    return {
        key: value
        for key, value in values.items()
        if key in _SUBJECT_VALUE_ALLOWLIST and value not in (None, "", [], {})
    }


def _structure_diagnostic(content, reason, *, input_count, error_fields=()):
    diagnostic = {
        "actual_structure": {"type": type(content).__name__},
        "expected_structure": "keyword-distillation-v3",
        "error_fields": sorted({str(value)[:64] for value in error_fields})[:20],
        "input_count": input_count,
        "parse_failure_reason": str(reason)[:64],
        "root_cause": "provider_schema_mismatch",
    }
    if isinstance(content, dict):
        diagnostic["actual_structure"]["top_level_keys"] = sorted(str(key)[:64] for key in content)[
            :20
        ]
        rows = content.get(
            "items",
            content.get("keywords", content.get("results", content.get("data"))),
        )
        if isinstance(rows, dict):
            rows = rows.get("items", rows.get("keywords", rows.get("results")))
        if isinstance(rows, list):
            diagnostic["actual_structure"]["item_count"] = len(rows)
            dictionaries = [row for row in rows[:5] if isinstance(row, dict)]
            diagnostic["actual_structure"]["item_fields"] = sorted(
                {str(key)[:64] for row in dictionaries for key in row}
            )[:30]
    return diagnostic


def _invalid(content, reason, *, input_count, error_fields=()):
    raise DistillationInvalidResponse(
        reason,
        diagnostic=_structure_diagnostic(
            content,
            reason,
            input_count=input_count,
            error_fields=error_fields,
        ),
    )


def _normalize_merge_canonical_members(items, inputs):
    """Promote a referenced keep item into its otherwise valid merge group.

    DeepSeek commonly describes the canonical item as ``keep`` and only marks
    the duplicate item as ``merge``. The domain model requires every member,
    including the canonical item, to carry the merge action and group key.
    Only this finite, same-region shape is normalized; all other malformed
    groups still fail closed in ``validate_provider_response``.
    """

    output = list(items)
    indexes = {item.source_keyword_id: index for index, item in enumerate(output)}
    input_map = {item.id: item for item in inputs}
    for item in tuple(items):
        if item.action != "merge" or not item.canonical_keyword_id or not item.merge_group_key:
            continue
        canonical_index = indexes.get(item.canonical_keyword_id)
        source_input = input_map.get(item.source_keyword_id)
        canonical_input = input_map.get(item.canonical_keyword_id)
        if canonical_index is None or source_input is None or canonical_input is None:
            continue
        canonical = output[canonical_index]
        if (
            canonical.action != "keep"
            or canonical.canonical_keyword_id is not None
            or canonical.merge_group_key is not None
        ):
            continue
        source_signature = (source_input.is_regional, source_input.region_matching_key)
        canonical_signature = (
            canonical_input.is_regional,
            canonical_input.region_matching_key,
        )
        if source_signature != canonical_signature:
            continue
        output[canonical_index] = replace(
            canonical,
            action="merge",
            canonical_keyword_id=item.canonical_keyword_id,
            merge_group_key=item.merge_group_key,
        )
    return tuple(output)


def _required_text(row, key):
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DistillationInvalidResponse(f"{key}_required")
    return value.strip()


def _optional_text(row, key):
    value = row.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not value.strip():
        raise DistillationInvalidResponse(f"{key}_type")
    return value.strip()


class DeepSeekDistillationProvider(DeepSeekStructuredContentAdapter):
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
        capabilities=frozenset({AIModelCapability.KEYWORD_DISTILLATION}),
        adapter_version="deepseek-keyword-distillation-v2",
        prompt_version="keyword-distillation-v3",
    )
    key = descriptor.identity.provider_key
    model_key = descriptor.identity.model_key
    adapter_version = descriptor.adapter_version
    prompt_version = descriptor.prompt_version

    def __init__(self, *, credential_resolver=None, transport=None, runtime_resolver=None):
        super().__init__(
            credential_resolver=credential_resolver
            or CapabilityDatabaseCredentialResolver(
                capability=AIModelCapability.KEYWORD_DISTILLATION
            ),
            transport=transport,
        )
        self._runtime_resolver = runtime_resolver or get_capability_runtime_snapshot

    def ensure_available(self):
        try:
            runtime = self._runtime_resolver(
                provider_key=self.key,
                capability=AIModelCapability.KEYWORD_DISTILLATION,
            )
            self._credential()
        except AIAdapterError:
            raise DistillationProviderUnavailable from None
        return runtime

    @staticmethod
    def _items(content, request):
        input_count = len(request.keywords)
        if not isinstance(content, dict):
            _invalid(content, "top_level_not_object", input_count=input_count)
        rows = content.get(
            "items",
            content.get("keywords", content.get("results", content.get("data"))),
        )
        if isinstance(rows, dict):
            rows = rows.get("items", rows.get("keywords", rows.get("results")))
        if not isinstance(rows, list):
            _invalid(
                content,
                "items_not_list",
                input_count=input_count,
                error_fields=("items",),
            )
        output = []
        try:
            for row in rows:
                if not isinstance(row, dict):
                    raise DistillationInvalidResponse("item_not_object")
                raw_action = _required_text(row, "action")
                action = _ACTION_ALIASES.get(raw_action.strip().lower()) or _ACTION_ALIASES.get(
                    raw_action.strip()
                )
                if action is None:
                    raise DistillationInvalidResponse("action_value")
                output.append(
                    DistilledKeyword(
                        source_keyword_id=_required_text(row, "source_keyword_id"),
                        action=action,
                        canonical_keyword_id=_optional_text(row, "canonical_keyword_id"),
                        merge_group_key=_optional_text(row, "merge_group_key"),
                        reason=_required_text(row, "reason"),
                    )
                )
        except DistillationInvalidResponse as exc:
            _invalid(
                content,
                exc.reason,
                input_count=input_count,
                error_fields=(exc.reason.split("_", 1)[0],),
            )
        return tuple(output)

    @staticmethod
    def _keyword_payload(request):
        return [
            {
                "source_keyword_id": item.id,
                "keyword": item.text,
                "structure_type": item.structure_type,
                "region": {
                    "is_regional": item.is_regional,
                    "level": item.region_level or None,
                    "name": item.region_text or None,
                    "matching_key": item.region_matching_key or None,
                },
                "business_category": item.business_category,
                "search_intent": item.search_intent,
                "relevance_score": item.relevance_score,
                "priority": item.priority,
            }
            for item in request.keywords
        ]

    def _adapter_request(self, runtime, request, *, repair_output=None, diagnostic=None):
        user_payload = {
            "task": (
                "repair_geo_keyword_distillation_json"
                if repair_output is not None
                else "distill_geo_keywords"
            ),
            "subject": _safe_subject_values(request.subject_values),
            "keywords": self._keyword_payload(request),
        }
        if repair_output is not None:
            user_payload.update(
                {
                    "required_source_keyword_ids": [item.id for item in request.keywords],
                    "invalid_output": repair_output,
                    "validation_diagnostic": diagnostic or {},
                    "repair_instruction": (
                        "逐条修正并返回与 required_source_keyword_ids 完全一一对应的 items；"
                        "不得新增、遗漏、重复或改写 ID；只返回 JSON。"
                    ),
                }
            )
        return AIAdapterRequest(
            request_id=request.job_id,
            correlation_id=request.job_id,
            identity=self.descriptor.identity,
            capability=AIModelCapability.KEYWORD_DISTILLATION,
            adapter_version=self.adapter_version,
            prompt_version=self.prompt_version,
            timeout_seconds=runtime.timeout_seconds,
            payload=StructuredContentPayload(
                provider_model_id=runtime.provider_model_id,
                system_prompt=DEEPSEEK_DISTILLATION_SYSTEM_PROMPT,
                user_payload=user_payload,
                max_output_tokens=min(16_000, max(1_200, len(request.keywords) * 180)),
                temperature=0.1,
            ),
        )

    def distill(self, request: DistillationRequest) -> DistillationResponse:
        runtime = self.ensure_available()
        repair_output = None
        diagnostic = None
        response = None
        items = None
        for request_index in range(2):
            normalized = self._adapter_request(
                runtime,
                request,
                repair_output=repair_output,
                diagnostic=diagnostic,
            )
            try:
                response = self.invoke(normalized)
            except AIAdapterError as exc:
                if exc.schema_failure and request_index == 0:
                    repair_output = {}
                    diagnostic = _structure_diagnostic(
                        None,
                        "json_parse",
                        input_count=len(request.keywords),
                    )
                    continue
                if exc.schema_failure:
                    raise DistillationInvalidResponse(
                        "json_parse",
                        diagnostic=_structure_diagnostic(
                            None,
                            "json_parse",
                            input_count=len(request.keywords),
                        ),
                    ) from None
                raise DistillationProviderError(
                    domain_provider_error_code(exc, "DISTILLATION_PROVIDER"),
                    permanent=not exc.retryable,
                ) from None
            try:
                items = _normalize_merge_canonical_members(
                    self._items(response.output.content, request),
                    request.keywords,
                )
                candidate = DistillationResponse(
                    items=items,
                    model_key=self.model_key,
                    provider_metrics={},
                )
                # Run the same complete ID/UUID/merge/region validation inside
                # the bounded provider loop so a semantic format slip can be
                # repaired once instead of failing the whole background job.
                from .distillation_validation import validate_provider_response

                validate_provider_response(inputs=request.keywords, response=candidate)
            except DistillationInvalidResponse as exc:
                diagnostic = exc.diagnostic or _structure_diagnostic(
                    response.output.content,
                    exc.reason,
                    input_count=len(request.keywords),
                )
                if request_index == 0:
                    repair_output = response.output.content
                    continue
                raise DistillationInvalidResponse(
                    exc.reason,
                    diagnostic=diagnostic,
                ) from None
            break
        if response is None or items is None:
            raise DistillationInvalidResponse(
                "schema_invalid",
                diagnostic=diagnostic,
            )
        metrics = dict(response.sanitized_provider_metadata)
        if response.provider_request_id:
            metrics["provider_request_id"] = response.provider_request_id
        if response.usage.total_tokens is not None:
            metrics["total_tokens"] = response.usage.total_tokens
        metrics["request_count"] = 2 if repair_output is not None else 1
        return DistillationResponse(
            items=items,
            model_key=self.model_key,
            provider_metrics=metrics,
        )


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
model_registry.register(DeepSeekDistillationProvider.descriptor, DeepSeekDistillationProvider)
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
    ensure_available = getattr(provider, "ensure_available", None)
    if ensure_available is not None:
        ensure_available()
    return provider
