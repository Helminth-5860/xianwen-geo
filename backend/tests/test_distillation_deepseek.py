import json
import uuid

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


def _provider_response(request, content):
    payload = json.loads(request.content)
    assert request.headers["Authorization"] == ("Bearer test-only-distillation-provider-credential")
    assert payload["model"] == "deepseek-chat"
    assert payload["response_format"] == {"type": "json_object"}
    user_payload = json.loads(payload["messages"][1]["content"])
    assert user_payload["task"] == "distill_geo_keywords"
    assert user_payload["subject"] == {
        "official_name": "显问科技",
        "main_business": "GEO 智能分析",
        "target_users": "企业客户",
    }
    assert len(user_payload["keywords"]) == 3
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
                "action": "merge",
                "canonical_keyword_id": canonical_id,
                "merge_group_key": group_key,
                "reason": "含义相同，合并为统一表达",
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
