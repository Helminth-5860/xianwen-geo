import re
import unicodedata

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class QuestionCatalogNormalizationError(ValueError):
    pass


def normalize_catalog_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not KEY_PATTERN.fullmatch(normalized):
        raise QuestionCatalogNormalizationError("key")
    return normalized


def normalize_catalog_text(value: str, *, maximum: int, required: bool) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(char) == "Cc" for char in normalized):
        raise QuestionCatalogNormalizationError("control")
    normalized = " ".join(normalized.split()).strip()
    if (required and not normalized) or len(normalized) > maximum:
        raise QuestionCatalogNormalizationError("length")
    matching = normalized.casefold()
    if len(matching) > maximum:
        raise QuestionCatalogNormalizationError("length")
    return normalized, matching
