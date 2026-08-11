import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.admin_rbac.audit_services import record_audit_event
from apps.users.validators import validate_safe_plain_text

from .catalog import COMMON_FIELD_CATALOG
from .models import (
    SubjectFieldDefinition,
    SubjectFieldOption,
    SubjectType,
    SubjectTypeFieldConfig,
)

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CHOICE_TYPES = {
    SubjectFieldDefinition.FieldType.SINGLE,
    SubjectFieldDefinition.FieldType.MULTI,
    SubjectFieldDefinition.FieldType.SELECT,
}
NAME_ROLE_FIELD_TYPES: dict[str, set[str]] = {
    SubjectTypeFieldConfig.NameRole.OFFICIAL_NAME: {"text", "single", "select"},
    SubjectTypeFieldConfig.NameRole.ALIAS: {"text", "single", "select", "multi"},
    SubjectTypeFieldConfig.NameRole.ENGLISH_NAME: {"text", "single", "select", "multi"},
    SubjectTypeFieldConfig.NameRole.PRODUCT: {"text", "single", "select", "multi"},
}


class SubjectDomainError(Exception):
    code = "SUBJECT_FIELD_CONFIG_INVALID"


class SubjectTypeVersionConflict(SubjectDomainError):
    code = "SUBJECT_TYPE_VERSION_CONFLICT"


class SubjectSchemaVersionConflict(SubjectDomainError):
    code = "SUBJECT_SCHEMA_VERSION_CONFLICT"


class SubjectTypeKeyConflict(SubjectDomainError):
    code = "SUBJECT_TYPE_KEY_CONFLICT"


class SubjectFieldKeyConflict(SubjectDomainError):
    code = "SUBJECT_FIELD_KEY_CONFLICT"


class SubjectFieldConfigInvalid(SubjectDomainError):
    code = "SUBJECT_FIELD_CONFIG_INVALID"


class SubjectTypeStateConflict(SubjectDomainError):
    code = "SUBJECT_TYPE_STATE_CONFLICT"


def normalize_key(value: str, *, label: str) -> str:
    normalized = value.strip().lower()
    if not KEY_RE.fullmatch(normalized):
        raise SubjectFieldConfigInvalid(f"{label}必须使用小写 snake_case。")
    return normalized


def _plain(value: str, *, label: str, maximum: int, required: bool = True) -> str:
    return validate_safe_plain_text(
        value,
        field_label=label,
        max_length=maximum,
        required=required,
    )


def _locked_type(subject_type_id) -> SubjectType:
    try:
        return SubjectType.objects.select_for_update().get(pk=subject_type_id)
    except SubjectType.DoesNotExist as exc:
        raise NotFound from exc


def _ensure_type_versions(subject_type, expected_version=None, expected_schema_version=None):
    if expected_version is not None and subject_type.version != expected_version:
        raise SubjectTypeVersionConflict
    if (
        expected_schema_version is not None
        and subject_type.schema_version != expected_schema_version
    ):
        raise SubjectSchemaVersionConflict


def _bump_schema(subject_type: SubjectType, actor) -> None:
    subject_type.schema_version += 1
    subject_type.updated_by = actor
    subject_type.save(update_fields=["schema_version", "updated_by", "updated_at"])


def _enabled_option_keys(config: SubjectTypeFieldConfig) -> set[str]:
    return set(config.options.filter(enabled=True).values_list("option_key", flat=True))


def validate_default_value(config: SubjectTypeFieldConfig, value: Any) -> Any:
    field_type = config.field_definition.field_type
    if value is None:
        return None
    if field_type in {
        SubjectFieldDefinition.FieldType.TEXT,
        SubjectFieldDefinition.FieldType.TEXTAREA,
    }:
        if not isinstance(value, str):
            raise SubjectFieldConfigInvalid("文本字段默认值必须是字符串或 null。")
        return _plain(value, label="默认值", maximum=2000, required=False)
    if field_type == SubjectFieldDefinition.FieldType.NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SubjectFieldConfigInvalid("数字字段默认值必须是 JSON number 或 null。")
        if not float(value) == float(value) or value in (float("inf"), float("-inf")):
            raise SubjectFieldConfigInvalid("数字字段默认值必须是有限数值。")
        return value
    if field_type == SubjectFieldDefinition.FieldType.DATE:
        if not isinstance(value, str):
            raise SubjectFieldConfigInvalid("日期默认值必须是 YYYY-MM-DD 或 null。")
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError as exc:
            raise SubjectFieldConfigInvalid("日期默认值必须是 YYYY-MM-DD 或 null。") from exc
        return value
    if field_type == SubjectFieldDefinition.FieldType.URL:
        if not isinstance(value, str):
            raise SubjectFieldConfigInvalid("网址默认值必须是 HTTP/HTTPS URL 或 null。")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SubjectFieldConfigInvalid("网址默认值必须是 HTTP/HTTPS URL 或 null。")
        return value
    if field_type in {
        SubjectFieldDefinition.FieldType.SINGLE,
        SubjectFieldDefinition.FieldType.SELECT,
    }:
        if not isinstance(value, str) or value not in _enabled_option_keys(config):
            raise SubjectFieldConfigInvalid("默认值必须引用已启用的 option_key。")
        return value
    if field_type == SubjectFieldDefinition.FieldType.MULTI:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise SubjectFieldConfigInvalid("多选默认值必须是 option_key 数组。")
        if len(value) != len(set(value)) or not set(value).issubset(_enabled_option_keys(config)):
            raise SubjectFieldConfigInvalid("多选默认值包含重复或未启用的 option_key。")
        return value
    if field_type in {
        SubjectFieldDefinition.FieldType.IMAGE,
        SubjectFieldDefinition.FieldType.FILE,
    }:
        raise SubjectFieldConfigInvalid("图片和文件字段在当前版本不能设置默认值。")
    raise SubjectFieldConfigInvalid("未知字段类型。")


def validate_name_role_type(config: SubjectTypeFieldConfig) -> None:
    role = config.name_role
    if role == SubjectTypeFieldConfig.NameRole.NONE:
        return
    if config.field_definition.field_type not in NAME_ROLE_FIELD_TYPES.get(role, set()):
        raise SubjectFieldConfigInvalid(
            "\u5b57\u6bb5\u7c7b\u578b\u4e0d\u652f\u6301\u5f53\u524d\u540d\u79f0\u8bed\u4e49\u89d2\u8272\uff0c\u8bf7\u505c\u7528\u65e7\u5b57\u6bb5\u5e76\u521b\u5efa\u6b63\u786e\u7c7b\u578b\u7684\u65b0\u5b57\u6bb5\u3002"
        )


def ensure_schema_invariants(subject_type: SubjectType) -> None:
    configs = list(
        SubjectTypeFieldConfig.objects.filter(subject_type=subject_type)
        .select_related("field_definition")
        .prefetch_related("options")
    )
    seen_keys: set[str] = set()
    roles: dict[str, int] = {}
    official = 0
    for config in configs:
        definition = config.field_definition
        key = definition.field_key.lower()
        if key in seen_keys:
            raise SubjectFieldKeyConflict
        seen_keys.add(key)
        if definition.scope == SubjectFieldDefinition.Scope.CUSTOM and (
            definition.owner_subject_type_id != subject_type.pk
        ):
            raise SubjectFieldConfigInvalid("自定义字段不能绑定到其他主体类型。")
        option_count = config.options.count()
        if definition.field_type not in CHOICE_TYPES and option_count:
            raise SubjectFieldConfigInvalid("非选择字段不能配置选项。")
        if (
            config.enabled
            and definition.field_type in CHOICE_TYPES
            and not config.options.filter(enabled=True).exists()
        ):
            raise SubjectFieldConfigInvalid("启用的选择字段必须至少有一个启用选项。")
        validate_default_value(config, config.default_value)
        validate_name_role_type(config)
        if config.enabled and config.name_role != SubjectTypeFieldConfig.NameRole.NONE:
            roles[config.name_role] = roles.get(config.name_role, 0) + 1
        if (
            config.enabled
            and config.required
            and config.name_role == SubjectTypeFieldConfig.NameRole.OFFICIAL_NAME
        ):
            official += 1
    if subject_type.status == SubjectType.Status.ACTIVE:
        if official != 1:
            raise SubjectTypeStateConflict("启用主体类型必须有且只有一个必填正式名称字段。")
        if any(count != 1 for count in roles.values()):
            raise SubjectTypeStateConflict("启用 Schema 中非 none 的 name_role 必须唯一。")


def _audit(request, *, action, target_type, target_id, before=None, after=None):
    return record_audit_event(
        request=request,
        category="subject_schema",
        action_key=action,
        outcome="executed",
        actor=request.user,
        target_type=target_type,
        target_id=target_id,
        safe_before=before or {},
        safe_after=after or {},
    )


@transaction.atomic
def create_subject_type(*, request, data) -> SubjectType:
    key = normalize_key(data["key"], label="类型键")
    try:
        subject_type = SubjectType.objects.create(
            key=key,
            name=_plain(data["name"], label="名称", maximum=100),
            description=_plain(
                data.get("description", ""), label="说明", maximum=500, required=False
            ),
            icon_key=normalize_key(data.get("icon_key", "subject"), label="图标键"),
            status=SubjectType.Status.ACTIVE,
            sort_order=data.get("sort_order", 0),
            is_builtin=False,
            created_by=request.user,
            updated_by=request.user,
        )
    except IntegrityError as exc:
        raise SubjectTypeKeyConflict from exc
    common = {
        item.field_key: item
        for item in SubjectFieldDefinition.objects.filter(
            scope=SubjectFieldDefinition.Scope.COMMON,
            is_builtin=True,
        )
    }
    if set(common) != {item.key for item in COMMON_FIELD_CATALOG}:
        raise SubjectFieldConfigInvalid("公共字段目录不完整，请先同步目录。")
    SubjectTypeFieldConfig.objects.bulk_create(
        [
            SubjectTypeFieldConfig(
                subject_type=subject_type,
                field_definition=common[item.key],
                label=item.label,
                description=item.description,
                required=item.required,
                default_value=None,
                sort_order=item.sort_order,
                enabled=True,
                used_for_ai=item.used_for_ai,
                name_role=item.name_role,
                created_by=request.user,
                updated_by=request.user,
            )
            for item in COMMON_FIELD_CATALOG
        ]
    )
    ensure_schema_invariants(subject_type)
    _audit(
        request,
        action="subject_type.create",
        target_type="subject_type",
        target_id=subject_type.pk,
        after={"key": subject_type.key, "schema_version": subject_type.schema_version},
    )
    return subject_type


@transaction.atomic
def update_subject_type(*, request, subject_type_id, data) -> SubjectType:
    subject_type = _locked_type(subject_type_id)
    _ensure_type_versions(
        subject_type,
        data.pop("expected_version"),
        data.pop("expected_schema_version"),
    )
    before = {
        "status": subject_type.status,
        "version": subject_type.version,
        "schema_version": subject_type.schema_version,
    }
    for field, label, maximum in (
        ("name", "名称", 100),
        ("description", "说明", 500),
    ):
        if field in data:
            setattr(
                subject_type,
                field,
                _plain(data[field], label=label, maximum=maximum, required=field == "name"),
            )
    if "icon_key" in data:
        subject_type.icon_key = normalize_key(data["icon_key"], label="图标键")
    if "sort_order" in data:
        subject_type.sort_order = data["sort_order"]
    subject_type.version += 1
    subject_type.schema_version += 1
    subject_type.updated_by = request.user
    subject_type.save()
    ensure_schema_invariants(subject_type)
    _audit(
        request,
        action="subject_type.update",
        target_type="subject_type",
        target_id=subject_type.pk,
        before=before,
        after={"version": subject_type.version, "schema_version": subject_type.schema_version},
    )
    return subject_type


@transaction.atomic
def set_subject_type_status(*, request, subject_type_id, status, data) -> SubjectType:
    subject_type = _locked_type(subject_type_id)
    _ensure_type_versions(
        subject_type,
        data["expected_version"],
        data["expected_schema_version"],
    )
    if subject_type.status == status:
        raise SubjectTypeStateConflict
    before = {
        "status": subject_type.status,
        "version": subject_type.version,
        "schema_version": subject_type.schema_version,
    }
    subject_type.status = status
    subject_type.version += 1
    subject_type.schema_version += 1
    subject_type.updated_by = request.user
    subject_type.save()
    ensure_schema_invariants(subject_type)
    _audit(
        request,
        action=f"subject_type.{status}",
        target_type="subject_type",
        target_id=subject_type.pk,
        before=before,
        after={
            "status": status,
            "version": subject_type.version,
            "schema_version": subject_type.schema_version,
        },
    )
    return subject_type


@transaction.atomic
def create_custom_field(*, request, subject_type_id, data) -> SubjectTypeFieldConfig:
    subject_type = _locked_type(subject_type_id)
    expected_schema = data.pop("expected_schema_version")
    _ensure_type_versions(subject_type, expected_schema_version=expected_schema)
    field_key = normalize_key(data.pop("field_key"), label="字段键")
    field_type = data.pop("field_type")
    options = data.pop("options", [])
    if SubjectTypeFieldConfig.objects.filter(
        subject_type=subject_type,
        field_definition__field_key__iexact=field_key,
    ).exists():
        raise SubjectFieldKeyConflict
    try:
        definition = SubjectFieldDefinition.objects.create(
            owner_subject_type=subject_type,
            field_key=field_key,
            field_type=field_type,
            scope=SubjectFieldDefinition.Scope.CUSTOM,
            is_builtin=False,
            created_by=request.user,
        )
        config = SubjectTypeFieldConfig.objects.create(
            subject_type=subject_type,
            field_definition=definition,
            label=_plain(data["label"], label="字段名称", maximum=100),
            description=_plain(
                data.get("description", ""), label="字段说明", maximum=500, required=False
            ),
            required=data.get("required", False),
            default_value=None,
            sort_order=data.get("sort_order", 0),
            enabled=data.get("enabled", False),
            used_for_ai=data.get("used_for_ai", False),
            name_role=data.get("name_role", SubjectTypeFieldConfig.NameRole.NONE),
            created_by=request.user,
            updated_by=request.user,
        )
        for index, option in enumerate(options):
            SubjectFieldOption.objects.create(
                field_config=config,
                option_key=normalize_key(option["option_key"], label="选项键"),
                label=_plain(option["label"], label="选项名称", maximum=100),
                enabled=option.get("enabled", True),
                sort_order=option.get("sort_order", index * 10),
                created_by=request.user,
                updated_by=request.user,
            )
    except IntegrityError as exc:
        raise SubjectFieldKeyConflict from exc
    config.default_value = validate_default_value(config, data.get("default_value"))
    config.save(update_fields=["default_value", "updated_at"])
    ensure_schema_invariants(subject_type)
    _bump_schema(subject_type, request.user)
    _audit(
        request,
        action="subject_field.create",
        target_type="subject_type_field_config",
        target_id=config.pk,
        after={"field_key": field_key, "schema_version": subject_type.schema_version},
    )
    return config


@transaction.atomic
def update_field_config(*, request, config_id, data) -> SubjectTypeFieldConfig:
    try:
        subject_type_id = (
            SubjectTypeFieldConfig.objects.only("subject_type_id").get(pk=config_id).subject_type_id
        )
    except SubjectTypeFieldConfig.DoesNotExist as exc:
        raise NotFound from exc
    subject_type = _locked_type(subject_type_id)
    expected_schema = data.pop("expected_schema_version")
    expected_version = data.pop("expected_version")
    _ensure_type_versions(subject_type, expected_schema_version=expected_schema)
    config = (
        SubjectTypeFieldConfig.objects.select_for_update()
        .select_related("field_definition")
        .get(pk=config_id)
    )
    if config.version != expected_version:
        raise SubjectSchemaVersionConflict
    before = {
        "version": config.version,
        "schema_version": subject_type.schema_version,
        "enabled": config.enabled,
        "required": config.required,
        "name_role": config.name_role,
    }
    for field, label, maximum in (
        ("label", "字段名称", 100),
        ("description", "字段说明", 500),
    ):
        if field in data:
            setattr(
                config,
                field,
                _plain(data[field], label=label, maximum=maximum, required=field == "label"),
            )
    for field in ("required", "sort_order", "enabled", "used_for_ai", "name_role"):
        if field in data:
            setattr(config, field, data[field])
    if not config.enabled:
        config.required = False
    if "default_value" in data:
        config.default_value = validate_default_value(config, data["default_value"])
    else:
        validate_default_value(config, config.default_value)
    config.version += 1
    config.updated_by = request.user
    config.save()
    ensure_schema_invariants(subject_type)
    _bump_schema(subject_type, request.user)
    _audit(
        request,
        action="subject_field.update",
        target_type="subject_type_field_config",
        target_id=config.pk,
        before=before,
        after={
            "version": config.version,
            "schema_version": subject_type.schema_version,
            "enabled": config.enabled,
            "required": config.required,
            "name_role": config.name_role,
        },
    )
    return config


@transaction.atomic
def create_field_option(*, request, config_id, data) -> SubjectFieldOption:
    try:
        config_binding = SubjectTypeFieldConfig.objects.only("subject_type_id").get(pk=config_id)
    except SubjectTypeFieldConfig.DoesNotExist as exc:
        raise NotFound from exc
    subject_type = _locked_type(config_binding.subject_type_id)
    _ensure_type_versions(subject_type, expected_schema_version=data.pop("expected_schema_version"))
    config = (
        SubjectTypeFieldConfig.objects.select_for_update()
        .select_related("field_definition")
        .get(pk=config_id)
    )
    if config.version != data.pop("expected_config_version"):
        raise SubjectSchemaVersionConflict
    if config.field_definition.field_type not in CHOICE_TYPES:
        raise SubjectFieldConfigInvalid("非选择字段不能配置选项。")
    try:
        option = SubjectFieldOption.objects.create(
            field_config=config,
            option_key=normalize_key(data["option_key"], label="选项键"),
            label=_plain(data["label"], label="选项名称", maximum=100),
            enabled=data.get("enabled", True),
            sort_order=data.get("sort_order", 0),
            created_by=request.user,
            updated_by=request.user,
        )
    except IntegrityError as exc:
        raise SubjectFieldKeyConflict("选项键已存在。") from exc
    config.version += 1
    config.updated_by = request.user
    config.save(update_fields=["version", "updated_by", "updated_at"])
    validate_default_value(config, config.default_value)
    ensure_schema_invariants(subject_type)
    _bump_schema(subject_type, request.user)
    _audit(
        request,
        action="subject_field_option.create",
        target_type="subject_field_option",
        target_id=option.pk,
        after={"option_key": option.option_key, "schema_version": subject_type.schema_version},
    )
    return option


@transaction.atomic
def update_field_option(*, request, option_id, data) -> SubjectFieldOption:
    try:
        binding = (
            SubjectFieldOption.objects.select_related("field_config")
            .only("field_config__subject_type_id")
            .get(pk=option_id)
        )
    except SubjectFieldOption.DoesNotExist as exc:
        raise NotFound from exc
    subject_type = _locked_type(binding.field_config.subject_type_id)
    _ensure_type_versions(subject_type, expected_schema_version=data.pop("expected_schema_version"))
    option = (
        SubjectFieldOption.objects.select_for_update()
        .select_related("field_config__field_definition")
        .get(pk=option_id)
    )
    if option.version != data.pop("expected_version"):
        raise SubjectSchemaVersionConflict
    before = {"version": option.version, "enabled": option.enabled}
    if "label" in data:
        option.label = _plain(data["label"], label="选项名称", maximum=100)
    for field in ("enabled", "sort_order"):
        if field in data:
            setattr(option, field, data[field])
    option.version += 1
    option.updated_by = request.user
    option.save()
    config = option.field_config
    config.version += 1
    config.updated_by = request.user
    config.save(update_fields=["version", "updated_by", "updated_at"])
    validate_default_value(config, config.default_value)
    ensure_schema_invariants(subject_type)
    _bump_schema(subject_type, request.user)
    _audit(
        request,
        action="subject_field_option.update",
        target_type="subject_field_option",
        target_id=option.pk,
        before=before,
        after={
            "version": option.version,
            "enabled": option.enabled,
            "schema_version": subject_type.schema_version,
        },
    )
    return option


@transaction.atomic
def reorder_fields(*, request, subject_type_id, data) -> SubjectType:
    subject_type = _locked_type(subject_type_id)
    _ensure_type_versions(subject_type, expected_schema_version=data["expected_schema_version"])
    configs = list(
        SubjectTypeFieldConfig.objects.select_for_update()
        .filter(subject_type=subject_type)
        .order_by("id")
    )
    items = data["fields"]
    actual_ids = {config.pk for config in configs}
    supplied_ids = [item["id"] for item in items]
    if len(supplied_ids) != len(set(supplied_ids)) or set(supplied_ids) != actual_ids:
        raise SubjectFieldConfigInvalid("字段排序必须完整包含当前类型全部字段且不能重复。")
    by_id = {config.pk: config for config in configs}
    for item in items:
        if by_id[item["id"]].version != item["expected_version"]:
            raise SubjectSchemaVersionConflict
    for index, item in enumerate(items):
        config = by_id[item["id"]]
        config.sort_order = index * 10
        config.version += 1
        config.updated_by = request.user
        config.updated_at = timezone.now()
    SubjectTypeFieldConfig.objects.bulk_update(
        configs, ["sort_order", "version", "updated_by", "updated_at"]
    )
    ensure_schema_invariants(subject_type)
    _bump_schema(subject_type, request.user)
    _audit(
        request,
        action="subject_schema.reorder",
        target_type="subject_type",
        target_id=subject_type.pk,
        after={"field_count": len(configs), "schema_version": subject_type.schema_version},
    )
    return subject_type
