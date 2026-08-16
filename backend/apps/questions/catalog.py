from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinQuestionCategory:
    key: str
    name: str
    description: str
    generation_guidance: str
    sort_order: int


BUILTIN_QUESTION_CATEGORIES = (
    BuiltinQuestionCategory(
        "brand_awareness",
        "品牌认知",
        "了解用户对主体品牌的认知。",
        "生成品牌认知与了解程度相关问题。",
        10,
    ),
    BuiltinQuestionCategory(
        "products_services",
        "产品／服务",
        "了解主体产品或服务。",
        "生成产品功能、服务内容与适配性问题。",
        20,
    ),
    BuiltinQuestionCategory(
        "recommendation_selection",
        "推荐选择",
        "帮助用户比较和选择方案。",
        "生成推荐、选择标准和适合对象相关问题。",
        30,
    ),
    BuiltinQuestionCategory(
        "competitor_comparison",
        "竞品对比",
        "比较主体与替代方案。",
        "生成中立、可验证的竞品比较问题。",
        40,
    ),
    BuiltinQuestionCategory(
        "use_cases", "使用场景", "覆盖典型用户场景。", "生成具体场景、需求和使用方式相关问题。", 50
    ),
    BuiltinQuestionCategory(
        "purchase_decision",
        "购买决策",
        "辅助用户形成购买决策。",
        "生成购买前评估、条件和决策因素问题。",
        60,
    ),
    BuiltinQuestionCategory(
        "regional_services",
        "地域服务",
        "覆盖地域可用性与本地服务。",
        "生成服务地区、门店和本地可用性问题。",
        70,
    ),
    BuiltinQuestionCategory(
        "risk_reputation",
        "风险与口碑",
        "了解风险、评价与口碑。",
        "生成风险、评价、可信度和口碑问题。",
        80,
    ),
    BuiltinQuestionCategory(
        "price_cost", "价格与成本", "了解价格和总体成本。", "生成价格、费用构成和成本比较问题。", 90
    ),
    BuiltinQuestionCategory(
        "after_sales_support",
        "售后与保障",
        "了解售后支持和保障。",
        "生成售后、服务保障和问题处理相关问题。",
        100,
    ),
)
