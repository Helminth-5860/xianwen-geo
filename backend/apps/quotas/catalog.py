from dataclasses import dataclass

MAX_QUOTA_AMOUNT = 2**63 - 1


@dataclass(frozen=True)
class QuotaDefinition:
    key: str
    source_limit_key: str
    unit: str
    scope: str
    reset_type: str
    subject_level: bool
    accounting_mode: str = "consumable"
    minimum: int = 0
    maximum: int = MAX_QUOTA_AMOUNT
    customer_visible: bool = True


QUOTA_CATALOG = (
    # Natural-unit customer quotas used by every newly issued subscription.
    QuotaDefinition(
        "geo_detection_runs", "geo_detection_runs", "run", "subscription", "none", False
    ),
    QuotaDefinition(
        "article_generations", "article_generations", "article", "subscription", "none", False
    ),
    QuotaDefinition(
        "auto_publish_count", "auto_publish_count", "article", "subscription", "none", False
    ),
    QuotaDefinition(
        "image_generations", "image_generations", "image", "subscription", "none", False
    ),
    QuotaDefinition(
        "source_index_scans", "source_index_scans", "run", "subscription", "none", False
    ),
    QuotaDefinition(
        "negative_index_scans", "negative_index_scans", "run", "subscription", "none", False
    ),
    QuotaDefinition("website_audits", "website_audits", "run", "subscription", "none", False),
    QuotaDefinition(
        "website_generations", "website_generations", "run", "subscription", "none", False
    ),
    QuotaDefinition(
        "video_script_generations",
        "video_script_generations",
        "item",
        "subscription",
        "none",
        False,
    ),
    QuotaDefinition(
        "competitor_comparisons", "competitor_comparisons", "run", "subscription", "none", False
    ),
    QuotaDefinition(
        "keyword_generated_items", "keyword_generated_items", "item", "subscription", "none", False
    ),
    QuotaDefinition(
        "question_generated_items",
        "question_generated_items",
        "item",
        "subscription",
        "none",
        False,
    ),
    # Legacy facts remain readable and spendable by historical subscriptions, but
    # are never surfaced as current customer entitlements.
    QuotaDefinition(
        "detection_points",
        "detection_points",
        "point",
        "subscription",
        "none",
        False,
        customer_visible=False,
    ),
    QuotaDefinition(
        "article_credits",
        "article_credits",
        "article",
        "subscription",
        "none",
        False,
        customer_visible=False,
    ),
    QuotaDefinition(
        "image_credits",
        "image_credits",
        "image",
        "subscription",
        "none",
        False,
        customer_visible=False,
    ),
    QuotaDefinition(
        "video_credits",
        "video_credits",
        "second",
        "subscription",
        "none",
        False,
        customer_visible=False,
    ),
    QuotaDefinition(
        "storage_bytes",
        "storage_bytes",
        "byte",
        "account",
        "none",
        False,
        accounting_mode="capacity_absolute",
        customer_visible=False,
    ),
    QuotaDefinition(
        "assistant_messages",
        "assistant_messages_per_cycle",
        "count",
        "account_cycle",
        "monthly",
        False,
        customer_visible=False,
    ),
    QuotaDefinition(
        "keyword_regenerations",
        "keyword_regenerations_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
        customer_visible=False,
    ),
    QuotaDefinition(
        "distillation_regenerations",
        "distillation_regenerations_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
        customer_visible=False,
    ),
    QuotaDefinition(
        "question_bank_regenerations",
        "question_bank_regenerations_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
        customer_visible=False,
    ),
    QuotaDefinition(
        "strategy_regenerations",
        "strategy_regenerations_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
        customer_visible=False,
    ),
    QuotaDefinition(
        "outline_regenerations",
        "outline_regenerations_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
        customer_visible=False,
    ),
    QuotaDefinition(
        "local_ai_edits",
        "local_ai_edits_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
        customer_visible=False,
    ),
    QuotaDefinition(
        "quality_rechecks",
        "quality_rechecks_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
        customer_visible=False,
    ),
)

QUOTA_BY_KEY = {item.key: item for item in QUOTA_CATALOG}
CURRENT_ACCOUNT_DEFINITIONS = tuple(item for item in QUOTA_CATALOG if not item.subject_level)


def quota_definition(key: str) -> QuotaDefinition:
    try:
        return QUOTA_BY_KEY[key]
    except KeyError as exc:
        raise ValueError("未知额度类型。") from exc


def validate_quota_amount(value, *, definition: QuotaDefinition | None = None) -> int:
    if type(value) is not int:
        raise ValueError("额度必须是整数。")
    minimum = definition.minimum if definition else 0
    maximum = definition.maximum if definition else MAX_QUOTA_AMOUNT
    if value < minimum or value > maximum:
        raise ValueError("额度数值超出允许范围。")
    return value


def snapshot_quota_values(snapshot: dict) -> dict[str, int]:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("limits"), dict):
        raise ValueError("订阅权益快照不正确。")
    limits = snapshot["limits"]
    values: dict[str, int] = {}
    for definition in QUOTA_CATALOG:
        # Plan versions are immutable. A historical snapshot legitimately has
        # only the quota keys that existed when it was published; newly added
        # natural-unit quotas must therefore be absent rather than fabricated.
        if definition.source_limit_key not in limits:
            continue
        values[definition.key] = validate_quota_amount(
            limits[definition.source_limit_key], definition=definition
        )
    if not values:
        raise ValueError("订阅权益快照没有可识别的额度配置。")
    return values
