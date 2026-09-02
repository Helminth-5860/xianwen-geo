from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable

_IDENTITY_KEYS = (
    "official_name",
    "name",
    "brand_name",
    "alias",
    "subject_aliases",
    "aliases",
)
_SPLIT_PATTERN = re.compile(r"[\r\n,，;；、|]+")


def _text_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return
        if candidate[:1] in {"[", "{"}:
            try:
                yield from _text_values(json.loads(candidate))
                return
            except (TypeError, ValueError):
                pass
        yield from (part for part in _SPLIT_PATTERN.split(candidate) if part.strip())
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _text_values(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _text_values(item)


def normalized_identity_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def subject_identity_terms(subject_values: object) -> tuple[str, ...]:
    if not isinstance(subject_values, dict):
        return ()
    output: list[str] = []
    seen: set[str] = set()
    for key in _IDENTITY_KEYS:
        for raw in _text_values(subject_values.get(key)):
            value = " ".join(raw.split())
            matching = normalized_identity_text(value)
            if len(matching) < 2 or matching in seen:
                continue
            seen.add(matching)
            output.append(value)
    return tuple(output)


def matching_subject_identity(text: object, subject_values: object) -> str | None:
    matching_text = normalized_identity_text(text)
    if not matching_text:
        return None
    for term in subject_identity_terms(subject_values):
        if normalized_identity_text(term) in matching_text:
            return term
    return None
