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
    minimum: int = 0
    maximum: int = MAX_QUOTA_AMOUNT


QUOTA_CATALOG = (
    QuotaDefinition("detection_points", "detection_points", "point", "subscription", "none", False),
    QuotaDefinition("article_credits", "article_credits", "article", "subscription", "none", False),
    QuotaDefinition("image_credits", "image_credits", "image", "subscription", "none", False),
    QuotaDefinition("storage_bytes", "storage_bytes", "byte", "account", "none", False),
    QuotaDefinition(
        "assistant_messages",
        "assistant_messages_per_cycle",
        "count",
        "account_cycle",
        "monthly",
        False,
    ),
    QuotaDefinition(
        "keyword_regenerations",
        "keyword_regenerations_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
    ),
    QuotaDefinition(
        "distillation_regenerations",
        "distillation_regenerations_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
    ),
    QuotaDefinition(
        "question_bank_regenerations",
        "question_bank_regenerations_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
    ),
    QuotaDefinition(
        "strategy_regenerations",
        "strategy_regenerations_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
    ),
    QuotaDefinition(
        "outline_regenerations",
        "outline_regenerations_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
    ),
    QuotaDefinition(
        "local_ai_edits",
        "local_ai_edits_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
    ),
    QuotaDefinition(
        "quality_rechecks",
        "quality_rechecks_per_cycle",
        "count",
        "subject_cycle",
        "monthly",
        True,
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
        if definition.source_limit_key not in limits:
            raise ValueError("订阅权益快照缺少额度定义。")
        values[definition.key] = validate_quota_amount(
            limits[definition.source_limit_key], definition=definition
        )
    return values
