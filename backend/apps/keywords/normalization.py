import hashlib
import json
import unicodedata
from dataclasses import dataclass

from .models import KeywordItemFields


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


def normalize_keyword_items(items: list[dict[str, object]]) -> list[NormalizedKeyword]:
    result: list[NormalizedKeyword] = []
    seen: set[tuple[str, str]] = set()
    valid_structure = set(KeywordItemFields.StructureType.values)
    valid_region_levels = set(KeywordItemFields.RegionLevel.values)
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
        if is_regional:
            if raw_level and raw_level not in valid_region_levels:
                raise KeywordNormalizationError("region_level")
            region_text, region_match = normalize_plain_text(raw_region, max_length=200)
            region_level = raw_level
            region_matching_key = f"{region_level or 'region'}:{region_match}"
        else:
            if raw_level or raw_region:
                raise KeywordNormalizationError("region_shape")
            region_level = ""
            region_text = ""
            region_matching_key = ""
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
