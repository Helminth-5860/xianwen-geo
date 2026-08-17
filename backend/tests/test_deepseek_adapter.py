from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest
from django.core.management import call_command

from apps.ai.adapters.deepseek import (
    DEEPSEEK_BASE_URL,
    DeepSeekDetectionAdapter,
    register_deepseek_adapter,
)
from apps.ai.contracts import (
    AdapterCredential,
    AIAdapterRequest,
    AIModelCapability,
)
from apps.ai.detection import DetectionOutput, DetectionPayload
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.exceptions import AICredentialStateConflict
from apps.ai.models import AIModel
from apps.ai.registry import AIModelRegistry
from apps.ai.runtime import resolve_detection_adapter


@dataclass
class StaticCredentialResolver:
    value: str = "test-deepseek-secret"

    def resolve(self, provider_key: str) -> AdapterCredential:
        assert provider_key == "deepseek"
        return AdapterCredential(self.value)


class MissingCredentialResolver:
    def resolve(self, provider_key: str) -> AdapterCredential:
        del provider_key
        raise AICredentialStateConflict


def response_payload(
    *,
    content: str = "云计算是一种通过网络按需使用计算资源的服务模式。",
    finish_reason: str = "stop",
    model: str = "deepseek-v4-flash",
) -> dict[str, object]:
    return {
        "id": "deepseek-request-safe-id",
        "choices": [
            {
                "finish_reason": finish_reason,
                "index": 0,
                "message": {
                    "content": content,
                    "reasoning_content": "must-not-be-retained",
                    "role": "assistant",
                },
            }
        ],
        "created": 1_777_777_777,
        "model": model,
        "system_fingerprint": "fp_safe_123",
        "object": "chat.completion",
        "usage": {
            "completion_tokens": 12,
            "prompt_tokens": 20,
            "prompt_cache_hit_tokens": 4,
            "prompt_cache_miss_tokens": 16,
            "total_tokens": 32,
        },
    }


def build_request(
    *,
    provider_model_id: str = "deepseek-v4-flash",
    web_search_requested: bool = False,
    metadata: dict[str, object] | None = None,
) -> AIAdapterRequest[DetectionPayload]:
    adapter = DeepSeekDetectionAdapter(credential_resolver=StaticCredentialResolver())
    return AIAdapterRequest(
        request_id="deepseek-contract-request-0001",
        correlation_id="deepseek-contract-correlation-0001",
        identity=adapter.descriptor.identity,
        capability=AIModelCapability.GEO_DETECTION,
        adapter_version=adapter.descriptor.adapter_version,
        prompt_version=adapter.descriptor.prompt_version,
        timeout_seconds=17,
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
    return DeepSeekDetectionAdapter(
        credential_resolver=StaticCredentialResolver(),
        transport=httpx.MockTransport(handler),
    )


def test_deepseek_normal_chinese_call_maps_request_response_usage_and_safe_metadata():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json=response_payload())

    adapter = adapter_with_handler(handler)
    request = build_request(metadata={"internal_trace": "must-not-be-sent"})
    response = adapter.invoke(request)

    assert captured["url"] == f"{DEEPSEEK_BASE_URL}/chat/completions"
    assert captured["authorization"] == "Bearer test-deepseek-secret"
    assert captured["json"] == {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": request.payload.system_prompt},
            {"role": "user", "content": request.payload.user_question},
        ],
        "stream": False,
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
        "max_tokens": 256,
    }
    assert "internal_trace" not in str(captured["json"])

    assert isinstance(response.output, DetectionOutput)
    assert response.output.raw_text.startswith("云计算")
    assert response.provider_request_id == "deepseek-request-safe-id"
    assert response.usage.input_tokens == 20
    assert response.usage.output_tokens == 12
    assert response.usage.total_tokens == 32
    assert response.finish_reason.value == "stop"
    assert response.sanitized_provider_metadata == {
        "provider_model_id": "deepseek-v4-flash",
        "system_fingerprint": "fp_safe_123",
        "prompt_cache_hit_tokens": 4,
        "prompt_cache_miss_tokens": 16,
    }
    assert "must-not-be-retained" not in repr(response)
    assert "test-deepseek-secret" not in repr(response)


def test_deepseek_uses_runtime_provider_model_id_without_hardcoded_legacy_alias():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=response_payload(model="deepseek-v4-pro"))

    adapter = adapter_with_handler(handler)
    response = adapter.invoke(build_request(provider_model_id="deepseek-v4-pro"))

    assert captured["model"] == "deepseek-v4-pro"
    assert response.output.provider_model_id == "deepseek-v4-pro"
    assert "deepseek-chat" not in json.dumps(captured)


def test_deepseek_web_search_request_is_truthfully_degraded_and_citations_are_not_fabricated():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=response_payload())

    adapter = adapter_with_handler(handler)
    response = adapter.invoke(build_request(web_search_requested=True))

    assert adapter.supports_web_search is False
    assert adapter.supports_structured_citations is False
    assert "web_search" not in captured
    assert "tools" not in captured
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
        (422, AIAdapterErrorCategory.INVALID_REQUEST, False),
        (429, AIAdapterErrorCategory.RATE_LIMIT, True),
        (500, AIAdapterErrorCategory.PROVIDER_INTERNAL, True),
        (503, AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE, True),
    ],
)
def test_deepseek_http_errors_are_normalized_without_provider_body_leak(
    status_code, category, retryable
):
    def handler(request: httpx.Request):
        del request
        return httpx.Response(
            status_code,
            json={"error": {"message": "provider-secret raw upstream body"}},
        )

    adapter = adapter_with_handler(handler)
    with pytest.raises(AIAdapterError) as failure:
        adapter.invoke(build_request())

    assert failure.value.category == category
    assert failure.value.retryable is retryable
    assert "provider-secret" not in str(failure.value)
    assert "provider-secret" not in repr(failure.value)


def test_deepseek_timeout_and_network_errors_are_retryable_and_single_call_only():
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


def test_deepseek_same_retry_request_is_deterministic_and_adapter_never_retries_internally():
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
        {"not": "json"},
        {"choices": []},
        {"choices": [{"finish_reason": "stop", "message": {"content": None}}], "usage": {}},
    ],
)
def test_deepseek_malformed_response_fails_closed(payload):
    def handler(request: httpx.Request):
        del request
        if payload == {"not": "json"}:
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(200, json=payload)

    with pytest.raises(AIAdapterError) as failure:
        adapter_with_handler(handler).invoke(build_request())
    assert failure.value.category == AIAdapterErrorCategory.RESPONSE_PARSE
    assert failure.value.retryable is False


def test_deepseek_insufficient_system_resource_is_retryable_provider_failure():
    def handler(request: httpx.Request):
        del request
        return httpx.Response(
            200,
            json=response_payload(finish_reason="insufficient_system_resource"),
        )

    with pytest.raises(AIAdapterError) as failure:
        adapter_with_handler(handler).invoke(build_request())
    assert failure.value.category == AIAdapterErrorCategory.PROVIDER_INTERNAL
    assert failure.value.retryable is True


def test_deepseek_missing_database_credential_fails_closed_before_network():
    adapter = DeepSeekDetectionAdapter(
        credential_resolver=MissingCredentialResolver(),
        transport=httpx.MockTransport(
            lambda request: pytest.fail(f"network must not run: {request.url}")
        ),
    )
    with pytest.raises(AIAdapterError) as failure:
        adapter.invoke(build_request())
    assert failure.value.category == AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE
    assert failure.value.stable_code == "AI_DEEPSEEK_CREDENTIAL_UNAVAILABLE"


def test_deepseek_registry_contract_is_geo_detection_only():
    registry = AIModelRegistry()
    register_deepseek_adapter(registry)
    resolved = registry.resolve(
        provider_key="deepseek",
        model_key="deepseek",
        capability=AIModelCapability.GEO_DETECTION,
    )
    assert isinstance(resolved, DeepSeekDetectionAdapter)
    assert resolved.descriptor.capabilities == frozenset({AIModelCapability.GEO_DETECTION})
    with pytest.raises(AIAdapterError) as unsupported:
        registry.resolve(
            provider_key="deepseek",
            model_key="deepseek",
            capability=AIModelCapability.TEXT_GENERATION,
        )
    assert unsupported.value.category == AIAdapterErrorCategory.UNSUPPORTED_CAPABILITY


@pytest.mark.django_db
def test_deepseek_runtime_snapshot_exposes_limits_and_pause_blocks_new_adapter_resolution():
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)
    config = AIModel.objects.get(model_key="deepseek").runtime_config
    config.provider_model_id = "deepseek-v4-flash"
    config.enabled = True
    config.timeout_seconds = 41
    config.max_concurrency = 3
    config.version += 1
    config.save()

    snapshot, adapter = resolve_detection_adapter(model_key="deepseek")
    assert snapshot.provider_model_id == "deepseek-v4-flash"
    assert snapshot.timeout_seconds == 41
    assert snapshot.max_concurrency == 3
    assert isinstance(adapter, DeepSeekDetectionAdapter)

    config.paused = True
    config.pause_reason = "contract acceptance pause"
    config.version += 1
    config.save()
    with pytest.raises(AIAdapterError) as paused:
        resolve_detection_adapter(model_key="deepseek")
    assert paused.value.stable_code == "AI_MODEL_PAUSED"
