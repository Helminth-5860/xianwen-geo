import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from .catalog import CATALOG_VERSION, MODEL_KEYS, MODEL_NAMES
from .models import Plan, PlanLimit, PlanLimitDefinition, PlanModelPermission, PlanVersion

CODE_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
MAX_BIGINT = 9_223_372_036_854_775_807


class PlanDomainError(Exception):
    code = "PLAN_STATE_CONFLICT"


class PlanStateConflict(PlanDomainError):
    code = "PLAN_STATE_CONFLICT"


class PlanVersionStateConflict(PlanDomainError):
    code = "PLAN_VERSION_STATE_CONFLICT"


class PlanVersionConflict(PlanDomainError):
    code = "PLAN_VERSION_CONFLICT"


class PlanDraftAlreadyExists(PlanDomainError):
    code = "PLAN_DRAFT_ALREADY_EXISTS"


class PlanLimitInvalid(PlanDomainError):
    code = "PLAN_LIMIT_INVALID"


class PlanModelPermissionInvalid(PlanDomainError):
    code = "PLAN_MODEL_PERMISSION_INVALID"


class PlanPublishValidationFailed(PlanDomainError):
    code = "PLAN_PUBLISH_VALIDATION_FAILED"


class PlanImmutable(PlanDomainError):
    code = "PLAN_IMMUTABLE"


def normalize_plan_code(value: str) -> str:
    normalized = value.strip().lower()
    if not CODE_RE.fullmatch(normalized):
        raise PlanLimitInvalid("套餐代码格式不正确。")
    return normalized


def normalize_display_price(mode: str, raw_price: Any) -> Decimal | None:
    if mode == Plan.PriceDisplayMode.CONTACT:
        if raw_price not in (None, ""):
            raise PlanLimitInvalid("联系开通模式不能设置展示价格。")
        return None
    if mode != Plan.PriceDisplayMode.FIXED:
        raise PlanLimitInvalid("展示价格模式不正确。")
    if isinstance(raw_price, float) or isinstance(raw_price, bool) or raw_price in (None, ""):
        raise PlanLimitInvalid("固定价格模式必须提供 Decimal 展示价格。")
    try:
        price = Decimal(str(raw_price))
    except (InvalidOperation, ValueError) as exc:
        raise PlanLimitInvalid("展示价格格式不正确。") from exc
    exponent = price.as_tuple().exponent
    if not price.is_finite() or price < 0 or not isinstance(exponent, int) or exponent < -2:
        raise PlanLimitInvalid("展示价格必须非负且最多两位小数。")
    if price >= Decimal("10000000000"):
        raise PlanLimitInvalid("展示价格超出允许范围。")
    return price.quantize(Decimal("0.01"))


def _locked_plan(plan_id) -> Plan:
    try:
        return Plan.objects.select_for_update().get(pk=plan_id)
    except Plan.DoesNotExist as exc:
        from rest_framework.exceptions import NotFound

        raise NotFound from exc


def _locked_version(version_id) -> PlanVersion:
    try:
        return PlanVersion.objects.select_for_update().get(pk=version_id)
    except PlanVersion.DoesNotExist as exc:
        from rest_framework.exceptions import NotFound

        raise NotFound from exc


def _locked_plan_and_version(version_id) -> tuple[Plan, PlanVersion]:
    try:
        plan_id = PlanVersion.objects.only("plan_id").get(pk=version_id).plan_id
    except PlanVersion.DoesNotExist as exc:
        from rest_framework.exceptions import NotFound

        raise NotFound from exc
    plan = _locked_plan(plan_id)
    version = _locked_version(version_id)
    if version.plan_id != plan.pk:
        raise PlanStateConflict("套餐版本所属套餐发生变化。")
    return plan, version


def _ensure_expected(actual: int, expected: int, *, plan: bool = False) -> None:
    if actual != expected:
        if plan:
            raise PlanVersionConflict("套餐资料版本已变化。")
        raise PlanVersionConflict("套餐草稿版本已变化。")


def assert_pointer_consistency(plan: Plan) -> None:
    current = plan.current_published_version
    if plan.status == Plan.Status.DRAFT and current is not None:
        raise PlanStateConflict("草稿套餐不能指向已发布版本。")
    if plan.status == Plan.Status.PUBLISHED and (
        current is None
        or current.plan_id != plan.pk
        or current.status != PlanVersion.Status.PUBLISHED
    ):
        raise PlanStateConflict("已上架套餐必须指向自身的已发布版本。")
    if (
        plan.status == Plan.Status.OFFLINE
        and current is not None
        and (current.plan_id != plan.pk or current.status != PlanVersion.Status.PUBLISHED)
    ):
        raise PlanStateConflict("下架套餐的当前版本指针无效。")
    if plan.status == Plan.Status.ARCHIVED and current is not None:
        raise PlanStateConflict("归档套餐不能保留当前版本指针。")


@transaction.atomic
def create_plan(*, plan_id, actor, data: dict[str, Any]) -> Plan:
    code = normalize_plan_code(data["code"])
    price = normalize_display_price(data["price_display_mode"], data.get("display_price"))
    try:
        return Plan.objects.create(
            id=plan_id,
            code=code,
            name=data["name"].strip(),
            description=data.get("description", "").strip(),
            price_display_mode=data["price_display_mode"],
            display_price=price,
            display_currency="CNY",
            is_trial=data.get("is_trial", False),
            is_recommended=data.get("is_recommended", False),
            sort_order=data.get("sort_order", 0),
            created_by=actor,
            updated_by=actor,
        )
    except IntegrityError as exc:
        raise PlanVersionConflict("套餐代码已存在。") from exc


@transaction.atomic
def update_plan(*, plan_id, actor, expected_version: int, data: dict[str, Any]) -> Plan:
    plan = _locked_plan(plan_id)
    _ensure_expected(plan.version, expected_version, plan=True)
    if plan.status == Plan.Status.ARCHIVED:
        raise PlanStateConflict("归档套餐不可修改。")
    if "code" in data:
        code = normalize_plan_code(data["code"])
        if plan.status != Plan.Status.DRAFT and code != plan.code:
            raise PlanImmutable("套餐首次发布后代码不可修改。")
        plan.code = code
    mode = data.get("price_display_mode", plan.price_display_mode)
    raw_price = data.get("display_price", plan.display_price)
    plan.price_display_mode = mode
    plan.display_price = normalize_display_price(mode, raw_price)
    for field in ("name", "description", "is_trial", "is_recommended", "sort_order"):
        if field in data:
            value = data[field]
            if isinstance(value, str):
                value = value.strip()
            setattr(plan, field, value)
    plan.display_currency = "CNY"
    plan.updated_by = actor
    plan.version += 1
    try:
        plan.save()
    except IntegrityError as exc:
        raise PlanVersionConflict("套餐代码已存在或资料冲突。") from exc
    return plan


def _definition_rows() -> dict[str, PlanLimitDefinition]:
    return {
        item.key: item for item in PlanLimitDefinition.objects.filter(storage_kind="plan_limit")
    }


def _validate_json_value(definition: PlanLimitDefinition, value: Any) -> Any:
    def safe(item: Any) -> Any:
        if item is None or isinstance(item, (str, bool)):
            return item
        if type(item) is int:
            if not -MAX_BIGINT <= item <= MAX_BIGINT:
                raise PlanLimitInvalid(f"{definition.key} 超出 bigint 范围。")
            return item
        if isinstance(item, float):
            raise PlanLimitInvalid(f"{definition.key} 不允许浮点数。")
        if isinstance(item, list):
            return [safe(child) for child in item]
        if isinstance(item, dict):
            return {str(key): safe(child) for key, child in item.items()}
        raise PlanLimitInvalid(f"{definition.key} JSON 值不安全。")

    value = safe(value)
    kind = definition.json_schema.get("kind")
    if kind == "nullable_non_negative_integer":
        maximum = int(definition.json_schema["maximum"])
        if value is not None and (type(value) is not int or not 0 <= value <= maximum):
            raise PlanLimitInvalid(f"{definition.key} 必须为非负整数或 null。")
    elif kind == "quota_expiry_policy":
        allowed_keys = {
            "detection_points",
            "article_credits",
            "image_credits",
            "video_credits",
            "storage_bytes",
        }
        allowed_values = set(definition.json_schema.get("allowed_values", []))
        if not isinstance(value, dict) or not set(value).issubset(allowed_keys):
            raise PlanLimitInvalid(f"{definition.key} 包含未知额度类型。")
        if any(item not in allowed_values for item in value.values()):
            raise PlanLimitInvalid(f"{definition.key} 包含未知到期策略。")
    elif definition.json_schema:
        raise PlanLimitInvalid(f"{definition.key} 使用了未知 JSON Schema。")
    return value


def validate_limit_value(definition: PlanLimitDefinition, value: Any) -> Any:
    if definition.status != PlanLimitDefinition.Status.ACTIVE:
        raise PlanLimitInvalid(f"限制键已停用：{definition.key}")
    if definition.storage_kind != PlanLimitDefinition.StorageKind.PLAN_LIMIT:
        raise PlanLimitInvalid(f"限制键不存储在 PlanLimit：{definition.key}")
    if definition.value_type == PlanLimitDefinition.ValueType.INTEGER:
        if type(value) is not int:
            raise PlanLimitInvalid(f"{definition.key} 必须为整数。")
        if not -MAX_BIGINT <= value <= MAX_BIGINT or value < 0:
            raise PlanLimitInvalid(f"{definition.key} 必须为非负 bigint。")
        if definition.minimum is not None and value < definition.minimum:
            raise PlanLimitInvalid(f"{definition.key} 低于最小值。")
        if definition.maximum is not None and value > definition.maximum:
            raise PlanLimitInvalid(f"{definition.key} 高于最大值。")
        return value
    if definition.value_type == PlanLimitDefinition.ValueType.BOOLEAN:
        if type(value) is not bool:
            raise PlanLimitInvalid(f"{definition.key} 必须为布尔值。")
        return value
    if definition.value_type in {
        PlanLimitDefinition.ValueType.TEXT,
        PlanLimitDefinition.ValueType.ENUM,
    }:
        if not isinstance(value, str):
            raise PlanLimitInvalid(f"{definition.key} 必须为字符串。")
        if definition.value_type == PlanLimitDefinition.ValueType.ENUM and value not in set(
            definition.enum_values
        ):
            raise PlanLimitInvalid(f"{definition.key} 枚举值不正确。")
        return value
    if definition.value_type == PlanLimitDefinition.ValueType.JSON:
        return _validate_json_value(definition, value)
    raise PlanLimitInvalid(f"{definition.key} 类型不受支持。")


def _limit_row(version: PlanVersion, definition: PlanLimitDefinition, value: Any) -> PlanLimit:
    value = validate_limit_value(definition, value)
    fields: dict[str, Any] = {
        "integer_value": None,
        "boolean_value": None,
        "text_value": None,
        "json_value": None,
    }
    if definition.value_type == "integer":
        fields["integer_value"] = value
    elif definition.value_type == "boolean":
        fields["boolean_value"] = value
    elif definition.value_type in {"text", "enum"}:
        fields["text_value"] = value
    elif value is None:
        # Preserve JSON null without using SQL NULL, so the typed-column constraint remains exact.
        fields["json_value"] = {"value": None}
    else:
        fields["json_value"] = value
    return PlanLimit(
        plan_version=version,
        limit_definition=definition,
        limit_key=definition.key,
        value_type=definition.value_type,
        **fields,
    )


def _build_limit_rows(
    version: PlanVersion,
    items: list[dict[str, Any]] | None,
    *,
    use_defaults: bool,
) -> list[PlanLimit]:
    definitions = _definition_rows()
    values: dict[str, Any] = {}
    if items is not None:
        for item in items:
            key = item["key"]
            if key in values:
                raise PlanLimitInvalid(f"限制键重复：{key}")
            values[key] = item["value"]
    unknown = set(values) - set(definitions)
    if unknown:
        raise PlanLimitInvalid(f"未知限制键：{sorted(unknown)[0]}")
    rows = []
    for key, definition in definitions.items():
        if definition.status != PlanLimitDefinition.Status.ACTIVE:
            if key in values:
                raise PlanLimitInvalid(f"限制键已停用：{key}")
            continue
        if key in values:
            value = values[key]
        elif use_defaults:
            value = definition.default_value
        elif definition.required:
            raise PlanLimitInvalid(f"缺少必填限制键：{key}")
        else:
            continue
        rows.append(_limit_row(version, definition, value))
    return rows


def _validate_models(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        raise PlanModelPermissionInvalid("至少授权一个模型。")
    seen_keys: set[str] = set()
    seen_orders: set[int] = set()
    normalized = []
    for item in items:
        key = item["model_key"]
        order = item["sort_order"]
        selected = item.get("selected_by_default", False)
        if key not in MODEL_KEYS:
            raise PlanModelPermissionInvalid(f"未知模型：{key}")
        if key in seen_keys or order in seen_orders:
            raise PlanModelPermissionInvalid("模型或排序重复。")
        if type(order) is not int or order < 0:
            raise PlanModelPermissionInvalid("模型排序必须为非负整数。")
        if type(selected) is not bool:
            raise PlanModelPermissionInvalid("默认选择必须为布尔值。")
        seen_keys.add(key)
        seen_orders.add(order)
        normalized.append(
            {
                "model_key": key,
                "sort_order": order,
                "selected_by_default": selected,
            }
        )
    if not any(item["selected_by_default"] for item in normalized):
        raise PlanModelPermissionInvalid("至少默认选择一个模型。")
    return sorted(normalized, key=lambda item: (item["sort_order"], item["model_key"]))


def _create_models(version: PlanVersion, items: list[dict[str, Any]]) -> None:
    normalized = _validate_models(items)
    PlanModelPermission.objects.bulk_create(
        [PlanModelPermission(plan_version=version, **item) for item in normalized]
    )


def _clone_entitlements(source: PlanVersion, target: PlanVersion) -> None:
    source_limits = list(source.limits.select_related("limit_definition").order_by("limit_key"))
    source_limits = [
        item
        for item in source_limits
        if item.limit_definition.status == PlanLimitDefinition.Status.ACTIVE
    ]
    rows = [
        PlanLimit(
            plan_version=target,
            limit_definition=item.limit_definition,
            limit_key=item.limit_key,
            value_type=item.value_type,
            integer_value=item.integer_value,
            boolean_value=item.boolean_value,
            text_value=item.text_value,
            json_value=item.json_value,
        )
        for item in source_limits
    ]
    present = {item.limit_key for item in source_limits}
    # Historical published versions remain immutable. A new draft uses the
    # current catalog and receives defaults for entitlements introduced later.
    for definition in _definition_rows().values():
        if definition.status == PlanLimitDefinition.Status.ACTIVE and definition.key not in present:
            rows.append(_limit_row(target, definition, definition.default_value))
    PlanLimit.objects.bulk_create(rows)
    source_models = source.model_permissions.order_by("sort_order", "model_key")
    PlanModelPermission.objects.bulk_create(
        [
            PlanModelPermission(
                plan_version=target,
                model_key=item.model_key,
                sort_order=item.sort_order,
                selected_by_default=item.selected_by_default,
            )
            for item in source_models
        ]
    )


@transaction.atomic
def create_plan_version(
    *,
    plan_id,
    actor,
    expected_plan_version: int,
    source_version_id=None,
) -> PlanVersion:
    plan = _locked_plan(plan_id)
    _ensure_expected(plan.version, expected_plan_version, plan=True)
    if plan.status == Plan.Status.ARCHIVED:
        raise PlanStateConflict("归档套餐不能创建新版本。")
    if PlanVersion.objects.filter(plan=plan, status=PlanVersion.Status.DRAFT).exists():
        raise PlanDraftAlreadyExists("套餐已有草稿版本。")
    version_no = (
        PlanVersion.objects.filter(plan=plan).aggregate(value=Max("version_no"))["value"] or 0
    ) + 1
    source = None
    if source_version_id:
        source = (
            PlanVersion.objects.select_for_update()
            .filter(
                pk=source_version_id,
                plan=plan,
                status__in=(PlanVersion.Status.PUBLISHED, PlanVersion.Status.RETIRED),
            )
            .first()
        )
        if source is None:
            raise PlanVersionStateConflict("来源版本不存在或不可复制。")
    elif plan.current_published_version_id:
        source = PlanVersion.objects.select_for_update().get(pk=plan.current_published_version_id)
    valid_days = 365
    queue_priority = source.queue_priority if source else 100
    try:
        version = PlanVersion.objects.create(
            plan=plan,
            version_no=version_no,
            valid_days=valid_days,
            queue_priority=queue_priority,
        )
    except IntegrityError as exc:
        raise PlanDraftAlreadyExists("并发创建套餐版本冲突。") from exc
    if source:
        _clone_entitlements(source, version)
    else:
        PlanLimit.objects.bulk_create(_build_limit_rows(version, None, use_defaults=True))
        _create_models(
            version,
            [
                {
                    "model_key": key,
                    "sort_order": index,
                    "selected_by_default": True,
                }
                for index, key in enumerate(MODEL_KEYS)
            ],
        )
    plan.updated_by = actor
    plan.version += 1
    plan.save(update_fields=["updated_by", "version", "updated_at"])
    return version


@transaction.atomic
def update_plan_version(
    *,
    version_id,
    actor,
    expected_version: int,
    valid_days: int,
    queue_priority: int,
    limits: list[dict[str, Any]],
    model_permissions: list[dict[str, Any]],
) -> PlanVersion:
    plan, version = _locked_plan_and_version(version_id)
    _ensure_expected(version.version, expected_version)
    if plan.status == Plan.Status.ARCHIVED or version.status != PlanVersion.Status.DRAFT:
        raise PlanImmutable("仅草稿版本可修改。")
    if type(valid_days) is not int or not 1 <= valid_days <= 3650:
        raise PlanLimitInvalid("有效天数必须在 1 至 3650 之间。")
    if type(queue_priority) is not int or not 0 <= queue_priority <= 1000:
        raise PlanLimitInvalid("队列优先级必须在 0 至 1000 之间。")
    rows = _build_limit_rows(version, limits, use_defaults=False)
    models = _validate_models(model_permissions)
    PlanLimit.objects.filter(plan_version=version).delete()
    PlanModelPermission.objects.filter(plan_version=version).delete()
    PlanLimit.objects.bulk_create(rows)
    PlanModelPermission.objects.bulk_create(
        [PlanModelPermission(plan_version=version, **item) for item in models]
    )
    version.valid_days = valid_days
    version.queue_priority = queue_priority
    version.version += 1
    version.save(update_fields=["valid_days", "queue_priority", "version", "updated_at"])
    plan.updated_by = actor
    plan.version += 1
    plan.save(update_fields=["updated_by", "version", "updated_at"])
    return version


def _limit_value(item: PlanLimit) -> Any:
    if item.value_type == "integer":
        return item.integer_value
    if item.value_type == "boolean":
        return item.boolean_value
    if item.value_type in {"text", "enum"}:
        return item.text_value
    if item.json_value == {"value": None} and item.limit_key in {
        "business_record_retention_days",
        "document_retention_days_after_expiry",
    }:
        return None
    return item.json_value


def _formal_composite_capability(version: PlanVersion) -> tuple[bool, list[str]]:
    values = {item.limit_key: _limit_value(item) for item in version.limits.all()}
    models = list(version.model_permissions.all())
    defaults = sum(1 for item in models if item.selected_by_default)
    reasons = []
    if len(models) < 6:
        reasons.append("授权模型少于 6 个")
    if values.get("max_models_per_detection", 0) < 6:
        reasons.append("单次模型上限少于 6 个")
    if values.get("allow_user_model_selection") is False and defaults < 6:
        reasons.append("固定默认模型少于 6 个")
    return not reasons, reasons


def validate_publishable(version: PlanVersion, *, confirm_informal_composite: bool) -> dict:
    definitions = _definition_rows()
    rows = list(version.limits.select_related("limit_definition").all())
    keys = {item.limit_key for item in rows}
    required = {
        key
        for key, definition in definitions.items()
        if definition.required and definition.status == PlanLimitDefinition.Status.ACTIVE
    }
    if keys != required | {
        key
        for key, definition in definitions.items()
        if not definition.required
        and definition.status == PlanLimitDefinition.Status.ACTIVE
        and key in keys
    }:
        missing = sorted(required - keys)
        raise PlanPublishValidationFailed(
            f"套餐限制键不完整：{missing[0] if missing else '包含未知键'}"
        )
    for item in rows:
        definition = item.limit_definition
        if item.limit_key != definition.key or item.value_type != definition.value_type:
            raise PlanLimitInvalid("限制键快照与目录不一致。")
        validate_limit_value(definition, _limit_value(item))
    models = _validate_models(
        [
            {
                "model_key": item.model_key,
                "sort_order": item.sort_order,
                "selected_by_default": item.selected_by_default,
            }
            for item in version.model_permissions.all()
        ]
    )
    values = {item.limit_key: _limit_value(item) for item in rows}
    max_models = values["max_models_per_detection"]
    defaults = sum(1 for item in models if item["selected_by_default"])
    if max_models > len(models):
        raise PlanModelPermissionInvalid("单次模型上限不能超过授权模型数。")
    if defaults > max_models:
        raise PlanModelPermissionInvalid("默认模型数不能超过单次模型上限。")
    formal, reasons = _formal_composite_capability(version)
    if not formal and not confirm_informal_composite:
        raise PlanPublishValidationFailed("该套餐无法形成正式综合分，必须显式确认。")
    return {"supports_formal_composite": formal, "informal_reasons": reasons}


def build_effective_config(version: PlanVersion, generated_at) -> tuple[dict, str]:
    limits = {item.limit_key: _limit_value(item) for item in version.limits.order_by("limit_key")}
    models = [
        {
            "model_key": item.model_key,
            "sort_order": item.sort_order,
            "selected_by_default": item.selected_by_default,
        }
        for item in version.model_permissions.order_by("sort_order", "model_key")
    ]
    generated = generated_at.isoformat().replace("+00:00", "Z")
    snapshot = {
        "schema_version": "1.0",
        "plan_id": str(version.plan_id),
        "plan_version_id": str(version.pk),
        "version_no": version.version_no,
        "valid_days": version.valid_days,
        "queue_priority": version.queue_priority,
        "limits": limits,
        "model_permissions": models,
        "generated_at": generated,
        "catalog_version": CATALOG_VERSION,
    }
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return snapshot, hashlib.sha256(encoded).hexdigest()


def _snapshot_draft(version: PlanVersion, when) -> None:
    snapshot, digest = build_effective_config(version, when)
    version.snapshot_generated_at = when
    version.effective_config = snapshot
    version.config_digest = digest


@transaction.atomic
def publish_plan_version(
    *,
    version_id,
    actor,
    expected_version: int,
    confirm_informal_composite: bool,
) -> PlanVersion:
    plan, version = _locked_plan_and_version(version_id)
    _ensure_expected(version.version, expected_version)
    if plan.status == Plan.Status.ARCHIVED or version.status != PlanVersion.Status.DRAFT:
        raise PlanVersionStateConflict("当前版本不能发布。")
    PlanLimit.objects.select_for_update().filter(plan_version=version).count()
    PlanModelPermission.objects.select_for_update().filter(plan_version=version).count()
    validate_publishable(version, confirm_informal_composite=confirm_informal_composite)
    now = timezone.now()
    current = None
    if plan.current_published_version_id:
        current = PlanVersion.objects.select_for_update().get(pk=plan.current_published_version_id)
        if current.status != PlanVersion.Status.PUBLISHED:
            raise PlanStateConflict("当前版本指针失效。")
        current.status = PlanVersion.Status.RETIRED
        current.retired_at = now
        current.retired_by = actor
        current.version += 1
        current.save(update_fields=["status", "retired_at", "retired_by", "version", "updated_at"])
    _snapshot_draft(version, now)
    version.status = PlanVersion.Status.PUBLISHED
    version.published_at = now
    version.published_by = actor
    version.version += 1
    version.save(
        update_fields=[
            "status",
            "snapshot_generated_at",
            "effective_config",
            "config_digest",
            "published_at",
            "published_by",
            "version",
            "updated_at",
        ]
    )
    plan.current_published_version = version
    if plan.status == Plan.Status.DRAFT:
        plan.status = Plan.Status.PUBLISHED
    plan.updated_by = actor
    plan.version += 1
    plan.save(
        update_fields=[
            "current_published_version",
            "status",
            "updated_by",
            "version",
            "updated_at",
        ]
    )
    assert_pointer_consistency(plan)
    return version


@transaction.atomic
def set_plan_online(*, plan_id, actor, expected_version: int) -> Plan:
    plan = _locked_plan(plan_id)
    _ensure_expected(plan.version, expected_version, plan=True)
    if plan.status != Plan.Status.OFFLINE or plan.current_published_version_id is None:
        raise PlanStateConflict("仅有当前发布版本的下架套餐可重新上架。")
    current = PlanVersion.objects.select_for_update().get(pk=plan.current_published_version_id)
    if current.status != PlanVersion.Status.PUBLISHED:
        raise PlanStateConflict("当前版本不可上架。")
    plan.status = Plan.Status.PUBLISHED
    plan.updated_by = actor
    plan.version += 1
    plan.save(update_fields=["status", "updated_by", "version", "updated_at"])
    assert_pointer_consistency(plan)
    return plan


@transaction.atomic
def set_plan_offline(*, plan_id, actor, expected_version: int) -> Plan:
    plan = _locked_plan(plan_id)
    _ensure_expected(plan.version, expected_version, plan=True)
    if plan.status != Plan.Status.PUBLISHED:
        raise PlanStateConflict("仅已上架套餐可下架。")
    plan.status = Plan.Status.OFFLINE
    plan.updated_by = actor
    plan.version += 1
    plan.save(update_fields=["status", "updated_by", "version", "updated_at"])
    assert_pointer_consistency(plan)
    return plan


@transaction.atomic
def retire_plan_version(*, version_id, actor, expected_version: int) -> PlanVersion:
    plan, version = _locked_plan_and_version(version_id)
    _ensure_expected(version.version, expected_version)
    if plan.status == Plan.Status.ARCHIVED or version.status == PlanVersion.Status.RETIRED:
        raise PlanVersionStateConflict("当前版本不能退役。")
    now = timezone.now()
    if version.status == PlanVersion.Status.PUBLISHED:
        if plan.status != Plan.Status.OFFLINE or plan.current_published_version_id != version.pk:
            raise PlanVersionStateConflict("当前发布版本仅可在套餐下架后退役。")
        plan.current_published_version = None
    else:
        _snapshot_draft(version, now)
    version.status = PlanVersion.Status.RETIRED
    version.retired_at = now
    version.retired_by = actor
    version.version += 1
    version.save(
        update_fields=[
            "status",
            "snapshot_generated_at",
            "effective_config",
            "config_digest",
            "retired_at",
            "retired_by",
            "version",
            "updated_at",
        ]
    )
    plan.updated_by = actor
    plan.version += 1
    plan.save(update_fields=["current_published_version", "updated_by", "version", "updated_at"])
    assert_pointer_consistency(plan)
    return version


@transaction.atomic
def archive_plan(*, plan_id, actor, expected_version: int) -> Plan:
    plan = _locked_plan(plan_id)
    _ensure_expected(plan.version, expected_version, plan=True)
    if plan.status == Plan.Status.PUBLISHED:
        raise PlanStateConflict("已上架套餐必须先下架。")
    if plan.status not in (Plan.Status.DRAFT, Plan.Status.OFFLINE):
        raise PlanStateConflict("当前套餐不能归档。")
    versions = list(PlanVersion.objects.select_for_update().filter(plan=plan))
    now = timezone.now()
    for version in versions:
        if version.status == PlanVersion.Status.RETIRED:
            continue
        if version.status == PlanVersion.Status.DRAFT:
            _snapshot_draft(version, now)
        version.status = PlanVersion.Status.RETIRED
        version.retired_at = now
        version.retired_by = actor
        version.version += 1
        version.save(
            update_fields=[
                "status",
                "snapshot_generated_at",
                "effective_config",
                "config_digest",
                "retired_at",
                "retired_by",
                "version",
                "updated_at",
            ]
        )
    plan.status = Plan.Status.ARCHIVED
    plan.current_published_version = None
    plan.updated_by = actor
    plan.version += 1
    plan.save(
        update_fields=[
            "status",
            "current_published_version",
            "updated_by",
            "version",
            "updated_at",
        ]
    )
    assert_pointer_consistency(plan)
    return plan


@transaction.atomic
def copy_plan(
    *,
    source_plan_id,
    new_plan_id,
    actor,
    expected_source_plan_version: int,
    new_code: str,
    new_name: str,
    source_version_id=None,
) -> tuple[Plan, PlanVersion]:
    source_plan = _locked_plan(source_plan_id)
    _ensure_expected(source_plan.version, expected_source_plan_version, plan=True)
    if source_version_id:
        source = (
            PlanVersion.objects.select_for_update()
            .filter(pk=source_version_id, plan=source_plan)
            .first()
        )
    elif source_plan.current_published_version_id:
        source = PlanVersion.objects.select_for_update().get(
            pk=source_plan.current_published_version_id
        )
    else:
        source = None
    if source is None:
        raise PlanVersionStateConflict("复制套餐必须指定可用来源版本。")
    target = create_plan(
        plan_id=new_plan_id,
        actor=actor,
        data={
            "code": new_code,
            "name": new_name,
            "description": source_plan.description,
            "price_display_mode": source_plan.price_display_mode,
            "display_price": source_plan.display_price,
            "is_trial": source_plan.is_trial,
            "is_recommended": False,
            "sort_order": source_plan.sort_order,
        },
    )
    version = PlanVersion.objects.create(
        plan=target,
        version_no=1,
        valid_days=source.valid_days,
        queue_priority=source.queue_priority,
    )
    _clone_entitlements(source, version)
    return target, version


def public_plan_summary(plan: Plan) -> dict[str, Any]:
    version = plan.current_published_version
    if version is None:
        raise PlanStateConflict("套餐没有当前发布版本。")
    formal, _ = _formal_composite_capability(version)
    models = [
        {
            "model_key": item.model_key,
            "name": MODEL_NAMES[item.model_key],
            "selected_by_default": item.selected_by_default,
        }
        for item in version.model_permissions.order_by("sort_order", "model_key")
    ]
    visible_limit_keys = (
        "max_models_per_detection",
        "max_questions_per_detection",
        "geo_detection_runs",
        "article_generations",
        "auto_publish_count",
        "image_generations",
        "source_index_scans",
        "negative_index_scans",
        "website_audits",
        "website_generations",
        "video_script_generations",
        "competitor_comparisons",
        "keyword_generated_items",
        "question_generated_items",
        "white_label_enabled",
        "report_export_enabled",
        "report_share_enabled",
    )
    values = {
        item.limit_key: _limit_value(item)
        for item in version.limits.filter(limit_key__in=visible_limit_keys).order_by("limit_key")
    }
    return {
        "id": str(plan.pk),
        "plan_version_id": str(version.pk),
        "version_no": version.version_no,
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "price_display_mode": plan.price_display_mode,
        "display_price": str(plan.display_price) if plan.display_price is not None else None,
        "display_currency": plan.display_currency,
        "is_trial": plan.is_trial,
        "is_recommended": plan.is_recommended,
        "valid_days": version.valid_days,
        "benefits": values,
        "models": models,
        "supports_formal_composite": formal,
        "sort_order": plan.sort_order,
    }
