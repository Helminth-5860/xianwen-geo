from __future__ import annotations

import re
from typing import Any

_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])\s*")


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _split_long_fragment(fragment: str, *, maximum_chars: int) -> list[str]:
    rows: list[str] = []
    remaining = fragment.strip()
    while len(remaining) > maximum_chars:
        window = remaining[: maximum_chars + 1]
        cut = max(
            window.rfind("。"),
            window.rfind("！"),
            window.rfind("？"),
            window.rfind("；"),
            window.rfind("，"),
            window.rfind(","),
            window.rfind(" "),
        )
        if cut < maximum_chars // 2:
            cut = maximum_chars
        else:
            cut += 1
        piece = remaining[:cut].strip()
        if piece:
            rows.append(piece)
        remaining = remaining[cut:].strip()
    if remaining:
        rows.append(remaining)
    return rows


def build_evidence_spans(
    *,
    page_id: str,
    text: str,
    maximum_chars: int = 280,
    maximum_spans: int = 30,
) -> list[dict[str, str]]:
    """Build deterministic, bounded citation spans from one crawled page.

    The model may select a span id, but it never supplies the quoted source text.
    The backend therefore remains the authority for the final excerpt.
    """

    normalized = _normalize_text(text)
    if not page_id or not normalized or maximum_chars < 80 or maximum_spans < 1:
        return []

    fragments: list[str] = []
    for sentence in _SENTENCE_BOUNDARY.split(normalized):
        sentence = sentence.strip()
        if not sentence:
            continue
        fragments.extend(_split_long_fragment(sentence, maximum_chars=maximum_chars))

    spans: list[str] = []
    buffer = ""
    for fragment in fragments:
        candidate = f"{buffer} {fragment}".strip() if buffer else fragment
        if len(candidate) <= maximum_chars:
            buffer = candidate
            continue
        if buffer:
            spans.append(buffer)
            if len(spans) >= maximum_spans:
                break
        buffer = fragment
    if len(spans) < maximum_spans and buffer:
        spans.append(buffer)

    return [
        {
            "span_id": f"{page_id}:s{index:02d}",
            "text": span,
        }
        for index, span in enumerate(spans[:maximum_spans], start=1)
        if span
    ]


def prepare_provider_pages(
    pages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Replace free-form page text with deterministic evidence spans for the model."""

    provider_pages: list[dict[str, Any]] = []
    span_by_id: dict[str, dict[str, str]] = {}

    for raw_page in pages:
        page_id = str(raw_page.get("page_id", "")).strip()
        url = str(raw_page.get("url", "")).strip()
        text = str(raw_page.get("text", ""))
        if not page_id or not url or not text.strip():
            continue

        spans = build_evidence_spans(page_id=page_id, text=text)
        if not spans:
            continue

        page = {key: value for key, value in raw_page.items() if key != "text"}
        page["evidence_spans"] = spans
        provider_pages.append(page)

        for span in spans:
            span_id = span["span_id"]
            span_by_id[span_id] = {
                "page_id": page_id,
                "url": url,
                "text": span["text"],
            }

    return provider_pages, span_by_id
