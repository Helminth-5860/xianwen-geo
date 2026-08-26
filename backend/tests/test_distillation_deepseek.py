import json
import uuid
from dataclasses import replace

import httpx
import pytest

from apps.ai.contracts import AdapterCredential, AIModelCapability
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.models import AICapabilityRuntimeConfig, APICredentialCapabilityBinding
from apps.ai.runtime import AICapabilityRuntimeSnapshot
from apps.keywords.distillation_contracts import (
    DistillationKeywordInput,
    DistillationRequest,
)
from apps.keywords.distillation_exceptions import (
    DistillationInvalidResponse,
    DistillationProviderUnavailable,
)
from apps.keywords.distillation_providers import DeepSeekDistillationProvider
from apps.keywords.distillation_validation import validate_provider_response


class CredentialResolver:
    def resolve(self, provider_key):
        assert provider_key == "deepseek"
        return AdapterCredential("test-only-distillation-provider-credential")


def runtime_snapshot(**kwargs):
    assert kwargs == {
        "provider_key": "deepseek",
        "capability": AIModelCapability.KEYWORD_DISTILLATION,
    }
    return AICapabilityRuntimeSnapshot(
        runtime_id="runtime-distillation-1",
        model_id="model-deepseek-1",
        provider_key="deepseek",
        model_key="deepseek",
        capability=AIModelCapability.KEYWORD_DISTILLATION,
        provider_model_id="deepseek-chat",
        api_version="",
        timeout_seconds=45,
        max_retries=2,
        retry_base_seconds=30,
        version=1,
    )


def distillation_request():
    keyword_ids = [str(uuid.UUID(int=index + 1)) for index in range(3)]
    return DistillationRequest(
        job_id=str(uuid.UUID(int=100)),
        subject_id=str(uuid.UUID(int=101)),
        subject_version_id=str(uuid.UUID(int=102)),
        keyword_set_version_id=str(uuid.UUID(int=103)),
        subject_values={
            "official_name": "显问科技",
            "main_business": "GEO 智能分析",
            "target_users": "企业客户",
            "contact_name": "不得发送",
            "contact_phone": "13800000000",
            "unrelated_internal_field": "不得发送",
        },
        keywords=tuple(
            DistillationKeywordInput(
                id=keyword_id,
                text=("企业 GEO 服务", "GEO 企业服务", "无关旧词")[index],
                structure_type="long_tail",
                is_regional=False,
                region_level="",
                region_text="",
                region_matching_key="",
                business_category="GEO 服务",
                search_intent="commercial",
                relevance_score=90 - index,
                priority="high",
            )
            for index, keyword_id in enumerate(keyword_ids)
        ),
    )


def _provider_response(request, content, *, input_count=3):
    payload = json.loads(request.content)
    assert request.headers["Authorization"] == ("Bearer test-only-distillation-provider-credential")
    assert payload["model"] == "deepseek-chat"
    assert payload["response_format"] == {"type": "json_object"}
    user_payload = json.loads(payload["messages"][1]["content"])
    assert user_payload["task"] in {
        "distill_geo_keywords",
        "repair_geo_keyword_distillation_json",
    }
    assert user_payload["subject"] == {
        "official_name": "显问科技",
        "main_business": "GEO 智能分析",
        "target_users": "企业客户",
    }
    assert len(user_payload["keywords"]) == input_count
    return httpx.Response(
        200,
        json={
            "id": "provider-distillation-request-1",
            "model": "deepseek-chat",
            "choices": [
                {
                    "message": {"content": json.dumps(content, ensure_ascii=False)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 180,
                "completion_tokens": 120,
                "total_tokens": 300,
            },
        },
    )


def test_deepseek_distillation_uses_capability_runtime_and_existing_contract():
    request = distillation_request()
    group_key = str(uuid.UUID(int=200))
    canonical_id = request.keywords[0].id
    content = {
        "items": [
            {
                "source_keyword_id": request.keywords[0].id,
                # DeepSeek commonly keeps the canonical item and marks only
                # the duplicate as merge. The adapter safely promotes this
                # same-region canonical item into the merge group.
                "action": "keep",
                "canonical_keyword_id": None,
                "merge_group_key": None,
                "reason": "保留为统一表达",
            },
            {
                "source_keyword_id": request.keywords[1].id,
                "action": "merge",
                "canonical_keyword_id": canonical_id,
                "merge_group_key": group_key,
                "reason": "与标准表达语义重复",
            },
            {
                "source_keyword_id": request.keywords[2].id,
                "action": "delete",
                "canonical_keyword_id": None,
                "merge_group_key": None,
                "reason": "与当前主体业务无关",
            },
        ]
    }

    provider = DeepSeekDistillationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(lambda raw: _provider_response(raw, content)),
        runtime_resolver=runtime_snapshot,
    )
    response = provider.distill(request)

    normalized = validate_provider_response(inputs=request.keywords, response=response)
    assert [item.action for item in normalized] == ["merge", "merge", "delete"]
    assert response.model_key == "deepseek"
    assert response.provider_metrics == {
        "provider_model_id": "deepseek-chat",
        "provider_request_id": "provider-distillation-request-1",
        "total_tokens": 300,
        "request_count": 1,
    }


def test_deepseek_distillation_invalid_schema_fails_closed():
    request = distillation_request()
    provider = DeepSeekDistillationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(
            lambda raw: _provider_response(raw, {"items": [{"action": "keep"}]})
        ),
        runtime_resolver=runtime_snapshot,
    )

    with pytest.raises(DistillationInvalidResponse):
        provider.distill(request)


def test_deepseek_distillation_does_not_merge_across_regions():
    request = distillation_request()
    request = replace(
        request,
        keywords=(
            replace(
                request.keywords[0],
                is_regional=True,
                region_matching_key="440100",
            ),
            replace(
                request.keywords[1],
                is_regional=True,
                region_matching_key="110100",
            ),
            request.keywords[2],
        ),
    )
    group_key = str(uuid.UUID(int=201))
    content = {
        "items": [
            {
                "source_keyword_id": request.keywords[0].id,
                "action": "keep",
                "canonical_keyword_id": None,
                "merge_group_key": None,
                "reason": "保留标准表达",
            },
            {
                "source_keyword_id": request.keywords[1].id,
                "action": "merge",
                "canonical_keyword_id": request.keywords[0].id,
                "merge_group_key": group_key,
                "reason": "模型错误地跨地域合并",
            },
            {
                "source_keyword_id": request.keywords[2].id,
                "action": "delete",
                "canonical_keyword_id": None,
                "merge_group_key": None,
                "reason": "与主体无关",
            },
        ]
    }
    provider = DeepSeekDistillationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(lambda raw: _provider_response(raw, content)),
        runtime_resolver=runtime_snapshot,
    )

    with pytest.raises(DistillationInvalidResponse):
        provider.distill(request)


def test_deepseek_distillation_repairs_semantic_schema_once():
    request = distillation_request()
    request_payloads = []

    def handler(raw):
        payload = json.loads(raw.content)
        user_payload = json.loads(payload["messages"][1]["content"])
        request_payloads.append(user_payload)
        source_rows = [
            {
                "source_keyword_id": item.id,
                "action": "keep",
                "canonical_keyword_id": None,
                "merge_group_key": None,
                "reason": "保留当前关键词",
            }
            for item in request.keywords
        ]
        # The first response omits one ID. Complete coverage is a domain
        # contract error, so the provider must repair exactly once.
        if len(request_payloads) == 1:
            source_rows = source_rows[:-1]
        return _provider_response(raw, {"items": source_rows})

    provider = DeepSeekDistillationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )
    response = provider.distill(request)

    assert [payload["task"] for payload in request_payloads] == [
        "distill_geo_keywords",
        "repair_geo_keyword_distillation_json",
    ]
    assert request_payloads[1]["required_source_keyword_ids"] == [
        item.id for item in request.keywords
    ]
    assert len(validate_provider_response(inputs=request.keywords, response=response)) == 3
    assert response.provider_metrics["request_count"] == 2


def test_deepseek_distillation_accepts_finite_wrappers_aliases_and_empty_optionals():
    request = distillation_request()
    content = {
        "results": [
            {
                "source_keyword_id": request.keywords[0].id,
                "action": "RETAIN",
                "canonical_keyword_id": "",
                "merge_group_key": "",
                "reason": "保留核心表达",
            },
            {
                "source_keyword_id": request.keywords[1].id,
                "action": "删除",
                "canonical_keyword_id": "",
                "merge_group_key": "",
                "reason": "表达重复且价值较低",
            },
            {
                "source_keyword_id": request.keywords[2].id,
                "action": "low-value",
                "canonical_keyword_id": "",
                "merge_group_key": "",
                "reason": "业务相关度较低",
            },
        ]
    }
    provider = DeepSeekDistillationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(lambda raw: _provider_response(raw, content)),
        runtime_resolver=runtime_snapshot,
    )

    response = provider.distill(request)

    assert [item.action for item in response.items] == ["keep", "delete", "low_value"]
    assert response.provider_metrics["request_count"] == 1


def test_deepseek_distillation_preserves_complete_coverage_for_32_inputs():
    base = distillation_request()
    request = replace(
        base,
        keywords=tuple(
            replace(
                base.keywords[index % len(base.keywords)],
                id=str(uuid.UUID(int=index + 1)),
                text=f"测试关键词 {index + 1}",
            )
            for index in range(32)
        ),
    )

    def handler(raw):
        payload = json.loads(raw.content)
        user_payload = json.loads(payload["messages"][1]["content"])
        assert len(user_payload["keywords"]) == 32
        return _provider_response(
            raw,
            {
                "items": [
                    {
                        "source_keyword_id": item.id,
                        "action": "keep",
                        "canonical_keyword_id": None,
                        "merge_group_key": None,
                        "reason": "保留当前关键词",
                    }
                    for item in request.keywords
                ]
            },
            input_count=32,
        )

    provider = DeepSeekDistillationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )

    response = provider.distill(request)

    assert len(validate_provider_response(inputs=request.keywords, response=response)) == 32
    assert response.provider_metrics["request_count"] == 1


def test_deepseek_distillation_fails_after_one_repair_with_safe_diagnostic():
    request = distillation_request()
    request_count = 0

    def handler(raw):
        nonlocal request_count
        request_count += 1
        return _provider_response(
            raw,
            {
                "items": [
                    {
                        "source_keyword_id": request.keywords[0].id,
                        "action": "keep",
                        "canonical_keyword_id": None,
                        "merge_group_key": None,
                        "reason": "仅返回一项",
                    }
                ]
            },
        )

    provider = DeepSeekDistillationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )

    with pytest.raises(DistillationInvalidResponse) as error:
        provider.distill(request)

    assert request_count == 2
    assert error.value.diagnostic["input_count"] == 3
    assert error.value.diagnostic["actual_structure"]["item_count"] == 1
    assert "invalid_output" not in json.dumps(error.value.diagnostic, ensure_ascii=False)


def test_deepseek_distillation_fails_closed_without_capability_runtime():
    def unavailable_runtime(**kwargs):
        raise AIAdapterError(
            AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
            stable_code="AI_CAPABILITY_RUNTIME_CONFIG_MISSING",
            retryable=False,
        )

    provider = DeepSeekDistillationProvider(
        credential_resolver=CredentialResolver(),
        runtime_resolver=unavailable_runtime,
    )

    with pytest.raises(DistillationProviderUnavailable):
        provider.ensure_available()


@pytest.mark.django_db
def test_deepseek_distillation_capability_rows_are_seeded_disabled():
    runtime = AICapabilityRuntimeConfig.objects.get(
        model__model_key="deepseek",
        capability="keyword_distillation",
    )
    bindings = APICredentialCapabilityBinding.objects.filter(
        provider__provider_key="deepseek",
        capability="keyword_distillation",
    )

    assert runtime.enabled is False
    assert runtime.provider_model_id == ""
    assert set(bindings.values_list("environment", "enabled")) == {
        ("staging", False),
        ("production", False),
    }
