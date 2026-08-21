from __future__ import annotations

import unicodedata
from decimal import Decimal

from django.db import transaction

from apps.admin_rbac.audit_services import record_audit_event

from .exceptions import (
    AIModelConfigStateConflict,
    AIModelConfigValuesInvalid,
    AIModelConfigVersionConflict,
)
from .models import (
    AICapabilityRuntimeConfig,
    AIModelRuntimeConfig,
    APICredential,
    APICredentialCapabilityBinding,
)


def _normalized_text(value: str, *, maximum: int, required: bool = False) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in normalized):
        raise AIModelConfigValuesInvalid
    normalized = " ".join(normalized.split())
    if len(normalized) > maximum or (required and not normalized):
        raise AIModelConfigValuesInvalid
    return normalized


def _audit_summary(config: AIModelRuntimeConfig) -> dict[str, object]:
    return {
        "model_key": config.model.model_key,
        "enabled": config.enabled,
        "paused": config.paused,
        "version": config.version,
        "sort_order": config.sort_order,
        "network_access_enabled": config.network_access_enabled,
        "web_search_failure_policy": config.web_search_failure_policy,
        "timeout_seconds": config.timeout_seconds,
        "max_retries": config.max_retries,
        "retry_base_seconds": config.retry_base_seconds,
        "retry_backoff": config.retry_backoff,
        "max_concurrency": config.max_concurrency,
        "cost_unit": config.cost_unit or None,
        "currency": config.currency,
        "input_cost": str(config.input_cost) if config.input_cost is not None else None,
        "output_cost": str(config.output_cost) if config.output_cost is not None else None,
        "request_cost": str(config.request_cost) if config.request_cost is not None else None,
        "display_name_overridden": bool(config.display_name_override),
        "provider_model_configured": bool(config.provider_model_id),
        "api_version_configured": bool(config.api_version),
    }


def _record_audit(request, *, action: str, config: AIModelRuntimeConfig, before: dict) -> None:
    record_audit_event(
        request=request,
        category="ai_model_config",
        action_key=action,
        outcome="executed",
        actor=request.user,
        target_type="ai_model",
        target_id=config.model_id,
        safe_before=before,
        safe_after=_audit_summary(config),
    )


def _locked_config(model_id) -> AIModelRuntimeConfig:
    return (
        AIModelRuntimeConfig.objects.select_for_update()
        .select_related("model__provider")
        .get(model_id=model_id)
    )


def _check_version(config: AIModelRuntimeConfig, expected_version: int) -> None:
    if config.version != expected_version:
        raise AIModelConfigVersionConflict


def _validate_cost(config: AIModelRuntimeConfig) -> None:
    zero = Decimal("0")
    if not config.cost_unit:
        if any(
            value is not None
            for value in (config.input_cost, config.output_cost, config.request_cost)
        ):
            raise AIModelConfigValuesInvalid
        return
    if config.cost_unit == AIModelRuntimeConfig.CostUnit.PER_MILLION_TOKENS:
        if (
            config.input_cost is None
            or config.output_cost is None
            or config.request_cost is not None
            or config.input_cost < zero
            or config.output_cost < zero
        ):
            raise AIModelConfigValuesInvalid
        return
    if config.cost_unit == AIModelRuntimeConfig.CostUnit.PER_REQUEST:
        if (
            config.request_cost is None
            or config.input_cost is not None
            or config.output_cost is not None
            or config.request_cost < zero
        ):
            raise AIModelConfigValuesInvalid
        return
    raise AIModelConfigValuesInvalid


@transaction.atomic
def update_runtime_config(*, request, model_id, data) -> AIModelRuntimeConfig:
    config = _locked_config(model_id)
    _check_version(config, data.pop("expected_version"))
    before = _audit_summary(config)
    text_fields = {
        "display_name_override": 150,
        "provider_model_id": 255,
        "api_version": 100,
    }
    for field, maximum in text_fields.items():
        if field in data:
            setattr(config, field, _normalized_text(data[field], maximum=maximum))
    for field in (
        "sort_order",
        "network_access_enabled",
        "web_search_failure_policy",
        "timeout_seconds",
        "max_retries",
        "retry_base_seconds",
        "retry_backoff",
        "max_concurrency",
        "currency",
        "input_cost",
        "output_cost",
        "request_cost",
    ):
        if field in data:
            setattr(config, field, data[field])
    if "cost_unit" in data:
        config.cost_unit = data["cost_unit"] or ""
    _validate_cost(config)
    config.version += 1
    config.updated_by = request.user
    config.save()
    _record_audit(request, action="ai_model_config.update", config=config, before=before)
    return config


@transaction.atomic
def set_model_enabled(
    *, request, model_id, enabled: bool, expected_version: int
) -> AIModelRuntimeConfig:
    config = _locked_config(model_id)
    _check_version(config, expected_version)
    if config.enabled is enabled:
        raise AIModelConfigStateConflict
    before = _audit_summary(config)
    config.enabled = enabled
    config.version += 1
    config.updated_by = request.user
    config.save()
    _record_audit(
        request,
        action="ai_model.enable" if enabled else "ai_model.disable",
        config=config,
        before=before,
    )
    return config


@transaction.atomic
def set_model_paused(
    *, request, model_id, paused: bool, expected_version: int, reason: str = ""
) -> AIModelRuntimeConfig:
    config = _locked_config(model_id)
    _check_version(config, expected_version)
    if config.paused is paused:
        raise AIModelConfigStateConflict
    before = _audit_summary(config)
    config.paused = paused
    config.pause_reason = _normalized_text(reason, maximum=200, required=paused) if paused else ""
    config.version += 1
    config.updated_by = request.user
    config.save()
    _record_audit(
        request,
        action="ai_model.pause" if paused else "ai_model.unpause",
        config=config,
        before=before,
    )
    return config


@transaction.atomic
def update_capability_runtime(*, request, config_id, data) -> AICapabilityRuntimeConfig:
    config = (
        AICapabilityRuntimeConfig.objects.select_for_update()
        .select_related("model__provider")
        .get(pk=config_id)
    )
    expected_version = data.pop("expected_version")
    if config.version != expected_version:
        raise AIModelConfigVersionConflict
    before = {
        "provider_key": config.model.provider.provider_key,
        "capability": config.capability,
        "provider_model_configured": bool(config.provider_model_id),
        "enabled": config.enabled,
        "paused": config.paused,
        "version": config.version,
    }
    for field, value in data.items():
        if field in {"provider_model_id", "api_version", "pause_reason"}:
            maximum = {"provider_model_id": 255, "api_version": 100, "pause_reason": 200}[field]
            value = _normalized_text(value, maximum=maximum)
        setattr(config, field, value)
    if config.paused and not config.pause_reason:
        raise AIModelConfigValuesInvalid
    if not config.paused:
        config.pause_reason = ""
    if config.enabled and not config.provider_model_id:
        raise AIModelConfigValuesInvalid
    config.version += 1
    config.updated_by = request.user
    config.save()
    record_audit_event(
        request=request,
        category="ai_model_config",
        action_key="ai_capability_runtime.update",
        outcome="executed",
        actor=request.user,
        target_type="ai_capability_runtime",
        target_id=config.pk,
        safe_before=before,
        safe_after={
            "provider_key": config.model.provider.provider_key,
            "capability": config.capability,
            "provider_model_configured": bool(config.provider_model_id),
            "enabled": config.enabled,
            "paused": config.paused,
            "version": config.version,
        },
    )
    return config


@transaction.atomic
def upsert_credential_capability_binding(*, request, provider, data):
    capability = data["capability"]
    environment = data["environment"]
    enabled = data["enabled"]
    binding = (
        APICredentialCapabilityBinding.objects.select_for_update()
        .filter(provider=provider, capability=capability, environment=environment)
        .first()
    )
    before = None
    if binding is None:
        if data.get("expected_version") is not None:
            raise AIModelConfigVersionConflict
        binding = APICredentialCapabilityBinding(
            provider=provider, capability=capability, environment=environment
        )
    else:
        if data.get("expected_version") != binding.version:
            raise AIModelConfigVersionConflict
        before = {"enabled": binding.enabled, "version": binding.version}
        binding.version += 1
    if (
        enabled
        and not APICredential.objects.filter(
            provider=provider, environment=environment, status=APICredential.Status.ACTIVE
        ).exists()
    ):
        raise AIModelConfigStateConflict
    binding.enabled = enabled
    binding.updated_by = request.user
    binding.save()
    record_audit_event(
        request=request,
        category="api_credential",
        action_key="api_credential.capability_binding.update",
        outcome="executed",
        actor=request.user,
        target_type="api_credential_capability_binding",
        target_id=binding.pk,
        safe_before=before or {},
        safe_after={
            "provider_key": provider.provider_key,
            "capability": capability,
            "environment": environment,
            "enabled": enabled,
            "version": binding.version,
        },
    )
    return binding
