import json
from dataclasses import replace

import httpx
import pytest

from apps.ai.contracts import AdapterCredential
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.models import AICapabilityRuntimeConfig, APICredentialCapabilityBinding
from apps.ai.runtime import AICapabilityRuntimeSnapshot
from apps.keywords.generation_contracts import KeywordGenerationRequest
from apps.keywords.generation_exceptions import (
    KeywordGenerationInvalidResponse,
    KeywordGenerationProviderUnavailable,
)
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


@pytest.mark.parametrize(
    ("raw_category", "expected_category"),
    (
        ("comparison", "competitor"),
        ("recommendation", "goal"),
        ("transactional", "product_category"),
    ),
)
def test_deepseek_keyword_provider_uses_capability_runtime_and_returns_typed_items(
    raw_category,
    expected_category,
):
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
                                            # DeepSeek can place an intent-catalog value in
                                            # the category field. The adapter applies only
                                            # finite, documented aliases.
                                            "business_category": raw_category,
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
    assert response.items[0].business_category == expected_category
    assert response.items[0].relevance_score == 95
    assert response.provider_metrics == {
        "provider_model_id": "deepseek-chat",
        "provider_request_id": "provider-request-1",
        "total_tokens": 180,
        "request_count": 1,
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


def test_deepseek_keyword_provider_repairs_schema_once_then_succeeds():
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][1]["content"])
        requests.append(user_payload)
        category = "unknown-category" if len(requests) == 1 else "service"
        return httpx.Response(
            200,
            json={
                "id": f"provider-request-{len(requests)}",
                "model": "deepseek-chat",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "keywords": [
                                        {
                                            "keyword": "企业 GEO 优化",
                                            "business_category": category,
                                            "search_intent": "commercial",
                                            "structure_type": "general",
                                            "regions": None,
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
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            },
        )

    provider = DeepSeekKeywordGenerationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )
    response = provider.generate(generation_request())

    assert len(requests) == 2
    assert requests[0]["task"] == "generate_geo_keywords"
    assert requests[1]["task"] == "repair_geo_keyword_json"
    assert response.items[0].business_category == "service"
    assert response.items[0].search_intents == ("recommendation",)
    assert response.provider_metrics["request_count"] == 2


def test_deepseek_keyword_provider_replaces_historical_duplicates_once():
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][1]["content"])
        requests.append(user_payload)
        keyword = "旧关键词" if len(requests) == 1 else "全新关键词"
        return httpx.Response(
            200,
            json={
                "id": f"provider-request-{len(requests)}",
                "model": "deepseek-chat",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "items": [
                                        {
                                            "text": keyword,
                                            "category": "service",
                                            "intents": ["recommendation"],
                                            "length_type": "general",
                                            "regions": [],
                                            "base_keyword": None,
                                            "notes": "",
                                            "relevance_score": 90,
                                            "priority": "high",
                                            "ai_reason": "与主营业务相关",
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    provider = DeepSeekKeywordGenerationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )
    response = provider.generate(generation_request())

    assert len(requests) == 2
    assert requests[0]["task"] == "generate_geo_keywords"
    assert requests[1]["task"] == "repair_geo_keyword_candidates"
    assert requests[1]["target_count"] == 1
    assert requests[1]["exclusions"] == ["旧关键词"]
    assert "invalid_output" not in requests[1]
    assert requests[1]["validation_diagnostic"]["root_cause"] == ("historical_keyword_overlap")
    assert requests[1]["validation_diagnostic"]["duplicate_keywords"] == ["旧关键词"]
    assert response.items[0].text == "全新关键词"
    assert response.provider_metrics["request_count"] == 2


def test_deepseek_keyword_provider_coerces_known_general_length_for_requested_modes():
    def handler(request):
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
                                            "text": "GEO优化",
                                            "category": "service",
                                            "intents": ["recommendation"],
                                            "length_type": "general",
                                            "regions": [],
                                            "base_keyword": None,
                                            "notes": "",
                                            "relevance_score": 90,
                                            "priority": "high",
                                            "ai_reason": "与主营业务相关",
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    provider = DeepSeekKeywordGenerationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )
    request = replace(
        generation_request(),
        include_short=True,
        include_long_tail=True,
        historical_exclusions=(),
    )
    response = provider.generate(request)

    assert response.items[0].structure_type == "short"
    assert response.provider_metrics["request_count"] == 1


def test_deepseek_keyword_provider_honours_selected_category_and_intent_subsets():
    captured = []

    def handler(request):
        payload = json.loads(request.content)
        captured.append(json.loads(payload["messages"][1]["content"]))
        ignored_subset = len(captured) == 1
        return httpx.Response(
            200,
            json={
                "id": f"provider-request-subset-{len(captured)}",
                "model": "deepseek-chat",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "items": [
                                        {
                                            "text": "企业 GEO 痛点解决方案",
                                            # Both values are valid globally, but the
                                            # model ignored the selected subsets.
                                            "category": (
                                                "service" if ignored_subset else "pain_point"
                                            ),
                                            "intents": (
                                                ["recommendation"]
                                                if ignored_subset
                                                else ["informational"]
                                            ),
                                            "length_type": "long_tail",
                                            "regions": [],
                                            "base_keyword": None,
                                            "notes": "",
                                            "relevance_score": 92,
                                            "priority": "high",
                                            "ai_reason": "符合用户需求",
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    provider = DeepSeekKeywordGenerationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )
    request = replace(
        generation_request(),
        include_long_tail=True,
        categories=("pain_point", "solution", "industry", "goal"),
        intents=("informational", "comparison", "local", "trust"),
        historical_exclusions=(),
    )

    response = provider.generate(request)

    assert [payload["task"] for payload in captured] == [
        "generate_geo_keywords",
        "repair_geo_keyword_json",
    ]
    assert all(payload["category_catalog"] == list(request.categories) for payload in captured)
    assert all(payload["intent_catalog"] == list(request.intents) for payload in captured)
    assert response.items[0].business_category == "pain_point"
    assert response.items[0].search_intents == ("informational",)
    assert response.provider_metrics["request_count"] == 2


def test_deepseek_keyword_provider_removes_only_extra_intents_with_a_valid_intersection():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": "provider-request-intent-intersection",
                "model": "deepseek-chat",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "items": [
                                        {
                                            "text": "企业 GEO 方案对比",
                                            "category": "solution",
                                            "intents": ["comparison", "recommendation"],
                                            "length_type": "long_tail",
                                            "regions": [],
                                            "base_keyword": None,
                                            "notes": "",
                                            "relevance_score": 90,
                                            "priority": "high",
                                            "ai_reason": "适合方案对比意图",
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    provider = DeepSeekKeywordGenerationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )
    request = replace(
        generation_request(),
        include_long_tail=True,
        categories=("pain_point", "solution", "industry", "goal"),
        intents=("informational", "comparison", "local", "trust"),
        historical_exclusions=(),
    )

    response = provider.generate(request)

    assert response.items[0].business_category == "solution"
    assert response.items[0].search_intents == ("comparison",)
    assert response.provider_metrics["request_count"] == 1


def test_deepseek_keyword_provider_fails_after_exactly_one_repair_request():
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            json={
                "id": f"provider-request-{request_count}",
                "model": "deepseek-chat",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"items": [{"text": "企业 GEO 优化"}]},
                                ensure_ascii=False,
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            },
        )

    provider = DeepSeekKeywordGenerationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )
    with pytest.raises(KeywordGenerationInvalidResponse) as error:
        provider.generate(generation_request())

    assert request_count == 2
    assert set(error.value.diagnostic) == {
        "actual_structure",
        "expected_structure",
        "error_fields",
        "parse_failure_reason",
        "root_cause",
    }


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
