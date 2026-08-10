import copy
import hashlib
import json
import math
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
        raise SnapshotValueError(field_key)
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
