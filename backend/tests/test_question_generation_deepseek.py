import json
from unittest.mock import patch

import httpx
import pytest
from django.test import override_settings

from apps.ai.contracts import AdapterCredential, AIModelCapability
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.models import AICapabilityRuntimeConfig, APICredentialCapabilityBinding
from apps.ai.runtime import AICapabilityRuntimeSnapshot
from apps.questions.generation_contracts import (
    QuestionCatalogInput,
    QuestionGenerationRequest,
    QuestionKeywordInput,
)
from apps.questions.generation_exceptions import (
    QuestionGenerationInvalidResponse,
    QuestionGenerationProviderUnavailable,
)
from apps.questions.generation_providers import (
    DeepSeekQuestionGenerationProvider,
    require_available_question_generation_provider,
)

CATEGORY_ID = "11111111-1111-4111-8111-111111111111"
TAG_ID = "22222222-2222-4222-8222-222222222222"
KEYWORD_ONE_ID = "33333333-3333-4333-8333-333333333333"
KEYWORD_TWO_ID = "44444444-4444-4444-8444-444444444444"


class CredentialResolver:
    def resolve(self, provider_key):
        assert provider_key == "deepseek"
        return AdapterCredential("test-only-question-provider-credential")


def runtime_snapshot(**kwargs):
    assert kwargs == {
        "provider_key": "deepseek",
        "capability": AIModelCapability.QUESTION_GENERATION,
    }
    return AICapabilityRuntimeSnapshot(
        runtime_id="question-runtime-1",
        model_id="model-1",
        provider_key="deepseek",
        model_key="deepseek",
        capability=AIModelCapability.QUESTION_GENERATION,
        provider_model_id="deepseek-chat",
        api_version="",
        timeout_seconds=30,
        max_retries=2,
        retry_base_seconds=30,
        version=1,
    )


def generation_request(*, limit=1):
    keywords = (
        QuestionKeywordInput(
            id=KEYWORD_ONE_ID,
            text="企业 GEO 优化",
            region_text="广州市",
            search_intent="commercial",
            business_category="service",
            search_intents=("recommendation", "local"),
        ),
        QuestionKeywordInput(
            id=KEYWORD_TWO_ID,
            text="AI 搜索优化方案",
            region_text=None,
            search_intent="informational",
            business_category="solution",
            search_intents=("informational",),
        ),
    )
    return QuestionGenerationRequest(
        job_id="question-job-1",
        subject_id="subject-1",
        subject_version_id="subject-version-1",
        distillation_set_id="distillation-1",
        subject_values={
            "official_name": "显问科技",
            "main_business": "GEO 智能分析",
            "contact_person": "不应发送",
            "contact_phone": "13800000000",
        },
        keywords=keywords[:limit],
        categories=(
            QuestionCatalogInput(
                id=CATEGORY_ID,
                key="business_decision",
                name="市场决策",
                version=1,
                guidance="帮助用户比较和选择",
            ),
        ),
        tags=(
            QuestionCatalogInput(
                id=TAG_ID,
                key="trust",
                name="信任",
                version=1,
            ),
        ),
        question_limit=limit,
    )


def provider_response(items, request_number=1):
    return httpx.Response(
        200,
        json={
            "id": f"question-provider-request-{request_number}",
            "model": "deepseek-chat",
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"questions": items}, ensure_ascii=False),
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


def question_row(text, keyword, *, category=CATEGORY_ID):
    return {
        "question": text,
        "category_id": category,
        "tags": ["信任"],
        "keywords": [keyword],
        "priority": "高",
        "type": "自然探索型",
        "include_in_scoring": "true",
        "ai_reason": "与当前主体和关键词直接相关",
    }


def test_deepseek_question_provider_uses_capability_runtime_and_normalizes_finite_aliases():
    captured = []

    def handler(request):
        assert request.headers["Authorization"] == (
            "Bearer test-only-question-provider-credential"
        )
        payload = json.loads(request.content)
        captured.append(json.loads(payload["messages"][1]["content"]))
        assert payload["model"] == "deepseek-chat"
        assert payload["response_format"] == {"type": "json_object"}
        return provider_response(
            [question_row("企业选择 GEO 优化服务时应关注哪些因素？", "企业 GEO 优化")]
        )

    provider = DeepSeekQuestionGenerationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )
    response = provider.generate(generation_request())

    assert captured[0]["task"] == "generate_geo_questions"
    assert captured[0]["target_count"] == 1
    assert captured[0]["subject"] == {
        "official_name": "显问科技",
        "main_business": "GEO 智能分析",
    }
    assert len(response.questions) == 1
    question = response.questions[0]
    assert question.primary_category_id == CATEGORY_ID
    assert question.tag_ids == (TAG_ID,)
    assert question.keyword_ids == (KEYWORD_ONE_ID,)
    assert question.priority == "high"
    assert question.question_type == "natural"
    assert question.participates_in_scoring is True
    assert response.provider_metrics == {
        "provider_model_id": "deepseek-chat",
        "provider_request_id": "question-provider-request-1",
        "total_tokens": 180,
        "request_count": 1,
    }


def test_deepseek_question_provider_keeps_valid_rows_and_repairs_shortfall_once():
    captured = []

    def handler(request):
        payload = json.loads(request.content)
        captured.append(json.loads(payload["messages"][1]["content"]))
        if len(captured) == 1:
            items = [
                question_row("企业 GEO 优化服务如何选择？", "企业 GEO 优化"),
                question_row(
                    "AI 搜索优化方案如何比较？",
                    "AI 搜索优化方案",
                    category="00000000-0000-0000-0000-000000000000",
                ),
            ]
        else:
            items = [
                question_row("不同 AI 搜索优化方案应比较什么？", "AI 搜索优化方案"),
                question_row(
                    "这个结果仍然无效吗？",
                    "AI 搜索优化方案",
                    category="00000000-0000-0000-0000-000000000000",
                ),
            ]
        return provider_response(items, len(captured))

    provider = DeepSeekQuestionGenerationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )
    response = provider.generate(generation_request(limit=2))

    assert [payload["task"] for payload in captured] == [
        "generate_geo_questions",
        "repair_geo_question_json",
    ]
    assert [payload["target_count"] for payload in captured] == [2, 2]
    assert captured[1]["retained_questions"] == ["企业 GEO 优化服务如何选择?"]
    assert [question.text for question in response.questions] == [
        "企业 GEO 优化服务如何选择?",
        "不同 AI 搜索优化方案应比较什么?",
    ]
    assert response.provider_metrics["request_count"] == 2


def test_deepseek_question_provider_fails_after_exactly_one_repair_request():
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        return provider_response([{"text": "缺少必要引用"}], request_count)

    provider = DeepSeekQuestionGenerationProvider(
        credential_resolver=CredentialResolver(),
        transport=httpx.MockTransport(handler),
        runtime_resolver=runtime_snapshot,
    )

    with pytest.raises(QuestionGenerationInvalidResponse):
        provider.generate(generation_request())

    assert request_count == 2


def test_deepseek_question_provider_fails_closed_without_capability_runtime():
    def unavailable_runtime(**kwargs):
        raise AIAdapterError(
            AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
            stable_code="AI_CAPABILITY_RUNTIME_CONFIG_MISSING",
            retryable=False,
        )

    provider = DeepSeekQuestionGenerationProvider(
        credential_resolver=CredentialResolver(),
        runtime_resolver=unavailable_runtime,
    )

    with pytest.raises(QuestionGenerationProviderUnavailable):
        provider.ensure_available()


@override_settings(QUESTION_GENERATION_PROVIDER="deepseek")
def test_require_available_question_provider_executes_runtime_and_credential_preflight():
    with patch.object(
        DeepSeekQuestionGenerationProvider,
        "ensure_available",
        return_value=runtime_snapshot(
            provider_key="deepseek",
            capability=AIModelCapability.QUESTION_GENERATION,
        ),
    ) as ensure_available:
        provider = require_available_question_generation_provider()

    assert isinstance(provider, DeepSeekQuestionGenerationProvider)
    ensure_available.assert_called_once()


@pytest.mark.django_db
def test_deepseek_question_capability_rows_are_seeded_disabled():
    runtime = AICapabilityRuntimeConfig.objects.get(
        model__model_key="deepseek",
        capability="question_generation",
    )
    bindings = APICredentialCapabilityBinding.objects.filter(
        provider__provider_key="deepseek",
        capability="question_generation",
    )

    assert runtime.enabled is False
    assert runtime.provider_model_id == ""
    assert set(bindings.values_list("environment", "enabled")) == {
        ("staging", False),
        ("production", False),
    }
