from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest
from django.core.management import call_command

from apps.ai.adapters.glm import GLMDetectionAdapter
from apps.ai.adapters.hunyuan import HunyuanDetectionAdapter
from apps.ai.adapters.kimi import KimiDetectionAdapter
from apps.ai.adapters.qwen import QwenDetectionAdapter
from apps.ai.adapters.spark import SparkDetectionAdapter
from apps.ai.adapters.wenxin import WenxinDetectionAdapter
from apps.ai.contracts import AdapterCredential, AIAdapterRequest, AIModelCapability
from apps.ai.detection import DetectionPayload
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.exceptions import AICredentialStateConflict
from apps.ai.models import AIModel
from apps.ai.registry import AIModelRegistry
from apps.ai.runtime import resolve_detection_adapter

PROVIDERS = (
    ("qwen", QwenDetectionAdapter, "qwen-plus"),
    ("hunyuan", HunyuanDetectionAdapter, "hunyuan-turbos-latest"),
    ("wenxin", WenxinDetectionAdapter, "ernie-4.5-turbo-128k"),
    ("kimi", KimiDetectionAdapter, "kimi-k3"),
    ("glm", GLMDetectionAdapter, "glm-5.2"),
    ("spark", SparkDetectionAdapter, "generalv3.5"),
)


@dataclass
class StaticCredentialResolver:
    provider_key: str
    value: str = "test-provider-secret"

    def resolve(self, provider_key: str) -> AdapterCredential:
        assert provider_key == self.provider_key
        return AdapterCredential(self.value)


class MissingCredentialResolver:
    def resolve(self, provider_key: str) -> AdapterCredential:
        del provider_key
        raise AICredentialStateConflict


def response_payload(
    *,
    model: str,
    content: str = "云计算是一种通过网络按需使用计算资源的服务模式。",
    finish_reason: str = "stop",
) -> dict[str, object]:
    return {
        "id": "provider-request-safe-id",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": "must-not-be-retained",
                },
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 12,
            "total_tokens": 32,
        },
        "system_fingerprint": "safe-fingerprint",
    }


def build_request(adapter, *, provider_model_id: str, web_search_requested: bool = False):
    return AIAdapterRequest(
        request_id=f"{adapter.descriptor.identity.provider_key}-request-0001",
        correlation_id=None,
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
    )


@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
def test_provider_wave_normal_chinese_call_maps_contract(provider_key, adapter_cls, model_id):
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=response_payload(model=model_id))

    adapter = adapter_cls(
        credential_resolver=StaticCredentialResolver(provider_key),
        transport=httpx.MockTransport(handler),
    )
    response = adapter.invoke(build_request(adapter, provider_model_id=model_id))

    assert captured["authorization"] == "Bearer test-provider-secret"
    assert captured["body"]["model"] == model_id
    assert captured["body"]["messages"] == [
        {"role": "system", "content": "你是一个面向普通用户的中文信息助手。请直接回答问题。"},
        {"role": "user", "content": "什么是云计算？"},
    ]
    assert captured["body"]["stream"] is False
    if provider_key == "kimi":
        assert "temperature" not in captured["body"]
        assert captured["body"]["reasoning_effort"] == "low"
    else:
        assert captured["body"]["temperature"] == 0.2
    assert captured["body"]["max_tokens"] == 256
    assert response.output.raw_text.startswith("云计算")
    assert response.usage.input_tokens == 20
    assert response.usage.output_tokens == 12
    assert response.usage.total_tokens == 32
    assert response.provider_request_id == "provider-request-safe-id"
    assert response.output.provider_model_id == model_id
    assert response.finish_reason.value == "stop"
    assert "reasoning_content" not in response.sanitized_provider_metadata
    assert response.sanitized_provider_metadata["provider_model_id"] == model_id


def test_kimi_k26_uses_supported_fast_request_shape():
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=response_payload(model="kimi-k2.6"))

    adapter = KimiDetectionAdapter(
        credential_resolver=StaticCredentialResolver("kimi"),
        transport=httpx.MockTransport(handler),
    )
    adapter.invoke(build_request(adapter, provider_model_id="kimi-k2.6"))

    assert "temperature" not in captured["body"]
    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in captured["body"]


@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
def test_provider_wave_web_search_request_is_truthfully_degraded(
    provider_key, adapter_cls, model_id
):
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert "tools" not in body
        assert "web_search" not in body
        return httpx.Response(200, json=response_payload(model=model_id))

    adapter = adapter_cls(
        credential_resolver=StaticCredentialResolver(provider_key),
        transport=httpx.MockTransport(handler),
    )
    response = adapter.invoke(
        build_request(
            adapter,
            provider_model_id=model_id,
            web_search_requested=True,
        )
    )
    assert response.output.web_search_requested is True
    assert response.output.web_search_used is False
    assert response.output.degraded is True
    assert response.output.citations == ()


@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
@pytest.mark.parametrize(
    ("status_code", "category"),
    (
        (401, AIAdapterErrorCategory.AUTHENTICATION),
        (403, AIAdapterErrorCategory.PERMISSION),
        (404, AIAdapterErrorCategory.MODEL_UNAVAILABLE),
        (408, AIAdapterErrorCategory.TIMEOUT),
        (422, AIAdapterErrorCategory.INVALID_REQUEST),
        (429, AIAdapterErrorCategory.RATE_LIMIT),
        (500, AIAdapterErrorCategory.PROVIDER_INTERNAL),
        (503, AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE),
    ),
)
def test_provider_wave_http_errors_are_normalized(
    provider_key,
    adapter_cls,
    model_id,
    status_code,
    category,
):
    def handler(request: httpx.Request):
        del request
        return httpx.Response(status_code, json={"error": {"message": "must-not-leak"}})

    adapter = adapter_cls(
        credential_resolver=StaticCredentialResolver(provider_key),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AIAdapterError) as raised:
        adapter.invoke(build_request(adapter, provider_model_id=model_id))
    assert raised.value.category == category
    assert "must-not-leak" not in str(raised.value)


@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
def test_provider_wave_timeout_and_network_do_not_retry(provider_key, adapter_cls, model_id):
    calls = {"timeout": 0, "network": 0}

    def timeout_handler(request: httpx.Request):
        del request
        calls["timeout"] += 1
        raise httpx.ReadTimeout("timeout")

    adapter = adapter_cls(
        credential_resolver=StaticCredentialResolver(provider_key),
        transport=httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(AIAdapterError) as timed_out:
        adapter.invoke(build_request(adapter, provider_model_id=model_id))
    assert timed_out.value.category == AIAdapterErrorCategory.TIMEOUT
    assert calls["timeout"] == 1

    def network_handler(request: httpx.Request):
        del request
        calls["network"] += 1
        raise httpx.ConnectError("network")

    adapter = adapter_cls(
        credential_resolver=StaticCredentialResolver(provider_key),
        transport=httpx.MockTransport(network_handler),
    )
    with pytest.raises(AIAdapterError) as network:
        adapter.invoke(build_request(adapter, provider_model_id=model_id))
    assert network.value.category == AIAdapterErrorCategory.NETWORK
    assert calls["network"] == 1


@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
def test_provider_wave_request_is_deterministic_and_single_attempt(
    provider_key, adapter_cls, model_id
):
    bodies = []

    def handler(request: httpx.Request):
        bodies.append(request.content)
        return httpx.Response(200, json=response_payload(model=model_id))

    transport = httpx.MockTransport(handler)
    adapter = adapter_cls(
        credential_resolver=StaticCredentialResolver(provider_key),
        transport=transport,
    )
    frozen = build_request(adapter, provider_model_id=model_id)
    adapter.invoke(frozen)
    adapter.invoke(frozen)

    assert len(bodies) == 2
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
def test_provider_wave_malformed_success_payload_fails_closed(provider_key, adapter_cls, model_id):
    invalid_payloads = (
        {},
        {"choices": []},
        {
            "model": model_id,
            "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
        {
            "model": model_id,
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": "1", "completion_tokens": 1, "total_tokens": 2},
        },
    )

    for payload in invalid_payloads:
        adapter = adapter_cls(
            credential_resolver=StaticCredentialResolver(provider_key),
            transport=httpx.MockTransport(
                lambda request, payload=payload: httpx.Response(200, json=payload)
            ),
        )
        with pytest.raises(AIAdapterError) as raised:
            adapter.invoke(build_request(adapter, provider_model_id=model_id))
        assert raised.value.category == AIAdapterErrorCategory.RESPONSE_PARSE


@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
def test_provider_wave_missing_credential_fails_before_network(provider_key, adapter_cls, model_id):
    calls = {"count": 0}

    def handler(request: httpx.Request):
        del request
        calls["count"] += 1
        return httpx.Response(200, json=response_payload(model=model_id))

    adapter = adapter_cls(
        credential_resolver=MissingCredentialResolver(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AIAdapterError) as raised:
        adapter.invoke(build_request(adapter, provider_model_id=model_id))
    assert raised.value.category == AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE
    assert calls["count"] == 0


@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
def test_provider_wave_registry_exposes_geo_only(provider_key, adapter_cls, model_id):
    del model_id
    registry = AIModelRegistry()
    adapter_cls_instance = adapter_cls(credential_resolver=StaticCredentialResolver(provider_key))
    registry.register(adapter_cls_instance.descriptor, adapter_cls)

    resolved = registry.resolve(
        provider_key=provider_key,
        model_key=provider_key,
        capability=AIModelCapability.GEO_DETECTION,
    )
    assert isinstance(resolved, adapter_cls)

    with pytest.raises(AIAdapterError) as unsupported:
        registry.resolve(
            provider_key=provider_key,
            model_key=provider_key,
            capability=AIModelCapability.TEXT_GENERATION,
        )
    assert unsupported.value.category == AIAdapterErrorCategory.UNSUPPORTED_CAPABILITY


@pytest.mark.django_db
@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
def test_provider_wave_runtime_snapshot_and_pause_boundary(provider_key, adapter_cls, model_id):
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)
    config = AIModel.objects.get(model_key=provider_key).runtime_config
    config.provider_model_id = model_id
    config.enabled = True
    config.timeout_seconds = 31
    config.max_concurrency = 4
    config.version += 1
    config.save()

    snapshot, adapter = resolve_detection_adapter(model_key=provider_key)
    assert snapshot.provider_model_id == model_id
    assert snapshot.timeout_seconds == 31
    assert snapshot.max_concurrency == 4
    assert isinstance(adapter, adapter_cls)

    config.paused = True
    config.pause_reason = "provider wave pause"
    config.version += 1
    config.save()
    with pytest.raises(AIAdapterError) as paused:
        resolve_detection_adapter(model_key=provider_key)
    assert paused.value.stable_code == "AI_MODEL_PAUSED"


@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
def test_provider_wave_finish_reason_mapping(provider_key, adapter_cls, model_id):
    for upstream, expected in (
        ("stop", "stop"),
        ("length", "length"),
        ("content_filter", "content_filter"),
        ("tool_calls", "tool_call"),
        ("provider_specific", "unknown"),
    ):
        adapter = adapter_cls(
            credential_resolver=StaticCredentialResolver(provider_key),
            transport=httpx.MockTransport(
                lambda request, upstream=upstream: httpx.Response(
                    200,
                    json=response_payload(model=model_id, finish_reason=upstream),
                )
            ),
        )
        response = adapter.invoke(build_request(adapter, provider_model_id=model_id))
        assert response.finish_reason.value == expected


@pytest.mark.parametrize(("provider_key", "adapter_cls", "model_id"), PROVIDERS)
def test_provider_wave_response_model_id_must_be_safe(provider_key, adapter_cls, model_id):
    payload = response_payload(model=model_id)
    payload["model"] = "invalid/model/id"

    adapter = adapter_cls(
        credential_resolver=StaticCredentialResolver(provider_key),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    with pytest.raises(AIAdapterError) as raised:
        adapter.invoke(build_request(adapter, provider_model_id=model_id))
    assert raised.value.category == AIAdapterErrorCategory.RESPONSE_PARSE


def test_spark_official_nonstream_shape_uses_sid_and_request_model_fallback():
    payload = {
        "code": 0,
        "message": "Success",
        "sid": "spark-safe-sid",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "星火返回正常。",
                },
            }
        ],
        "usage": {
            "prompt_tokens": 6,
            "completion_tokens": 8,
            "total_tokens": 14,
        },
    }
    adapter = SparkDetectionAdapter(
        credential_resolver=StaticCredentialResolver("spark"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    response = adapter.invoke(build_request(adapter, provider_model_id="generalv3.5"))
    assert response.output.provider_model_id == "generalv3.5"
    assert response.provider_request_id == "spark-safe-sid"
    assert response.finish_reason.value == "unknown"


@pytest.mark.parametrize(
    ("code", "category"),
    (
        (10013, AIAdapterErrorCategory.CONTENT_POLICY),
        (11201, AIAdapterErrorCategory.RATE_LIMIT),
        (11200, AIAdapterErrorCategory.PERMISSION),
        (10907, AIAdapterErrorCategory.INVALID_REQUEST),
    ),
)
def test_spark_http_200_business_errors_fail_closed(code, category):
    adapter = SparkDetectionAdapter(
        credential_resolver=StaticCredentialResolver("spark"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"code": code, "message": "must-not-leak"},
            )
        ),
    )
    with pytest.raises(AIAdapterError) as raised:
        adapter.invoke(build_request(adapter, provider_model_id="generalv3.5"))
    assert raised.value.category == category
    assert "must-not-leak" not in str(raised.value)
