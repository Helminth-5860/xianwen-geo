import hashlib
import json
import re
import unicodedata
from typing import Any

CATALOG_FORMAT_VERSION = 1
VALID_OPERATORS = {"equals_any", "contains_any"}
VALID_REASONS = {
    "suspected_violation",
    "suspected_impersonation",
    "data_conflict",
    "high_risk_industry",
}
MACHINE_KEY = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class RiskCatalogInvalid(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def catalog_digest(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(snapshot)).hexdigest()


def normalize_literal(value: Any) -> str:
    if not isinstance(value, str):
        raise RiskCatalogInvalid("Risk literal must be text.")
    value = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise RiskCatalogInvalid("Control characters are forbidden.")
    value = " ".join(value.split()).casefold()
    if not value or len(value) > 200:
        raise RiskCatalogInvalid("Risk literal length is invalid.")
    lowered = value.casefold()
    if "://" in lowered or "<script" in lowered or ("$" + "{") in lowered or "{{" in lowered:
        raise RiskCatalogInvalid("Dynamic expressions, scripts and URLs are forbidden.")
    return value


def normalize_patterns(patterns: Any) -> list[str]:
    if not isinstance(patterns, list) or not 1 <= len(patterns) <= 50:
        raise RiskCatalogInvalid("Patterns must contain between 1 and 50 values.")
    normalized = [normalize_literal(value) for value in patterns]
    if len(normalized) != len(set(normalized)):
        raise RiskCatalogInvalid("Duplicate patterns are forbidden.")
    return sorted(normalized)


def validate_catalog_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("format_version") != CATALOG_FORMAT_VERSION:
        raise RiskCatalogInvalid("Unsupported catalog format.")
    types = snapshot.get("risk_types")
    rules = snapshot.get("rules")
    if not isinstance(types, list) or not isinstance(rules, list):
        raise RiskCatalogInvalid("Invalid catalog structure.")
    type_keys: set[str] = set()
    for item in types:
        if not isinstance(item, dict) or not MACHINE_KEY.fullmatch(str(item.get("key", ""))):
            raise RiskCatalogInvalid("Invalid risk type key.")
        if item["key"] in type_keys:
            raise RiskCatalogInvalid("Duplicate risk type key.")
        type_keys.add(item["key"])
        for flag in (
            "enabled",
            "manual_review_required",
            "allow_geo_detection",
            "allow_article_generation",
            "allow_image_generation",
            "require_authoritative_citations",
            "require_disclaimer",
        ):
            if not isinstance(item.get(flag), bool):
                raise RiskCatalogInvalid("Risk policy flags must be booleans.")
    rule_keys: set[str] = set()
    for item in rules:
        if not isinstance(item, dict) or not MACHINE_KEY.fullmatch(str(item.get("key", ""))):
            raise RiskCatalogInvalid("Invalid risk rule key.")
        if item["key"] in rule_keys or item.get("risk_type_key") not in type_keys:
            raise RiskCatalogInvalid("Invalid risk rule binding.")
        rule_keys.add(item["key"])
        if item.get("operator") not in VALID_OPERATORS:
            raise RiskCatalogInvalid("Unsupported risk operator.")
        if item.get("reason_type") not in VALID_REASONS:
            raise RiskCatalogInvalid("Unsupported reason type.")
        item["patterns"] = normalize_patterns(item.get("patterns"))
        if not isinstance(item.get("enabled"), bool):
            raise RiskCatalogInvalid("Rule enabled must be a boolean.")
    return snapshot


def _choice_label(field: dict[str, Any], value: Any) -> str:
    by_key = {
        option["option_key"]: option["label"]
        for option in field.get("options", [])
        if option.get("enabled")
    }
    return str(by_key.get(value, value))


def _field_values(
    schema_snapshot: dict[str, Any], field_values: dict[str, Any]
) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for field in schema_snapshot.get("fields", []):
        if field.get("field_type") in {"image", "file"}:
            continue
        key = field.get("field_key")
        if not key or key not in field_values:
            continue
        raw = field_values[key]
        values = raw if isinstance(raw, list) else [raw]
        normalized: list[str] = []
        for value in values:
            if value is None:
                continue
            if field.get("field_type") in {"single", "select", "multi"}:
                value = _choice_label(field, value)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                try:
                    normalized.append(normalize_literal(str(value)))
                except RiskCatalogInvalid:
                    continue
        output[key] = normalized
    return output


def evaluate_catalog(
    *,
    snapshot: dict[str, Any],
    subject_type_key: str,
    schema_snapshot: dict[str, Any],
    field_values: dict[str, Any],
) -> list[dict[str, str]]:
    validate_catalog_snapshot(snapshot)
    types = {item["key"]: item for item in snapshot["risk_types"] if item["enabled"]}
    values = _field_values(schema_snapshot, field_values)
    hits: list[dict[str, str]] = []
    for rule in snapshot["rules"]:
        if not rule["enabled"] or rule["risk_type_key"] not in types:
            continue
        if rule.get("subject_type_key") not in (None, "", subject_type_key):
            continue
        field_keys = [rule["field_key"]] if rule.get("field_key") else sorted(values)
        matched_field = ""
        patterns = set(rule["patterns"])
        for field_key in field_keys:
            for value in values.get(field_key, []):
                matched = (
                    value in patterns
                    if rule["operator"] == "equals_any"
                    else any(pattern in value for pattern in patterns)
                )
                if matched:
                    matched_field = field_key
                    break
            if matched_field:
                break
        if matched_field:
            hits.append(
                {
                    "risk_type_key": rule["risk_type_key"],
                    "rule_key": rule["key"],
                    "reason_type": rule["reason_type"],
                    "field_key": matched_field,
                }
            )
    return sorted(hits, key=lambda item: (item["rule_key"], item["field_key"]))
