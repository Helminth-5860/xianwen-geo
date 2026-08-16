import unicodedata
import uuid
from dataclasses import dataclass

from .generation_exceptions import QuestionBankValuesInvalid, QuestionGenerationInvalidResponse


@dataclass(frozen=True)
class NormalizedQuestion:
    text: str
    matching_text: str
    primary_category_id: uuid.UUID
    tag_ids: tuple[uuid.UUID, ...]
    keyword_ids: tuple[uuid.UUID, ...]
    priority: str
    question_type: str
    participates_in_scoring: bool
    reason: str

    def payload(self):
        return {
            "text": self.text,
            "primary_category_id": str(self.primary_category_id),
            "tag_ids": [str(value) for value in self.tag_ids],
            "keyword_ids": [str(value) for value in self.keyword_ids],
            "priority": self.priority,
            "question_type": self.question_type,
            "participates_in_scoring": self.participates_in_scoring,
            "reason": self.reason,
        }


def normalize_question_text(value, *, required=True, maximum=1000):
    if not isinstance(value, str):
        raise QuestionBankValuesInvalid
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise QuestionBankValuesInvalid
    if required and not value:
        raise QuestionBankValuesInvalid
    if len(value) > maximum:
        raise QuestionBankValuesInvalid
    return value, value.casefold()


def _ids(values, allowed):
    if not isinstance(values, (list, tuple)):
        raise QuestionGenerationInvalidResponse
    try:
        result = tuple(uuid.UUID(str(value)) for value in values)
    except (TypeError, ValueError) as exc:
        raise QuestionGenerationInvalidResponse from exc
    if len(result) != len(set(result)) or not set(result).issubset(allowed):
        raise QuestionGenerationInvalidResponse
    return result


def validate_generated_questions(*, response, category_ids, tag_ids, keyword_ids, limit):
    if not response.questions or len(response.questions) > limit:
        raise QuestionGenerationInvalidResponse
    normalized = []
    seen = set()
    for item in response.questions:
        try:
            text, matching = normalize_question_text(item.text)
            category_id = uuid.UUID(str(item.primary_category_id))
            reason, _ = normalize_question_text(item.reason, required=False)
        except (QuestionBankValuesInvalid, TypeError, ValueError) as exc:
            raise QuestionGenerationInvalidResponse from exc
        if matching in seen or category_id not in category_ids:
            raise QuestionGenerationInvalidResponse
        if item.priority not in {"high", "medium", "low"}:
            raise QuestionGenerationInvalidResponse
        if item.question_type not in {"natural", "brand_directed"}:
            raise QuestionGenerationInvalidResponse
        if type(item.participates_in_scoring) is not bool:
            raise QuestionGenerationInvalidResponse
        normalized.append(
            NormalizedQuestion(
                text=text,
                matching_text=matching,
                primary_category_id=category_id,
                tag_ids=_ids(item.tag_ids, tag_ids),
                keyword_ids=_ids(item.keyword_ids, keyword_ids),
                priority=item.priority,
                question_type=item.question_type,
                participates_in_scoring=item.participates_in_scoring,
                reason=reason,
            )
        )
        seen.add(matching)
    return normalized


def validate_draft_items(*, items, category_ids, tag_ids, keyword_ids, limit):
    if not isinstance(items, list) or not items or len(items) > limit:
        raise QuestionBankValuesInvalid
    normalized = []
    seen = set()
    for item in items:
        try:
            text, matching = normalize_question_text(item["text"])
            category_id = uuid.UUID(str(item["primary_category_id"]))
            tags = tuple(uuid.UUID(str(value)) for value in item.get("tag_ids", []))
            keywords = tuple(uuid.UUID(str(value)) for value in item.get("keyword_ids", []))
            reason, _ = normalize_question_text(item.get("ai_reason", ""), required=False)
        except (KeyError, TypeError, ValueError, QuestionBankValuesInvalid) as exc:
            raise QuestionBankValuesInvalid from exc
        if matching in seen or category_id not in category_ids:
            raise QuestionBankValuesInvalid
        if len(tags) != len(set(tags)) or not set(tags).issubset(tag_ids):
            raise QuestionBankValuesInvalid
        if len(keywords) != len(set(keywords)) or not set(keywords).issubset(keyword_ids):
            raise QuestionBankValuesInvalid
        if item.get("priority") not in {"high", "medium", "low"}:
            raise QuestionBankValuesInvalid
        if item.get("question_type") not in {"natural", "brand_directed"}:
            raise QuestionBankValuesInvalid
        if type(item.get("participates_in_scoring")) is not bool:
            raise QuestionBankValuesInvalid
        normalized.append(
            NormalizedQuestion(
                text=text,
                matching_text=matching,
                primary_category_id=category_id,
                tag_ids=tags,
                keyword_ids=keywords,
                priority=item["priority"],
                question_type=item["question_type"],
                participates_in_scoring=item["participates_in_scoring"],
                reason=reason,
            )
        )
        seen.add(matching)
    return normalized
