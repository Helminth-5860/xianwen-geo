import json

import httpx
import pytest

from apps.ai.contracts import AdapterCredential
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.models import AICapabilityRuntimeConfig, APICredentialCapabilityBinding
from apps.ai.runtime import AICapabilityRuntimeSnapshot
from apps.keywords.generation_contracts import KeywordGenerationRequest
from apps.keywords.generation_exceptions import KeywordGenerationProviderUnavailable
from apps.keywords.generation_providers import DeepSeekKeywordGenerationProvider


class CredentialResolver:
    def resolve(self, provider_key):
        assert provider_key == "deepseek"
        return AdapterCredential("test-only-provider-credential")


def runtime_snapshot(**kwargs):
    assert kwargs == {
        "provider_key": "deepseek",
        "capability": "keyword_generation",
    }
    return AICapabilityRuntimeSnapshot(
        runtime_id="runtime-1",
        model_id="model-1",
        provider_key="deepseek",
        model_key="deepseek",
        capability="keyword_generation",
        provider_model_id="deepseek-chat",
        api_version="",
        timeout_seconds=30,
        max_retries=2,
        retry_base_seconds=30,
        version=1,
    )


def generation_request():
    return KeywordGenerationRequest(
        job_id="job-1",
        subject_id="subject-1",
        subject_version_id="subject-version-1",
        subject_values={
            "official_name": "显问科技",
            "main_business": "GEO 智能分析",
            "target_users": "企业客户",
        },
        target_count=1,
        include_short=False,
        include_long_tail=False,
        include_regional=False,
        regions=(),
        historical_exclusions=("旧关键词",),
    )


def test_deepseek_keyword_provider_uses_capability_runtime_and_returns_typed_items():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-only-provider-credential"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-chat"
        assert payload["response_format"] == {"type": "json_object"}
        user_payload = json.loads(payload["messages"][1]["content"])
        assert user_payload["target_count"] == 1
        assert user_payload["exclusions"] == ["旧关键词"]
        return httpx.Response(
            200,
            json={
                "id": "provider-request-1",
                "model": "deepseek-chat",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "items": [
                                        {
                                            "text": "企业 GEO 优化",
                                            "structure_type": "general",
                                            "is_regional": False,
                                            "region_level": None,
                                            "region_text": None,
                                            "base_keyword": None,
                                            "business_category": "GEO 服务",
                                            "search_intent": "commercial",
                                            "relevance_score": 95,
                                            "priority": "high",
                                            "ai_reason": "与当前主营业务直接相关",
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 80,
                    "total_tokens": 180,
                },
            },
        )

    provider = DeepSeekKeywordGenerationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )
    response = provider.generate(generation_request())

    assert response.model_key == "deepseek"
    assert len(response.items) == 1
    assert response.items[0].text == "企业 GEO 优化"
    assert response.items[0].relevance_score == 95
    assert response.provider_metrics == {
        "provider_model_id": "deepseek-chat",
        "provider_request_id": "provider-request-1",
        "total_tokens": 180,
    }


def test_deepseek_keyword_provider_fails_closed_without_capability_runtime():
    def unavailable_runtime(**kwargs):
        raise AIAdapterError(
            AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
            stable_code="AI_CAPABILITY_RUNTIME_CONFIG_MISSING",
            retryable=False,
        )

    provider = DeepSeekKeywordGenerationProvider(
        credential_resolver=CredentialResolver(),
        runtime_resolver=unavailable_runtime,
    )

    with pytest.raises(KeywordGenerationProviderUnavailable):
        provider.ensure_available()


@pytest.mark.django_db
def test_deepseek_keyword_capability_rows_are_seeded_disabled():
    runtime = AICapabilityRuntimeConfig.objects.get(
        model__model_key="deepseek",
        capability="keyword_generation",
    )
    bindings = APICredentialCapabilityBinding.objects.filter(
        provider__provider_key="deepseek",
        capability="keyword_generation",
    )

    assert runtime.enabled is False
    assert runtime.provider_model_id == ""
    assert set(bindings.values_list("environment", "enabled")) == {
        ("staging", False),
        ("production", False),
    }
