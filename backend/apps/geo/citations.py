from __future__ import annotations

import re
from dataclasses import dataclass

from apps.ai.detection import DetectionCitation, DetectionOutput
from apps.web_sources.exceptions import (
    WebSourceTransientError,
    WebSourceUrlInvalid,
    WebSourceUrlNotAllowed,
)
from apps.web_sources.url_security import canonicalize_url, resolve_and_validate

from .models import ModelResponse, ModelResponseCitation

_URL_RE = re.compile(r'https?://[^\s<>{}\[\]"\\]+', re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_TRAILING_URL_PUNCTUATION = ".,;:!?，。；：！？)]}>\"'"
MAX_CITATIONS = 50


@dataclass(frozen=True)
class NormalizedCitation:
    title: str
    canonical_url: str
    source_name: str
    source_host: str
    quoted_text: str
    provider_rank: int | None
    url_status: str
    source_category: str
    extraction_method: str


def _clean_text(value: str | None, *, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return _CONTROL_RE.sub(" ", value).strip()[:maximum]


def _raw_text_citations(raw_text: str) -> tuple[DetectionCitation, ...]:
    values: list[DetectionCitation] = []
    for match in _URL_RE.finditer(raw_text):
        candidate = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        if not candidate:
            continue
        values.append(DetectionCitation(url=candidate))
        if len(values) >= MAX_CITATIONS:
            break
    return tuple(values)


def _safe_url(raw_url: str | None) -> tuple[str, str, str]:
    if not raw_url:
        return "", "", ModelResponseCitation.UrlStatus.MISSING
    try:
        canonical = canonicalize_url(raw_url)
        resolve_and_validate(canonical.host, canonical.port)
    except WebSourceUrlInvalid:
        return "", "", ModelResponseCitation.UrlStatus.INVALID
    except WebSourceUrlNotAllowed:
        return "", "", ModelResponseCitation.UrlStatus.BLOCKED
    except WebSourceTransientError:
        return "", "", ModelResponseCitation.UrlStatus.UNRESOLVED
    return canonical.value, canonical.host, ModelResponseCitation.UrlStatus.SAFE


def normalize_detection_citations(output: DetectionOutput) -> tuple[NormalizedCitation, ...]:
    if output.citations:
        candidates = tuple(
            (citation, ModelResponseCitation.ExtractionMethod.PROVIDER)
            for citation in output.citations
        )
    else:
        candidates = tuple(
            (citation, ModelResponseCitation.ExtractionMethod.RAW_TEXT)
            for citation in _raw_text_citations(output.raw_text)
        )

    normalized: list[NormalizedCitation] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for citation, extraction_method in candidates[:MAX_CITATIONS]:
        title = _clean_text(citation.title, maximum=500)
        source_name = _clean_text(citation.source_name, maximum=500)
        quoted_text = _clean_text(citation.quoted_text, maximum=4000)
        provider_rank = (
            citation.provider_rank
            if type(citation.provider_rank) is int and citation.provider_rank >= 1
            else None
        )
        if not any((citation.url, title, source_name, quoted_text, provider_rank)):
            continue

        canonical_url, source_host, url_status = _safe_url(citation.url)
        if not source_name and url_status == ModelResponseCitation.UrlStatus.SAFE:
            source_name = source_host

        dedupe_key = (
            canonical_url,
            url_status,
            title.casefold(),
            source_name.casefold(),
            quoted_text,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        normalized.append(
            NormalizedCitation(
                title=title,
                canonical_url=canonical_url,
                source_name=source_name,
                source_host=source_host,
                quoted_text=quoted_text,
                provider_rank=provider_rank,
                url_status=url_status,
                source_category=(
                    ModelResponseCitation.SourceCategory.WEB
                    if url_status == ModelResponseCitation.UrlStatus.SAFE
                    else ModelResponseCitation.SourceCategory.UNKNOWN
                ),
                extraction_method=extraction_method,
            )
        )

    return tuple(normalized)


def persist_response_citations(
    *,
    model_response: ModelResponse,
    citations: tuple[NormalizedCitation, ...],
) -> None:
    if not citations:
        return
    ModelResponseCitation.objects.bulk_create(
        [
            ModelResponseCitation(
                model_response=model_response,
                sort_order=index,
                title=citation.title,
                canonical_url=citation.canonical_url,
                source_name=citation.source_name,
                source_host=citation.source_host,
                quoted_text=citation.quoted_text,
                provider_rank=citation.provider_rank,
                url_status=citation.url_status,
                source_category=citation.source_category,
                extraction_method=citation.extraction_method,
            )
            for index, citation in enumerate(citations)
        ]
    )
