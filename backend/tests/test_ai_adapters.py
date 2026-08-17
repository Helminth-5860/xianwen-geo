from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import pytest

from apps.ai.contracts import (
    AdapterCredential,
    AIAdapterDescriptor,
    AIAdapterRequest,
    AIAdapterResponse,
    AIModelCapability,
    AIModelIdentity,
)
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.mock import DeterministicMockAIAdapter
from apps.ai.registry import AIModelRegistry, model_registry
from apps.ai.sanitization import REDACTED, TRUNCATED, sanitize_provider_payload
from apps.core.logging import JsonFormatter


@dataclass(frozen=True)
class FakeOutput:
    value: str
    provider_metrics: dict[str, object]


class FakeMockAdapter(DeterministicMockAIAdapter[dict[str, object], FakeOutput]):
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="mock", model_key="mock-contract-v1"),
        capabilities=frozenset({AIModelCapability.TEXT_GENERATION}),
        adapter_version="1",
        prompt_version="contract-v1",
        is_mock=True,
    )

    def __init__(self, scenario="success"):
        self.scenario = scenario

    def _scenario(self):
        return self.scenario

    def _build_output(self, payload, scenario):
        return FakeOutput(
            value=str(payload["value"]),
            provider_metrics={
                "mock": True,
                "item_count": 1,
                "input_tokens": 4,
                "api_key": "must-not-survive",
                "raw_response": {"secret": "must-not-survive"},
            },
        )


def normalized_request(adapter, *, timeout_seconds=30):
    return adapter.normalized_request(
        {"value": "deterministic"},
        request_id="d8c8a31b-560e-4fe7-8132-9805528a68b7",
        correlation_id="477c0ccb-b665-4be0-a8af-31143ef452f9",
        timeout_seconds=timeout_seconds,
    )


def test_unified_request_validates_identity_versions_and_timeout():
    identity = AIModelIdentity(provider_key="deepseek", model_key="deepseek-chat")
    request = AIAdapterRequest(
        request_id="request-1",
        correlation_id=None,
        identity=identity,
        capability=AIModelCapability.TEXT_GENERATION,
        adapter_version="1.0",
        prompt_version="prompt-v1",
        timeout_seconds=30,
        payload={"untrusted": "data"},
    )
    assert request.identity == identity
    assert request.timeout_seconds == 30

    with pytest.raises(ValueError, match="timeout_seconds"):
        AIAdapterRequest(
            request_id="request-1",
            correlation_id=None,
            identity=identity,
            capability=AIModelCapability.TEXT_GENERATION,
            adapter_version="1.0",
            prompt_version="prompt-v1",
            timeout_seconds=0,
            payload={},
        )
    with pytest.raises(ValueError, match="stable machine key"):
        AIModelIdentity(provider_key="https://provider.example", model_key="model")


def test_registry_lookup_uniqueness_and_capability_errors():
    registry = AIModelRegistry()
    adapter = FakeMockAdapter()
    registry.register(adapter.descriptor, FakeMockAdapter)

    resolved = registry.resolve(
        provider_key="mock",
        model_key="mock-contract-v1",
        capability=AIModelCapability.TEXT_GENERATION,
    )
    assert isinstance(resolved, FakeMockAdapter)
    assert registry.descriptors() == (adapter.descriptor,)

    with pytest.raises(AIAdapterError) as duplicate:
        registry.register(adapter.descriptor, FakeMockAdapter)
    assert duplicate.value.stable_code == "AI_REGISTRY_DUPLICATE"
    assert duplicate.value.configuration_failure is True

    cases = (
        ("unknown", "mock-contract-v1", AIModelCapability.TEXT_GENERATION, "unknown_provider"),
        ("mock", "unknown", AIModelCapability.TEXT_GENERATION, "unknown_model"),
        ("mock", "mock-contract-v1", AIModelCapability.IMAGE_GENERATION, "unsupported_capability"),
    )
    for provider_key, model_key, capability, category in cases:
        with pytest.raises(AIAdapterError) as failure:
            registry.resolve(
                provider_key=provider_key,
                model_key=model_key,
                capability=capability,
            )
        assert failure.value.category.value == category
        assert failure.value.retryable is False


def test_mock_adapter_success_is_deterministic_and_normalized():
    adapter = FakeMockAdapter()
    request = normalized_request(adapter)
    first = adapter.invoke(request)
    second = adapter.invoke(request)

    assert first.output == second.output
    assert first.request_id == request.request_id
    assert first.identity == adapter.descriptor.identity
    assert first.finish_reason.value == "stop"
    assert first.usage.input_tokens == 4
    assert first.sanitized_provider_metadata == {
        "mock": True,
        "item_count": 1,
        "input_tokens": 4,
    }


@pytest.mark.parametrize(
    ("scenario", "category", "retryable"),
    [
        ("timeout", AIAdapterErrorCategory.TIMEOUT, True),
        ("rate_limit", AIAdapterErrorCategory.RATE_LIMIT, True),
        ("temporary", AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE, True),
        ("permanent", AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE, False),
        ("not-defined", AIAdapterErrorCategory.INTERNAL_ADAPTER, False),
    ],
)
def test_mock_adapter_normalizes_failure_scenarios(scenario, category, retryable):
    adapter = FakeMockAdapter(scenario)
    with pytest.raises(AIAdapterError) as failure:
        adapter.invoke(normalized_request(adapter))
    assert failure.value.category == category
    assert failure.value.retryable is retryable


def test_normalized_error_classification_and_repr_are_safe():
    error = AIAdapterError(
        AIAdapterErrorCategory.RESPONSE_PARSE,
        stable_code="AI_RESPONSE_SCHEMA_INVALID",
    )
    assert error.retryable is False
    assert error.configuration_failure is False
    assert error.provider_failure is False
    assert error.schema_failure is True
    assert "provider-secret" not in str(error)
    assert "provider-secret" not in repr(error)
    unsafe_code = AIAdapterError(
        AIAdapterErrorCategory.INTERNAL_ADAPTER,
        stable_code="provider-secret=raw-upstream-error",
    )
    assert unsafe_code.stable_code == "AI_INTERNAL_ADAPTER"
    assert "provider-secret" not in repr(unsafe_code)

    credential = AdapterCredential("provider-secret")
    request = normalized_request(FakeMockAdapter())
    response = FakeMockAdapter().invoke(request)
    assert "provider-secret" not in repr(credential)
    assert "deterministic" not in repr(request)
    assert "deterministic" not in repr(response)


def test_raw_provider_payload_sanitizer_redacts_nested_secrets_and_bounds_data():
    class DangerousObject:
        def __repr__(self):
            return "provider-secret-from-repr"

    sanitized = sanitize_provider_payload(
        {
            "headers": {
                "Authorization": "Bearer provider-secret",
                "Cookie": "session=provider-secret",
                "x-request-id": "safe-id",
            },
            "prompt": "system secret prompt",
            "nested": {
                "api_key": "provider-secret",
                "signed_url": "https://objects.example/file?X-Signature=provider-secret",
                "diagnostic_url": "https://provider.example/status?token=provider-secret",
            },
            "large": "x" * 300,
            "unknown": DangerousObject(),
        }
    )
    rendered = json.dumps(sanitized, ensure_ascii=False)
    assert "provider-secret" not in rendered
    assert "system secret prompt" not in rendered
    assert sanitized["headers"]["Authorization"] == REDACTED
    assert sanitized["headers"]["Cookie"] == REDACTED
    assert sanitized["prompt"] == REDACTED
    assert sanitized["nested"]["signed_url"] == REDACTED
    assert sanitized["nested"]["diagnostic_url"] == "https://provider.example/status"
    assert sanitized["large"].endswith(TRUNCATED)
    assert sanitized["unknown"] == "[UNSUPPORTED]"


def test_response_contract_sanitizes_metadata_on_construction():
    response = AIAdapterResponse(
        request_id="request-1",
        identity=AIModelIdentity(provider_key="mock", model_key="mock-contract-v1"),
        output={"structured": True},
        sanitized_provider_metadata={
            "provider_request_id": "safe-id",
            "authorization": "Bearer provider-secret",
            "diagnostics": "provider-secret diagnostic",
            "url": "https://provider.example/status?signature=provider-secret",
        },
    )
    rendered = json.dumps(response.sanitized_provider_metadata)
    assert "provider-secret" not in rendered
    assert response.sanitized_provider_metadata["authorization"] == REDACTED
    assert response.sanitized_provider_metadata["diagnostics"] == REDACTED
    assert response.sanitized_provider_metadata["url"] == "https://provider.example/status"


def test_existing_ai_consumers_are_registered_without_changing_legacy_identity():
    from apps.keywords.distillation_providers import MockDistillationProvider
    from apps.keywords.generation_providers import MockKeywordGenerationProvider
    from apps.questions.generation_providers import MockQuestionGenerationProvider
    from apps.subjects.enrichment_providers import MockSubjectEnrichmentProvider

    expected = (
        (MockSubjectEnrichmentProvider, AIModelCapability.SUBJECT_ENRICHMENT),
        (MockKeywordGenerationProvider, AIModelCapability.KEYWORD_GENERATION),
        (MockDistillationProvider, AIModelCapability.KEYWORD_DISTILLATION),
        (MockQuestionGenerationProvider, AIModelCapability.QUESTION_GENERATION),
    )
    for provider_type, capability in expected:
        provider = model_registry.resolve(
            provider_key=provider_type.key,
            model_key=provider_type.model_key,
            capability=capability,
        )
        assert isinstance(provider, provider_type)
        assert provider.adapter_version == provider.descriptor.adapter_version
        assert provider.prompt_version == provider.descriptor.prompt_version


def test_sanitized_provider_metadata_is_safe_when_logged():
    sanitized = sanitize_provider_payload(
        {
            "provider_request_id": "safe-request-id",
            "raw_response": {"api_key": "provider-secret"},
            "prompt": "provider-secret-prompt",
        }
    )
    record = logging.LogRecord(
        name="xianwen.ai",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg={"provider_metadata": sanitized},
        args=(),
        exc_info=None,
    )
    rendered = JsonFormatter().format(record)
    assert "safe-request-id" in rendered
    assert "provider-secret" not in rendered
