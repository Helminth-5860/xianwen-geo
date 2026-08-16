from django.conf import settings

from .generation_contracts import (
    GeneratedQuestion,
    QuestionGenerationRequest,
    QuestionGenerationResponse,
)
from .generation_exceptions import (
    QuestionGenerationProviderError,
    QuestionGenerationProviderUnavailable,
)


class MockQuestionGenerationProvider:
    key = "mock"
    model_key = "mock-question-generation-v1"
    adapter_version = "1"
    prompt_version = "question-generation-v1"

    def generate(self, request: QuestionGenerationRequest) -> QuestionGenerationResponse:
        scenario = getattr(settings, "QUESTION_GENERATION_MOCK_SCENARIO", "success")
        if scenario in {"timeout", "rate_limit", "temporary"}:
            code = {
                "timeout": "QUESTION_GENERATION_PROVIDER_TIMEOUT",
                "rate_limit": "QUESTION_GENERATION_PROVIDER_RATE_LIMITED",
                "temporary": "QUESTION_GENERATION_PROVIDER_TEMPORARY",
            }[scenario]
            raise QuestionGenerationProviderError(code, permanent=False)
        if scenario == "permanent":
            raise QuestionGenerationProviderError(
                "QUESTION_GENERATION_PROVIDER_REJECTED", permanent=True
            )
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


class UnavailableQuestionGenerationProvider:
    key = "unavailable"
    model_key = "unavailable"
    adapter_version = "1"
    prompt_version = "question-generation-v1"

    def generate(self, request: QuestionGenerationRequest) -> QuestionGenerationResponse:
        raise QuestionGenerationProviderUnavailable


def get_question_generation_provider(provider_key=None):
    key = provider_key or settings.QUESTION_GENERATION_PROVIDER
    if key == "mock":
        return MockQuestionGenerationProvider()
    if key == "unavailable":
        return UnavailableQuestionGenerationProvider()
    raise QuestionGenerationProviderUnavailable


def require_available_question_generation_provider():
    provider = get_question_generation_provider()
    if provider.key == "unavailable":
        raise QuestionGenerationProviderUnavailable
    return provider
