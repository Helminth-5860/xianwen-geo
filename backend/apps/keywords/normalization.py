import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Any

from .models import KeywordItemFields
from .taxonomy import normalize_intents


class KeywordNormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedKeyword:
    text: str
    matching_text: str
    structure_type: str
    is_regional: bool
    region_level: str
    region_text: str
    region_matching_key: str
    base_keyword_text: str | None
    base_keyword_matching: str | None
    business_category: str | None
    search_intent: str | None
    search_intents: tuple[str, ...]
    regions: tuple[dict[str, Any], ...]
    source: str
    notes: str
    relevance_score: int | None
    priority: str | None
    ai_reason: str | None
    sort_order: int

    def semantic_payload(self) -> dict[str, object]:
        return {
            "text": self.text,
            "matching_text": self.matching_text,
            "structure_type": self.structure_type,
            "is_regional": self.is_regional,
            "region_level": self.region_level,
            "region_text": self.region_text,
            "region_matching_key": self.region_matching_key,
            "base_keyword_text": self.base_keyword_text,
            "business_category": self.business_category,
            "search_intent": self.search_intent,
            "search_intents": list(self.search_intents),
            "regions": [dict(region) for region in self.regions],
            "source": self.source,
            "notes": self.notes,
            "relevance_score": self.relevance_score,
            "priority": self.priority,
            "ai_reason": self.ai_reason,
            "sort_order": self.sort_order,
        }


def normalize_plain_text(value: str, *, max_length: int = 500) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(char) == "Cc" for char in normalized):
        raise KeywordNormalizationError("control")
    normalized = " ".join(normalized.split()).strip()
    if not normalized or len(normalized) > max_length:
        raise KeywordNormalizationError("length")
    matching = normalized.casefold()
    if len(matching) > max_length:
        raise KeywordNormalizationError("length")
    return normalized, matching


def _optional_plain_text(
    item: dict[str, object], key: str, *, max_length: int
) -> tuple[str | None, str | None]:
    raw = item.get(key)
    if raw is None or raw == "":
        return None, None
    if not isinstance(raw, str):
        raise KeywordNormalizationError("shape")
    return normalize_plain_text(raw, max_length=max_length)


def normalize_region_entries(value: object) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, (list, tuple)) or len(value) > 20:
        raise KeywordNormalizationError("regions_shape")
    valid_levels = set(KeywordItemFields.RegionLevel.values)
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if isinstance(raw, str):
            name, matching_name = normalize_plain_text(raw, max_length=200)
            entry: dict[str, Any] = {"code": "", "name": name, "level": "custom"}
            identity = f"name:{matching_name}"
        elif isinstance(raw, dict):
            if set(raw) - {"code", "name", "level", "path"}:
                raise KeywordNormalizationError("regions_fields")
            code = raw.get("code", "")
            name = raw.get("name")
            level = raw.get("level", "custom")
            if not isinstance(code, str) or len(code.strip()) > 32:
                raise KeywordNormalizationError("region_code")
            if not isinstance(name, str) or not isinstance(level, str):
                raise KeywordNormalizationError("regions_shape")
            if level not in valid_levels:
                raise KeywordNormalizationError("region_level")
            normalized_name, matching_name = normalize_plain_text(name, max_length=200)
            normalized_code = code.strip()
            entry = {"code": normalized_code, "name": normalized_name, "level": level}
            path = raw.get("path")
            if path is not None:
                if not isinstance(path, list) or len(path) > 5:
                    raise KeywordNormalizationError("region_path")
                normalized_path = []
                for node in path:
                    if not isinstance(node, dict) or set(node) - {"code", "name"}:
                        raise KeywordNormalizationError("region_path")
                    node_code = node.get("code")
                    node_name = node.get("name")
                    if not isinstance(node_code, str) or not isinstance(node_name, str):
                        raise KeywordNormalizationError("region_path")
                    normalized_node_name, _ = normalize_plain_text(node_name, max_length=200)
                    if not node_code.strip() or len(node_code.strip()) > 32:
                        raise KeywordNormalizationError("region_path")
                    normalized_path.append(
                        {"code": node_code.strip(), "name": normalized_node_name}
                    )
                entry["path"] = normalized_path
            identity = f"code:{normalized_code}" if normalized_code else f"name:{matching_name}"
        else:
            raise KeywordNormalizationError("regions_shape")
        if identity in seen:
            raise KeywordNormalizationError("regions_duplicate")
        seen.add(identity)
        output.append(entry)
    return output


def _regions_matching_key(regions: list[dict[str, Any]]) -> str:
    if not regions:
        return ""
    encoded = json.dumps(regions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"regions:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def normalize_keyword_items(items: list[dict[str, object]]) -> list[NormalizedKeyword]:
    result: list[NormalizedKeyword] = []
    seen: set[tuple[str, str]] = set()
    valid_structure = set(KeywordItemFields.StructureType.values)
    valid_region_levels = set(KeywordItemFields.RegionLevel.values)
    valid_intents = set(KeywordItemFields.SearchIntent.values)
    valid_priorities = set(KeywordItemFields.Priority.values)
    for index, item in enumerate(items):
        raw_text = item.get("text")
        structure_type = item.get("structure_type")
        is_regional = item.get("is_regional", False)
        if not isinstance(raw_text, str) or structure_type not in valid_structure:
            raise KeywordNormalizationError("shape")
        if not isinstance(is_regional, bool):
            raise KeywordNormalizationError("shape")
        text, matching_text = normalize_plain_text(raw_text)
        raw_level = item.get("region_level", "") or ""
        raw_region = item.get("region_text", "") or ""
        if not isinstance(raw_level, str) or not isinstance(raw_region, str):
            raise KeywordNormalizationError("shape")
        raw_regions = item.get("regions", [])
        regions = normalize_region_entries(raw_regions)
        if regions:
            if not is_regional:
                raise KeywordNormalizationError("region_shape")
            region_level = str(regions[0]["level"])
            region_text = str(regions[0]["name"])
            region_matching_key = _regions_matching_key(regions)
        elif is_regional:
            if raw_level and raw_level not in valid_region_levels:
                raise KeywordNormalizationError("region_level")
            region_text, region_match = normalize_plain_text(raw_region, max_length=200)
            region_level = raw_level
            region_matching_key = f"{region_level or 'region'}:{region_match}"
            regions = [
                {
                    "code": "",
                    "name": region_text,
                    "level": region_level or "custom",
                }
            ]
        else:
            if raw_level or raw_region:
                raise KeywordNormalizationError("region_shape")
            region_level = ""
            region_text = ""
            region_matching_key = ""
        base_keyword_text, base_keyword_matching = _optional_plain_text(
            item, "base_keyword_text", max_length=500
        )
        business_category, _ = _optional_plain_text(item, "business_category", max_length=128)
        search_intent = item.get("search_intent")
        if search_intent == "":
            search_intent = None
        if search_intent is not None and search_intent not in valid_intents:
            raise KeywordNormalizationError("search_intent")
        raw_intents = item.get("search_intents", [])
        if raw_intents in (None, []):
            raw_intents = [search_intent] if search_intent else []
        try:
            search_intents = normalize_intents(raw_intents) if raw_intents else ()
        except ValueError as exc:
            raise KeywordNormalizationError(str(exc)) from exc
        source = item.get("source", KeywordItemFields.Source.LEGACY)
        if source not in KeywordItemFields.Source.values:
            raise KeywordNormalizationError("source")
        notes, _ = _optional_plain_text(item, "notes", max_length=1000)
        relevance_score = item.get("relevance_score")
        if relevance_score is not None and (
            type(relevance_score) is not int or not 0 <= relevance_score <= 100
        ):
            raise KeywordNormalizationError("relevance_score")
        priority = item.get("priority")
        if priority == "":
            priority = None
        if priority is not None and priority not in valid_priorities:
            raise KeywordNormalizationError("priority")
        ai_reason, _ = _optional_plain_text(item, "ai_reason", max_length=1000)
        duplicate_key = (matching_text, region_matching_key)
        if duplicate_key in seen:
            raise KeywordNormalizationError("duplicate")
        seen.add(duplicate_key)
        result.append(
            NormalizedKeyword(
                text=text,
                matching_text=matching_text,
                structure_type=str(structure_type),
                is_regional=is_regional,
                region_level=region_level,
                region_text=region_text,
                region_matching_key=region_matching_key,
                base_keyword_text=base_keyword_text,
                base_keyword_matching=base_keyword_matching,
                business_category=business_category,
                search_intent=str(search_intent) if search_intent is not None else None,
                search_intents=search_intents,
                regions=tuple(regions),
                source=str(source),
                notes=notes or "",
                relevance_score=relevance_score,
                priority=str(priority) if priority is not None else None,
                ai_reason=ai_reason,
                sort_order=index,
            )
        )
    return result


def keyword_content_digest(*, subject_version_id, items: list[NormalizedKeyword]) -> str:
    payload = {
        "subject_version_id": str(subject_version_id),
        "items": [item.semantic_payload() for item in items],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def resolve_base_keyword_indexes(items: list[NormalizedKeyword]) -> dict[int, int]:
    resolved: dict[int, int] = {}
    for index, item in enumerate(items):
        if item.base_keyword_matching is None:
            continue
        candidates = [
            candidate_index
            for candidate_index, candidate in enumerate(items)
            if candidate.matching_text == item.base_keyword_matching
        ]
        if len(candidates) != 1:
            raise KeywordNormalizationError(
                "base_keyword_missing" if not candidates else "base_keyword_ambiguous"
            )
        target = candidates[0]
        if target == index:
            raise KeywordNormalizationError("base_keyword_self")
        resolved[index] = target

    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(index: int) -> None:
        if index in visited:
            return
        if index in visiting:
            raise KeywordNormalizationError("base_keyword_cycle")
        visiting.add(index)
        target = resolved.get(index)
        if target is not None:
            visit(target)
        visiting.remove(index)
        visited.add(index)

    for index in resolved:
        visit(index)
    return resolved


def normalize_generated_keyword_items(
    items: list[dict[str, object]], *, target_count: int
) -> list[NormalizedKeyword]:
    normalized = normalize_keyword_items(items)
    if not normalized or len(normalized) > target_count:
        raise KeywordNormalizationError("generated_count")
    for item in normalized:
        if (
            item.business_category is None
            or (item.search_intent is None and not item.search_intents)
            or item.relevance_score is None
            or item.priority is None
            or item.ai_reason is None
        ):
            raise KeywordNormalizationError("generated_metadata")
    resolve_base_keyword_indexes(normalized)
    return normalized
