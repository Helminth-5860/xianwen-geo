from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest
from django.core.management import call_command

from apps.ai.adapters.doubao import (
    DOUBAO_BASE_URL,
    DoubaoDetectionAdapter,
    register_doubao_adapter,
)
from apps.ai.contracts import AdapterCredential, AIAdapterRequest, AIModelCapability
from apps.ai.detection import DetectionOutput, DetectionPayload
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.exceptions import AICredentialCryptoFailure, AICredentialStateConflict
from apps.ai.models import AIModel
from apps.ai.registry import AIModelRegistry
from apps.ai.runtime import resolve_detection_adapter


@dataclass
class StaticCredentialResolver:
    value: str = "test-doubao-secret"

    def resolve(self, provider_key: str) -> AdapterCredential:
        assert provider_key == "doubao"
        return AdapterCredential(self.value)


class MissingCredentialResolver:
    def resolve(self, provider_key: str) -> AdapterCredential:
        del provider_key
        raise AICredentialStateConflict


class BrokenCredentialResolver:
    def resolve(self, provider_key: str) -> AdapterCredential:
        del provider_key
        raise AICredentialCryptoFailure


def response_payload(
    *,
    content: str = "云计算是一种通过网络按需使用计算资源的服务模式。",
    model: str = "doubao-seed-2-0-lite-260215",
) -> dict[str, object]:
    return {
        "id": "doubao-request-safe-id",
        "object": "response",
        "model": model,
        "status": "completed",
        "service_tier": "default",
        "output": [
            {
                "id": "reasoning-safe-id",
                "type": "reasoning",
                "summary": [{"text": "must-not-be-retained"}],
            },
            {
                "id": "message-safe-id",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": content}],
            },
        ],
        "thinking": {"type": "disabled"},
        "usage": {
            "input_tokens": 20,
            "output_tokens": 12,
            "total_tokens": 32,
            "input_tokens_details": {"cached_tokens": 4},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def build_request(
    *,
    provider_model_id: str = "doubao-seed-2-0-lite-260215",
    web_search_requested: bool = False,
    metadata: dict[str, object] | None = None,
) -> AIAdapterRequest[DetectionPayload]:
    adapter = DoubaoDetectionAdapter(credential_resolver=StaticCredentialResolver())
    return AIAdapterRequest(
        request_id="doubao-contract-request-0001",
        correlation_id="doubao-contract-correlation-0001",
        identity=adapter.descriptor.identity,
        capability=AIModelCapability.GEO_DETECTION,
        adapter_version=adapter.descriptor.adapter_version,
        prompt_version=adapter.descriptor.prompt_version,
        timeout_seconds=19,
        payload=DetectionPayload(
            provider_model_id=provider_model_id,
            system_prompt="你是一个面向普通用户的中文信息助手。请直接回答问题。",
            user_question="什么是云计算？",
            web_search_requested=web_search_requested,
            temperature=0.2,
            max_output_tokens=256,
        ),
        metadata=metadata or {},
    )


def adapter_with_handler(handler):
    return DoubaoDetectionAdapter(
        credential_resolver=StaticCredentialResolver(),
        transport=httpx.MockTransport(handler),
    )


def test_doubao_normal_chinese_call_maps_responses_contract_usage_and_safe_metadata():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json=response_payload())

    adapter = adapter_with_handler(handler)
    request = build_request(metadata={"internal_trace": "must-not-be-sent"})
    response = adapter.invoke(request)

    assert captured["url"] == f"{DOUBAO_BASE_URL}/responses"
    assert captured["authorization"] == "Bearer test-doubao-secret"
    assert captured["json"] == {
        "model": "doubao-seed-2-0-lite-260215",
        "instructions": request.payload.system_prompt,
        "input": request.payload.user_question,
        "stream": False,
        "store": False,
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
        "max_output_tokens": 256,
    }
    assert "internal_trace" not in str(captured["json"])

    assert isinstance(response.output, DetectionOutput)
    assert response.output.raw_text.startswith("云计算")
    assert response.provider_request_id == "doubao-request-safe-id"
    assert response.usage.input_tokens == 20
    assert response.usage.output_tokens == 12
    assert response.usage.total_tokens == 32
    assert response.finish_reason.value == "stop"
    assert response.sanitized_provider_metadata == {
        "provider_model_id": "doubao-seed-2-0-lite-260215",
        "service_tier": "default",
        "cached_tokens": 4,
        "reasoning_tokens": 0,
    }
    assert "must-not-be-retained" not in repr(response)
    assert "test-doubao-secret" not in repr(response)


def test_doubao_uses_runtime_provider_model_id_without_hardcoded_model_alias():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json=response_payload(model="ep-20260817-production-alias"),
        )

    adapter = adapter_with_handler(handler)
    response = adapter.invoke(build_request(provider_model_id="ep-20260817-production-alias"))

    assert captured["model"] == "ep-20260817-production-alias"
    assert response.output.provider_model_id == "ep-20260817-production-alias"
    assert "doubao-seed" not in captured["model"]


def test_doubao_web_search_request_is_truthfully_degraded_without_tools_or_citations():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=response_payload())

    adapter = adapter_with_handler(handler)
    response = adapter.invoke(build_request(web_search_requested=True))

    assert adapter.supports_web_search is False
    assert adapter.supports_structured_citations is False
    assert "tools" not in captured
    assert "web_search" not in captured
    assert response.output.web_search_requested is True
    assert response.output.web_search_used is False
    assert response.output.degraded is True
    assert response.output.citations == ()


@pytest.mark.parametrize(
    ("status_code", "category", "retryable"),
    [
        (400, AIAdapterErrorCategory.INVALID_REQUEST, False),
        (401, AIAdapterErrorCategory.AUTHENTICATION, False),
        (402, AIAdapterErrorCategory.QUOTA_EXHAUSTED, False),
        (403, AIAdapterErrorCategory.PERMISSION, False),
        (404, AIAdapterErrorCategory.MODEL_UNAVAILABLE, False),
        (408, AIAdapterErrorCategory.TIMEOUT, True),
        (422, AIAdapterErrorCategory.INVALID_REQUEST, False),
        (429, AIAdapterErrorCategory.RATE_LIMIT, True),
        (500, AIAdapterErrorCategory.PROVIDER_INTERNAL, True),
        (502, AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE, True),
        (503, AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE, True),
        (504, AIAdapterErrorCategory.TIMEOUT, True),
        (418, AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE, False),
    ],
)
def test_doubao_http_errors_are_normalized_without_provider_body_leak(
    status_code, category, retryable
):
    def handler(request: httpx.Request):
        del request
        return httpx.Response(
            status_code,
            json={"error": {"message": "provider-secret raw upstream body"}},
        )

    with pytest.raises(AIAdapterError) as failure:
        adapter_with_handler(handler).invoke(build_request())

    assert failure.value.category == category
    assert failure.value.retryable is retryable
    assert "provider-secret" not in str(failure.value)
    assert "provider-secret" not in repr(failure.value)


def test_doubao_timeout_and_network_errors_are_retryable_and_single_call_only():
    timeout_calls = 0

    def timeout_handler(request: httpx.Request):
        nonlocal timeout_calls
        timeout_calls += 1
        raise httpx.ReadTimeout("provider-secret timeout", request=request)

    with pytest.raises(AIAdapterError) as timeout:
        adapter_with_handler(timeout_handler).invoke(build_request())
    assert timeout.value.category == AIAdapterErrorCategory.TIMEOUT
    assert timeout.value.retryable is True
    assert timeout.value.__cause__ is None
    assert timeout_calls == 1

    network_calls = 0

    def network_handler(request: httpx.Request):
        nonlocal network_calls
        network_calls += 1
        raise httpx.ConnectError("provider-secret network", request=request)

    with pytest.raises(AIAdapterError) as network:
        adapter_with_handler(network_handler).invoke(build_request())
    assert network.value.category == AIAdapterErrorCategory.NETWORK
    assert network.value.retryable is True
    assert network.value.__cause__ is None
    assert network_calls == 1


def test_doubao_same_retry_request_is_deterministic_and_adapter_never_retries_internally():
    bodies = []

    def handler(request: httpx.Request):
        bodies.append(request.content)
        return httpx.Response(200, json=response_payload())

    adapter = adapter_with_handler(handler)
    request = build_request()
    first = adapter.invoke(request)
    second = adapter.invoke(request)

    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    assert first.output.raw_text == second.output.raw_text


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        response_payload(model="bad model id"),
        response_payload(content="bad\x01text"),
        {"object": "response", "status": "in_progress", "output": []},
        {"object": "response", "status": "completed", "output": []},
        {
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": None}],
                }
            ],
            "usage": {},
        },
    ],
)
def test_doubao_malformed_success_response_fails_closed(payload):
    def handler(request: httpx.Request):
        del request
        if payload == "not-json":
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(200, json=payload)

    with pytest.raises(AIAdapterError) as failure:
        adapter_with_handler(handler).invoke(build_request())
    assert failure.value.category == AIAdapterErrorCategory.RESPONSE_PARSE
    assert failure.value.retryable is False


@pytest.mark.parametrize(
    ("resolver", "stable_code"),
    [
        (MissingCredentialResolver(), "AI_DOUBAO_CREDENTIAL_UNAVAILABLE"),
        (BrokenCredentialResolver(), "AI_DOUBAO_CREDENTIAL_CRYPTO_FAILURE"),
    ],
)
def test_doubao_database_credential_failures_close_before_network(resolver, stable_code):
    adapter = DoubaoDetectionAdapter(
        credential_resolver=resolver,
        transport=httpx.MockTransport(
            lambda request: pytest.fail(f"network must not run: {request.url}")
        ),
    )
    with pytest.raises(AIAdapterError) as failure:
        adapter.invoke(build_request())
    assert failure.value.category == AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE
    assert failure.value.stable_code == stable_code


def test_doubao_registry_contract_is_geo_detection_only():
    registry = AIModelRegistry()
    register_doubao_adapter(registry)
    resolved = registry.resolve(
        provider_key="doubao",
        model_key="doubao",
        capability=AIModelCapability.GEO_DETECTION,
    )
    assert isinstance(resolved, DoubaoDetectionAdapter)
    assert resolved.descriptor.capabilities == frozenset({AIModelCapability.GEO_DETECTION})
    with pytest.raises(AIAdapterError) as unsupported:
        registry.resolve(
            provider_key="doubao",
            model_key="doubao",
            capability=AIModelCapability.TEXT_GENERATION,
        )
    assert unsupported.value.category == AIAdapterErrorCategory.UNSUPPORTED_CAPABILITY


@pytest.mark.django_db
def test_doubao_runtime_snapshot_exposes_limits_and_pause_blocks_new_adapter_resolution():
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)
    config = AIModel.objects.get(model_key="doubao").runtime_config
    config.provider_model_id = "ep-20260817-production-alias"
    config.enabled = True
    config.timeout_seconds = 43
    config.max_concurrency = 5
    config.version += 1
    config.save()

    snapshot, adapter = resolve_detection_adapter(model_key="doubao")
    assert snapshot.provider_model_id == "ep-20260817-production-alias"
    assert snapshot.timeout_seconds == 43
    assert snapshot.max_concurrency == 5
    assert isinstance(adapter, DoubaoDetectionAdapter)

    config.paused = True
    config.pause_reason = "contract acceptance pause"
    config.version += 1
    config.save()
    with pytest.raises(AIAdapterError) as paused:
        resolve_detection_adapter(model_key="doubao")
    assert paused.value.stable_code == "AI_MODEL_PAUSED"
