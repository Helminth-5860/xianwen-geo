from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.search_discovery.subject_context import SubjectSearchContext
from apps.web_sources.exceptions import WebSourceError
from apps.web_sources.http_transport import fetch_url
from apps.web_sources.parser import parse_response

from .classifier import CATEGORY_TERMS, REBUTTAL_TERMS


@dataclass(frozen=True)
class VerificationResult:
    succeeded: bool
    excerpt: str
    error_code: str


def _evidence_excerpt(text: str, context: SubjectSearchContext) -> str:
    maximum = int(getattr(settings, "NEGATIVE_INDEX_VERIFICATION_TEXT_CHARS", 12000))
    if len(text) <= maximum:
        return text
    lowered = text.casefold()
    tokens = [value for value in context.anchors if len(value) >= 2]
    tokens.extend(term for terms in CATEGORY_TERMS.values() for term in terms)
    tokens.extend(REBUTTAL_TERMS)
    positions = [lowered.find(token.casefold()) for token in tokens]
    positions = [position for position in positions if position >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - maximum // 3)
    end = min(len(text), start + maximum)
    return text[start:end]


def verify_candidate(record: dict, context: SubjectSearchContext) -> VerificationResult:
    try:
        fetched = fetch_url(record["original_url"])
        media_type = fetched.content_type.split(";", 1)[0].strip().lower()
        _title, text, _charset, _digest = parse_response(body=fetched.body, media_type=media_type, content_type=fetched.content_type)
        if not text.strip():
            return VerificationResult(False, "", "NEGATIVE_VERIFICATION_EMPTY")
        return VerificationResult(True, _evidence_excerpt(text, context), "")
    except WebSourceError as exc:
        return VerificationResult(False, "", exc.code)
    except Exception:
        return VerificationResult(False, "", "NEGATIVE_VERIFICATION_FAILED")
