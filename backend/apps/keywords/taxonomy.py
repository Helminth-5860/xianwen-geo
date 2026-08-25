from __future__ import annotations

from enum import StrEnum


class KeywordCategory(StrEnum):
    ENTITY = "entity"
    INDUSTRY = "industry"
    PRODUCT_CATEGORY = "product_category"
    PRODUCT = "product"
    SERVICE = "service"
    CAPABILITY = "capability"
    GOAL = "goal"
    PAIN_POINT = "pain_point"
    SOLUTION = "solution"
    SCENARIO = "scenario"
    AUDIENCE = "audience"
    COMPETITOR = "competitor"
    TRUST = "trust"
    KNOWLEDGE = "knowledge"


KEYWORD_CATEGORY_LABELS = {
    KeywordCategory.ENTITY: "企业与品牌",
    KeywordCategory.INDUSTRY: "行业与赛道",
    KeywordCategory.PRODUCT_CATEGORY: "产品或服务类别",
    KeywordCategory.PRODUCT: "具体产品",
    KeywordCategory.SERVICE: "具体服务",
    KeywordCategory.CAPABILITY: "能力与功能",
    KeywordCategory.GOAL: "目标与收益",
    KeywordCategory.PAIN_POINT: "问题与痛点",
    KeywordCategory.SOLUTION: "解决方案",
    KeywordCategory.SCENARIO: "使用场景",
    KeywordCategory.AUDIENCE: "目标人群",
    KeywordCategory.COMPETITOR: "竞品与替代",
    KeywordCategory.TRUST: "信任与口碑",
    KeywordCategory.KNOWLEDGE: "知识与教育",
}


class KeywordIntent(StrEnum):
    INFORMATIONAL = "informational"
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    TRANSACTIONAL = "transactional"
    LOCAL = "local"
    NAVIGATIONAL = "navigational"
    TRUST = "trust"
    USAGE = "usage"


KEYWORD_INTENT_LABELS = {
    KeywordIntent.INFORMATIONAL: "信息了解",
    KeywordIntent.RECOMMENDATION: "推荐评估",
    KeywordIntent.COMPARISON: "对比选择",
    KeywordIntent.TRANSACTIONAL: "交易转化",
    KeywordIntent.LOCAL: "地域本地",
    KeywordIntent.NAVIGATIONAL: "导航联系",
    KeywordIntent.TRUST: "信任口碑",
    KeywordIntent.USAGE: "使用服务",
}


KEYWORD_CATEGORY_VALUES = frozenset(value.value for value in KeywordCategory)
KEYWORD_INTENT_VALUES = frozenset(value.value for value in KeywordIntent)


# Only finite, documented aliases are accepted. Unknown values remain invalid.
CATEGORY_ALIASES = {
    **{value: value for value in KEYWORD_CATEGORY_VALUES},
    **{label: key.value for key, label in KEYWORD_CATEGORY_LABELS.items()},
    "brand": KeywordCategory.ENTITY.value,
    "brand_entity": KeywordCategory.ENTITY.value,
    "business": KeywordCategory.ENTITY.value,
    "product_service_category": KeywordCategory.PRODUCT_CATEGORY.value,
    "feature": KeywordCategory.CAPABILITY.value,
    "need": KeywordCategory.GOAL.value,
    "problem": KeywordCategory.PAIN_POINT.value,
    "pain": KeywordCategory.PAIN_POINT.value,
    "use_case": KeywordCategory.SCENARIO.value,
    "persona": KeywordCategory.AUDIENCE.value,
    "competition": KeywordCategory.COMPETITOR.value,
    "credibility": KeywordCategory.TRUST.value,
    "education": KeywordCategory.KNOWLEDGE.value,
}

INTENT_ALIASES = {
    **{value: value for value in KEYWORD_INTENT_VALUES},
    **{label: key.value for key, label in KEYWORD_INTENT_LABELS.items()},
    "information": KeywordIntent.INFORMATIONAL.value,
    "education": KeywordIntent.INFORMATIONAL.value,
    "commercial": KeywordIntent.RECOMMENDATION.value,
    "commercial_research": KeywordIntent.RECOMMENDATION.value,
    "recommend": KeywordIntent.RECOMMENDATION.value,
    "evaluate": KeywordIntent.RECOMMENDATION.value,
    "compare": KeywordIntent.COMPARISON.value,
    "transaction": KeywordIntent.TRANSACTIONAL.value,
    "purchase": KeywordIntent.TRANSACTIONAL.value,
    "regional": KeywordIntent.LOCAL.value,
    "navigation": KeywordIntent.NAVIGATIONAL.value,
    "contact": KeywordIntent.NAVIGATIONAL.value,
    "reputation": KeywordIntent.TRUST.value,
    "after_sales": KeywordIntent.USAGE.value,
    "service_usage": KeywordIntent.USAGE.value,
}


def normalize_category(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("category_type")
    normalized = value.strip().lower()
    result = CATEGORY_ALIASES.get(normalized) or CATEGORY_ALIASES.get(value.strip())
    if result is None:
        raise ValueError("category_value")
    return result


def normalize_intents(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("intents_shape")
    result: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise ValueError("intent_type")
        normalized = raw.strip().lower()
        intent = INTENT_ALIASES.get(normalized) or INTENT_ALIASES.get(raw.strip())
        if intent is None:
            raise ValueError("intent_value")
        if intent not in result:
            result.append(intent)
    return tuple(result)
