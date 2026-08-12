import copy
import hashlib
import json
import math
import uuid
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from .models import SubjectType

SCHEMA_SNAPSHOT_FORMAT_VERSION = 1
MAX_TEXT_LENGTH = 50_000
MAX_ABS_NUMBER = 10**15


class SnapshotValueError(ValueError):
    def __init__(self, field_key: str):
        self.field_key = field_key
        super().__init__(field_key)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()


def build_schema_snapshot(subject_type: SubjectType) -> tuple[dict[str, Any], str]:
    configs = (
        subject_type.field_configs.filter(enabled=True)
        .select_related("field_definition")
        .prefetch_related("options")
        .order_by("sort_order", "field_definition__field_key", "id")
    )
    fields: list[dict[str, Any]] = []
    for config in configs:
        definition = config.field_definition
        options = [
            {
                "option_key": option.option_key,
                "label": option.label,
                "sort_order": option.sort_order,
            }
            for option in config.options.filter(enabled=True).order_by(
                "sort_order", "option_key", "id"
            )
        ]
        fields.append(
            {
                "field_key": definition.field_key,
                "field_type": definition.field_type,
                "scope": definition.scope,
                "label": config.label,
                "description": config.description,
                "required": config.required,
                "default_value": copy.deepcopy(config.default_value),
                "sort_order": config.sort_order,
                "used_for_ai": config.used_for_ai,
                "name_role": config.name_role,
                "options": options,
            }
        )
    snapshot = {
        "format_version": SCHEMA_SNAPSHOT_FORMAT_VERSION,
        "subject_type": {
            "id": str(subject_type.pk),
            "key": subject_type.key,
            "name": subject_type.name,
            "description": subject_type.description,
            "icon_key": subject_type.icon_key,
        },
        "schema_version": subject_type.schema_version,
        "fields": fields,
    }
    return snapshot, snapshot_digest(snapshot)


def public_form_schema(snapshot: dict[str, Any]) -> dict[str, Any]:
    subject_type = snapshot["subject_type"]
    return {
        "id": subject_type["id"],
        "key": subject_type["key"],
        "name": subject_type["name"],
        "description": subject_type["description"],
        "icon_key": subject_type["icon_key"],
        "schema_version": snapshot["schema_version"],
        "fields": copy.deepcopy(snapshot["fields"]),
    }


def materialize_defaults(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        field["field_key"]: copy.deepcopy(field.get("default_value"))
        for field in snapshot["fields"]
    }


def _choice_keys(field: dict[str, Any]) -> set[str]:
    return {option["option_key"] for option in field.get("options", [])}


def _validate_value(field: dict[str, Any], value: Any) -> Any:
    field_key = field["field_key"]
    field_type = field["field_type"]
    if value is None:
        return None
    if field_type in {"text", "textarea"}:
        if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
            raise SnapshotValueError(field_key)
        return value
    if field_type == "number":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or abs(value) > MAX_ABS_NUMBER
        ):
            raise SnapshotValueError(field_key)
        return value
    if field_type == "date":
        if not isinstance(value, str):
            raise SnapshotValueError(field_key)
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise SnapshotValueError(field_key) from exc
        if parsed_date.isoformat() != value:
            raise SnapshotValueError(field_key)
        return value
    if field_type == "url":
        if not isinstance(value, str) or len(value) > 2048:
            raise SnapshotValueError(field_key)
        parsed_url = urlsplit(value)
        if (
            parsed_url.scheme.lower() not in {"http", "https"}
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise SnapshotValueError(field_key)
        return value
    if field_type in {"single", "select"}:
        if not isinstance(value, str) or value not in _choice_keys(field):
            raise SnapshotValueError(field_key)
        return value
    if field_type == "multi":
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
            or len(value) != len(set(value))
            or not set(value) <= _choice_keys(field)
        ):
            raise SnapshotValueError(field_key)
        return list(value)
    if field_type in {"image", "file"}:
        if not isinstance(value, dict) or set(value) != {"document_version_id"}:
            raise SnapshotValueError(field_key)
        try:
            version_id = str(uuid.UUID(str(value["document_version_id"])))
        except (TypeError, ValueError, AttributeError) as exc:
            raise SnapshotValueError(field_key) from exc
        return {"document_version_id": version_id}
    raise SnapshotValueError(field_key)


def merge_and_validate_values(
    snapshot: dict[str, Any],
    *,
    current: dict[str, Any] | None = None,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = {field["field_key"]: field for field in snapshot["fields"]}
    result = copy.deepcopy(current if current is not None else materialize_defaults(snapshot))
    patch = updates or {}
    unknown = set(patch) - set(fields)
    if unknown:
        raise SnapshotValueError(sorted(unknown)[0])
    for field_key, value in patch.items():
        result[field_key] = _validate_value(fields[field_key], value)
    for field_key in set(result) - set(fields):
        raise SnapshotValueError(field_key)
    return result


def assert_snapshot_integrity(snapshot: dict[str, Any], digest: str) -> None:
    if (
        snapshot.get("format_version") != SCHEMA_SNAPSHOT_FORMAT_VERSION
        or snapshot_digest(snapshot) != digest
    ):
        raise ValueError("Invalid subject schema snapshot.")


class FrozenRequiredFieldsError(ValueError):
    def __init__(self, field_keys: list[str]):
        self.field_keys = field_keys
        super().__init__(",".join(field_keys))


class FrozenSemanticError(ValueError):
    pass


def values_digest(values: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(values).encode("utf-8")).hexdigest()


def normalize_semantic_text(value: str) -> tuple[str, str]:
    import unicodedata

    normalized = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(char) == "Cc" for char in normalized):
        raise FrozenSemanticError("Semantic value contains control characters.")
    display = " ".join(normalized.split())
    if not display or len(display) > 500:
        raise FrozenSemanticError("Semantic value is empty or too long.")
    return display, display.casefold()


def _required_value_present(field: dict[str, Any], value: Any) -> bool:
    if value is None:
        return False
    field_type = field["field_type"]
    if field_type in {"text", "textarea", "url"}:
        return isinstance(value, str) and bool(value.strip())
    if field_type == "multi":
        return isinstance(value, list) and bool(value)
    if field_type in {"image", "file"}:
        return (
            isinstance(value, dict)
            and set(value) == {"document_version_id"}
            and bool(value["document_version_id"])
        )
    return True


def validate_frozen_commit_values(
    snapshot: dict[str, Any], values: dict[str, Any]
) -> dict[str, Any]:
    validated = merge_and_validate_values(snapshot, updates=values)
    missing = [
        field["field_key"]
        for field in snapshot["fields"]
        if field.get("required")
        and not _required_value_present(field, validated.get(field["field_key"]))
    ]
    if missing:
        raise FrozenRequiredFieldsError(sorted(missing))
    return validated


def _semantic_values(field: dict[str, Any], value: Any) -> list[tuple[str, str]]:
    if value is None or value == "" or value == []:
        return []
    field_type = field["field_type"]
    if field_type == "text":
        return [normalize_semantic_text(value)]
    if field_type in {"single", "select"}:
        option_labels = {
            option["option_key"]: option["label"] for option in field.get("options", [])
        }
        try:
            return [normalize_semantic_text(option_labels[value])]
        except KeyError as exc:
            raise FrozenSemanticError("Unknown frozen option key.") from exc
    if field_type == "multi":
        option_labels = {
            option["option_key"]: option["label"] for option in field.get("options", [])
        }
        try:
            return [normalize_semantic_text(option_labels[item]) for item in value]
        except KeyError as exc:
            raise FrozenSemanticError("Unknown frozen option key.") from exc
    raise FrozenSemanticError("name_role is incompatible with the frozen field type.")


def derive_frozen_semantics(
    snapshot: dict[str, Any], values: dict[str, Any]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    allowed_types = {
        "official_name": {"text", "single", "select"},
        "alias": {"text", "single", "select", "multi"},
        "english_name": {"text", "single", "select", "multi"},
        "product": {"text", "single", "select", "multi"},
    }
    names: list[dict[str, str]] = []
    products: list[dict[str, str]] = []
    seen_names: set[tuple[str, str]] = set()
    seen_products: set[str] = set()
    for field in snapshot["fields"]:
        role = field.get("name_role", "none")
        if role == "none":
            continue
        if role not in allowed_types or field["field_type"] not in allowed_types[role]:
            raise FrozenSemanticError("name_role is incompatible with the frozen field type.")
        for display, matching in _semantic_values(field, values.get(field["field_key"])):
            if role == "product":
                if matching in seen_products:
                    continue
                seen_products.add(matching)
                candidate_key = hashlib.sha256(
                    canonical_json(
                        {"field_key": field["field_key"], "matching_value": matching}
                    ).encode("utf-8")
                ).hexdigest()
                products.append(
                    {
                        "candidate_key": candidate_key,
                        "display_value": display,
                        "matching_value": matching,
                        "source_field_key": field["field_key"],
                    }
                )
                continue
            key = (role, matching)
            if key in seen_names:
                continue
            seen_names.add(key)
            names.append(
                {
                    "role": role,
                    "display_value": display,
                    "matching_value": matching,
                    "source_field_key": field["field_key"],
                }
            )
    if sum(name["role"] == "official_name" for name in names) != 1:
        raise FrozenSemanticError("Exactly one official name is required.")
    return names, products


def committed_semantic_digest(
    *,
    schema_digest_value: str,
    field_values: dict[str, Any],
    product_confirmations: list[dict[str, Any]],
) -> str:
    payload = {
        "schema_digest": schema_digest_value,
        "field_values": field_values,
        "products": sorted(product_confirmations, key=lambda item: item["candidate_key"]),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def derive_product_candidates(
    snapshot: dict[str, Any], values: dict[str, Any]
) -> list[dict[str, str]]:
    products: list[dict[str, str]] = []
    seen: set[str] = set()
    for field in snapshot["fields"]:
        if field.get("name_role", "none") != "product":
            continue
        if field["field_type"] not in {"text", "single", "select", "multi"}:
            raise FrozenSemanticError("Product role is incompatible with the frozen field type.")
        for display, matching in _semantic_values(field, values.get(field["field_key"])):
            if matching in seen:
                continue
            seen.add(matching)
            products.append(
                {
                    "candidate_key": hashlib.sha256(
                        canonical_json(
                            {"field_key": field["field_key"], "matching_value": matching}
                        ).encode("utf-8")
                    ).hexdigest(),
                    "display_value": display,
                    "matching_value": matching,
                    "source_field_key": field["field_key"],
                }
            )
    return products
