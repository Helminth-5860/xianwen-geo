from dataclasses import replace

from django.conf import settings

from apps.ai.contracts import (
    AIAdapterDescriptor,
    AIAdapterRequest,
    AIAdapterResponse,
    AIModelCapability,
    AIModelIdentity,
)
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory, domain_provider_error_code
from apps.ai.mock import DeterministicMockAIAdapter
from apps.ai.registry import model_registry

from .generation_contracts import (
    GeneratedQuestion,
    QuestionGenerationRequest,
    QuestionGenerationResponse,
)
from .generation_exceptions import (
    QuestionGenerationProviderError,
    QuestionGenerationProviderUnavailable,
)


class MockQuestionGenerationProvider(
    DeterministicMockAIAdapter[QuestionGenerationRequest, QuestionGenerationResponse]
):
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(
            provider_key="mock",
            model_key="mock-question-generation-v1",
        ),
        capabilities=frozenset({AIModelCapability.QUESTION_GENERATION}),
        adapter_version="1",
        prompt_version="question-generation-v1",
        is_mock=True,
    )
    key = descriptor.identity.provider_key
    model_key = descriptor.identity.model_key
    adapter_version = descriptor.adapter_version
    prompt_version = descriptor.prompt_version

    def _scenario(self) -> str:
        return getattr(settings, "QUESTION_GENERATION_MOCK_SCENARIO", "success")

    def _build_output(
        self,
        request: QuestionGenerationRequest,
        scenario: str,
    ) -> QuestionGenerationResponse:
        count = min(request.question_limit, max(1, len(request.keywords)))
        category = request.categories[0]
        questions = []
        for index in range(count):
            keyword = request.keywords[index % len(request.keywords)]
            tag_ids = (request.tags[index % len(request.tags)].id,) if request.tags else ()
            questions.append(
                GeneratedQuestion(
                    text=f"用户在选择{keyword.text}时最关心哪些因素？",
                    primary_category_id=category.id,
                    tag_ids=tag_ids,
                    keyword_ids=(keyword.id,),
                    priority=("high", "medium", "low")[index % 3],
                    question_type="natural" if index % 2 == 0 else "brand_directed",
                    participates_in_scoring=True,
                    reason=f"Mock question reason {index + 1}",
                )
            )
        if scenario == "invalid_response" and questions:
            first = questions[0]
            questions[0] = GeneratedQuestion(
                text=first.text,
                primary_category_id="00000000-0000-0000-0000-000000000000",
                tag_ids=first.tag_ids,
                keyword_ids=first.keyword_ids,
                priority=first.priority,
                question_type=first.question_type,
                participates_in_scoring=True,
                reason=first.reason,
            )
        return QuestionGenerationResponse(
            questions=tuple(questions),
            model_key=self.model_key,
            provider_metrics={"mock": True, "item_count": len(questions)},
        )

    def generate(self, request: QuestionGenerationRequest) -> QuestionGenerationResponse:
        normalized = self.normalized_request(
            request,
            request_id=request.job_id,
            timeout_seconds=settings.QUESTION_GENERATION_PROVIDER_TIMEOUT_SECONDS,
        )
        try:
            response = self.invoke(normalized)
        except AIAdapterError as exc:
            raise QuestionGenerationProviderError(
                domain_provider_error_code(exc, "QUESTION_GENERATION_PROVIDER"),
                permanent=not exc.retryable,
            ) from None
        return replace(
            response.output,
            provider_metrics=dict(response.sanitized_provider_metadata),
        )


class UnavailableQuestionGenerationProvider:
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="unavailable", model_key="unavailable"),
        capabilities=frozenset({AIModelCapability.QUESTION_GENERATION}),
        adapter_version="1",
        prompt_version="question-generation-v1",
        is_available=False,
    )
    key = descriptor.identity.provider_key
    model_key = descriptor.identity.model_key
    adapter_version = descriptor.adapter_version
    prompt_version = descriptor.prompt_version

    def invoke(
        self,
        request: AIAdapterRequest[QuestionGenerationRequest],
    ) -> AIAdapterResponse[QuestionGenerationResponse]:
        raise AIAdapterError(AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE, retryable=False)

    def generate(self, request: QuestionGenerationRequest) -> QuestionGenerationResponse:
        raise QuestionGenerationProviderUnavailable


model_registry.register(MockQuestionGenerationProvider.descriptor, MockQuestionGenerationProvider)
model_registry.register(
    UnavailableQuestionGenerationProvider.descriptor,
    UnavailableQuestionGenerationProvider,
)


def get_question_generation_provider(provider_key=None):
    key = provider_key or settings.QUESTION_GENERATION_PROVIDER
    try:
        return model_registry.resolve_provider(
            provider_key=key,
            capability=AIModelCapability.QUESTION_GENERATION,
        )
    except AIAdapterError:
        raise QuestionGenerationProviderUnavailable from None


def require_available_question_generation_provider():
    provider = get_question_generation_provider()
    if not provider.descriptor.is_available:
        raise QuestionGenerationProviderUnavailable
    return provider
