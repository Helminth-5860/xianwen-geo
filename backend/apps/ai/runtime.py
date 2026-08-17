from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .contracts import AIModelCapability
from .errors import AIAdapterError, AIAdapterErrorCategory
from .models import AIModelRuntimeConfig
from .registry import AIModelRegistry, model_registry


@dataclass(frozen=True)
class AIModelRuntimeSnapshot:
    model_id: str
    provider_key: str
    model_key: str
    display_name: str
    provider_model_id: str
    api_version: str
    enabled: bool
    sort_order: int
    network_access_enabled: bool
    web_search_failure_policy: str
    timeout_seconds: int
    max_retries: int
    retry_base_seconds: int
    retry_backoff: str
    max_concurrency: int
    cost_unit: str | None
    currency: str
    input_cost: Decimal | None
    output_cost: Decimal | None
    request_cost: Decimal | None
    paused: bool
    version: int


def _snapshot(config: AIModelRuntimeConfig) -> AIModelRuntimeSnapshot:
    return AIModelRuntimeSnapshot(
        model_id=str(config.model_id),
        provider_key=config.model.provider.provider_key,
        model_key=config.model.model_key,
        display_name=config.display_name,
        provider_model_id=config.provider_model_id,
        api_version=config.api_version,
        enabled=config.enabled,
        sort_order=config.sort_order,
        network_access_enabled=config.network_access_enabled,
        web_search_failure_policy=config.web_search_failure_policy,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
        retry_base_seconds=config.retry_base_seconds,
        retry_backoff=config.retry_backoff,
        max_concurrency=config.max_concurrency,
        cost_unit=config.cost_unit or None,
        currency=config.currency,
        input_cost=config.input_cost,
        output_cost=config.output_cost,
        request_cost=config.request_cost,
        paused=config.paused,
        version=config.version,
    )


def get_runtime_snapshot(
    *, model_key: str, require_available: bool = True
) -> AIModelRuntimeSnapshot:
    try:
        config = AIModelRuntimeConfig.objects.select_related("model__provider").get(
            model__model_key=model_key
        )
    except AIModelRuntimeConfig.DoesNotExist as exc:
        raise AIAdapterError(
            AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
            stable_code="AI_MODEL_RUNTIME_CONFIG_MISSING",
            retryable=False,
        ) from exc
    snapshot = _snapshot(config)
    if require_available and not snapshot.enabled:
        raise AIAdapterError(
            AIAdapterErrorCategory.MODEL_UNAVAILABLE,
            stable_code="AI_MODEL_DISABLED",
            retryable=False,
        )
    if require_available and snapshot.paused:
        raise AIAdapterError(
            AIAdapterErrorCategory.MODEL_UNAVAILABLE,
            stable_code="AI_MODEL_PAUSED",
            retryable=False,
        )
    return snapshot


def list_available_runtime_snapshots() -> tuple[AIModelRuntimeSnapshot, ...]:
    rows = AIModelRuntimeConfig.objects.select_related("model__provider").filter(
        enabled=True, paused=False
    )
    return tuple(_snapshot(row) for row in rows.order_by("sort_order", "model__model_key"))


def resolve_detection_adapter(
    *, model_key: str, registry: AIModelRegistry = model_registry
) -> tuple[AIModelRuntimeSnapshot, object]:
    snapshot = get_runtime_snapshot(model_key=model_key, require_available=True)
    adapter = registry.resolve(
        provider_key=snapshot.provider_key,
        model_key=snapshot.model_key,
        capability=AIModelCapability.GEO_DETECTION,
    )
    return snapshot, adapter
