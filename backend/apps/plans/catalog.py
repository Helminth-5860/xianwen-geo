import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

MODEL_CATALOG = (
    ("deepseek", "DeepSeek"),
    ("doubao", "豆包"),
    ("qwen", "通义千问"),
    ("hunyuan", "腾讯混元"),
    ("wenxin", "百度文心"),
    ("kimi", "Kimi"),
    ("glm", "智谱 GLM"),
    ("spark", "讯飞星火"),
)
MODEL_KEYS = tuple(key for key, _ in MODEL_CATALOG)
MODEL_NAMES = dict(MODEL_CATALOG)
CATALOG_PATH = Path(settings.BASE_DIR).parent / "config" / "plan-limit-keys.json"


@dataclass(frozen=True)
class LimitDefinition:
    key: str
    name: str
    category: str
    value_type: str
    storage_kind: str
    scope: str
    quota_type: str
    status: str
    catalog_version: int
    sort_order: int
    required: bool
    default: Any
    minimum: int | None
    maximum: int | None
    unit: str
    description: str
    enum_values: tuple[str, ...]
    json_schema: dict[str, Any]

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "value_type": self.value_type,
            "storage_kind": self.storage_kind,
            "scope": self.scope,
            "quota_type": self.quota_type,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "unit": self.unit,
            "enum_values": list(self.enum_values),
            "json_schema": self.json_schema,
        }

    @property
    def semantic_digest(self) -> str:
        encoded = json.dumps(
            self.semantic_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _required(item: dict[str, Any], name: str) -> Any:
    if name not in item:
        raise ImproperlyConfigured(f"套餐限制键缺少字段：{name}")
    return item[name]


def load_limit_catalog(path: Path | None = None) -> tuple[str, tuple[LimitDefinition, ...]]:
    source = path or CATALOG_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImproperlyConfigured("套餐限制键目录无法读取。") from exc
    version = str(_required(raw, "catalog_version"))
    seen: set[str] = set()
    definitions: list[LimitDefinition] = []
    for index, item in enumerate(_required(raw, "limits")):
        key = str(_required(item, "key"))
        if key in seen:
            raise ImproperlyConfigured(f"套餐限制键重复：{key}")
        seen.add(key)
        value_type = str(_required(item, "value_type"))
        storage_kind = str(_required(item, "storage_kind"))
        status = str(_required(item, "status"))
        if value_type not in {"integer", "boolean", "text", "enum", "json"}:
            raise ImproperlyConfigured(f"套餐限制键类型无效：{key}")
        if storage_kind not in {"plan_limit", "plan_version_field", "model_permissions"}:
            raise ImproperlyConfigured(f"套餐限制键存储类型无效：{key}")
        if status not in {"active", "inactive"}:
            raise ImproperlyConfigured(f"套餐限制键状态无效：{key}")
        definition = LimitDefinition(
            key=key,
            name=str(_required(item, "name")),
            category=str(_required(item, "category")),
            value_type=value_type,
            storage_kind=storage_kind,
            scope=str(_required(item, "scope")),
            quota_type=str(item.get("quota_type", "")),
            status=status,
            catalog_version=int(item.get("catalog_version", 1)),
            sort_order=int(item.get("sort_order", index * 10)),
            required=bool(item.get("required", False)),
            default=item.get("default"),
            minimum=item.get("minimum"),
            maximum=item.get("maximum"),
            unit=str(item.get("unit", "")),
            description=str(item.get("description", "")),
            enum_values=tuple(str(value) for value in item.get("enum_values", [])),
            json_schema=dict(item.get("json_schema", {})),
        )
        if definition.catalog_version < 1:
            raise ImproperlyConfigured(f"套餐限制键目录版本无效：{key}")
        definitions.append(definition)
    return version, tuple(definitions)


CATALOG_VERSION, LIMIT_CATALOG = load_limit_catalog()
LIMIT_BY_KEY = {item.key: item for item in LIMIT_CATALOG}
ACTIVE_PLAN_LIMITS = tuple(
    item for item in LIMIT_CATALOG if item.status == "active" and item.storage_kind == "plan_limit"
)
