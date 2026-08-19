from __future__ import annotations

import pytest

from apps.ai.detection import DetectionCitation, DetectionOutput
from apps.geo.citations import normalize_detection_citations
from apps.geo.models import ModelResponseCitation
from apps.web_sources.exceptions import WebSourceUrlNotAllowed


def test_structured_citation_is_canonicalized_and_safe(monkeypatch):
    monkeypatch.setattr(
        "apps.geo.citations.resolve_and_validate",
        lambda host, port: ("93.184.216.34",),
    )
    output = DetectionOutput(
        provider_model_id="deepseek-chat",
        raw_text="answer",
        citations=(
            DetectionCitation(
                title=" Example ",
                url="https://example.com/path?q=1",
                source_name=None,
                quoted_text=" quote ",
                provider_rank=1,
            ),
        ),
    )

    rows = normalize_detection_citations(output)

    assert len(rows) == 1
    row = rows[0]
    assert row.canonical_url == "https://example.com/path?q=1"
    assert row.source_host == "example.com"
    assert row.source_name == "example.com"
    assert row.url_status == ModelResponseCitation.UrlStatus.SAFE
    assert row.source_category == ModelResponseCitation.SourceCategory.WEB
    assert row.extraction_method == ModelResponseCitation.ExtractionMethod.PROVIDER


def test_blocked_url_is_fail_closed_without_persistable_url(monkeypatch):
    def blocked(host, port):
        raise WebSourceUrlNotAllowed

    monkeypatch.setattr("apps.geo.citations.resolve_and_validate", blocked)
    output = DetectionOutput(
        provider_model_id="deepseek-chat",
        raw_text="answer",
        citations=(DetectionCitation(url="http://127.0.0.1/private"),),
    )

    row = normalize_detection_citations(output)[0]

    assert row.url_status == ModelResponseCitation.UrlStatus.BLOCKED
    assert row.canonical_url == ""
    assert row.source_host == ""
    assert row.source_category == ModelResponseCitation.SourceCategory.UNKNOWN


def test_raw_text_url_fallback_is_bounded_and_deduplicated(monkeypatch):
    monkeypatch.setattr(
        "apps.geo.citations.resolve_and_validate",
        lambda host, port: ("93.184.216.34",),
    )
    output = DetectionOutput(
        provider_model_id="deepseek-chat",
        raw_text="See https://example.com/a and https://example.com/a.",
    )

    rows = normalize_detection_citations(output)

    assert len(rows) == 1
    assert rows[0].canonical_url == "https://example.com/a"
    assert rows[0].extraction_method == ModelResponseCitation.ExtractionMethod.RAW_TEXT


def test_model_response_citation_python_immutability():
    citation = ModelResponseCitation(
        sort_order=0,
        url_status=ModelResponseCitation.UrlStatus.MISSING,
        extraction_method=ModelResponseCitation.ExtractionMethod.PROVIDER,
    )
    citation._state.adding = False
    with pytest.raises(TypeError):
        citation.save()
    with pytest.raises(TypeError):
        citation.delete()
