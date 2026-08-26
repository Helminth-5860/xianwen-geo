from types import SimpleNamespace

import pytest

from apps.website_audits.semantic_context import SemanticAuditContext
from apps.website_audits.semantic_provider import execute_semantic_provider
from apps.website_audits.semantic_services import _semantic_schema_error_code
from apps.website_audits.semantic_validation import (
    SemanticAuditSchemaError,
    ValidatedSemanticAudit,
)


_SCORE_PAYLOAD = {
    "entity_clarity": 80,
    "fact_density": 70,
    "citation_readiness": 75,
    "topic_coverage": 65,
    "credibility": 72,
    "answer_readiness": 60,
}


def _context():
    return SemanticAuditContext(
        subject={"official_name": "示例公司"},
        keywords=[],
        questions=[],
        pages=[{"page_id": "p1"}],
        technical_evidence={},
        allowed_page_ids=frozenset({"p1"}),
        allowed_question_ids=frozenset(),
        page_url_by_id={"p1": "https://example.com/"},
        page_text_by_id={"p1": "示例公司提供公开服务。"},
    )


def _response(content, request_id, *, tokens, latency):
    return SimpleNamespace(
        output=SimpleNamespace(content=content),
        provider_request_id=request_id,
        usage=SimpleNamespace(
            input_tokens=tokens,
            output_tokens=tokens + 1,
            total_tokens=tokens * 2 + 1,
        ),
        timing=SimpleNamespace(latency_ms=latency),
    )


def _runtime():
    return SimpleNamespace(
        provider_key="deepseek",
        provider_model_id="deepseek-v4-flash",
        version=2,
        timeout_seconds=120,
    )


def _patch_common(monkeypatch):
    monkeypatch.setattr(
        "apps.website_audits.semantic_provider.get_capability_runtime_snapshot",
        lambda **_kwargs: _runtime(),
    )
    monkeypatch.setattr(
        "apps.website_audits.semantic_provider.prepare_provider_pages",
        lambda _pages: (
            [{"page_id": "p1", "text": "示例公司提供公开服务。"}],
            {
                "s1": {
                    "page_id": "p1",
                    "url": "https://example.com/",
                    "text": "示例公司提供公开服务。",
                }
            },
        ),
    )


def test_semantic_provider_repairs_one_invalid_schema(monkeypatch):
    _patch_common(monkeypatch)
    responses = [
        _response({"attempt": 1}, "provider-1", tokens=10, latency=100),
        _response({"attempt": 2}, "provider-2", tokens=20, latency=200),
    ]
    requests = []

    def fake_invoke(_self, request):
        requests.append(request)
        return responses.pop(0)

    validation_calls = []

    def fake_validate(content, **_kwargs):
        validation_calls.append(content)
        if len(validation_calls) == 1:
            raise SemanticAuditSchemaError("derived_questions_invalid")
        return ValidatedSemanticAudit(
            summary="修复后通过",
            scores=dict(_SCORE_PAYLOAD),
            result={"question_assessments": []},
        )

    monkeypatch.setattr(
        "apps.website_audits.semantic_provider.WebsiteAuditSemanticAdapter.invoke",
        fake_invoke,
    )
    monkeypatch.setattr(
        "apps.website_audits.semantic_provider.validate_semantic_audit_output",
        fake_validate,
    )

    result = execute_semantic_provider(audit_id="audit-1", context=_context())

    assert len(requests) == 2
    assert requests[0].payload.user_payload["task"] == "deep_geo_website_semantic_audit"
    assert requests[1].payload.user_payload["task"] == "repair_deep_geo_website_semantic_audit"
    assert requests[1].payload.user_payload["validation_error"] == "derived_questions_invalid"
    assert requests[1].payload.user_payload["previous_output"] == {"attempt": 1}
    assert result.provider_request_id == "provider-2"
    assert result.input_tokens == 30
    assert result.output_tokens == 32
    assert result.total_tokens == 62
    assert result.latency_ms == 300


def test_semantic_provider_stops_after_one_repair_attempt(monkeypatch):
    _patch_common(monkeypatch)
    responses = [
        _response({"attempt": 1}, "provider-1", tokens=10, latency=100),
        _response({"attempt": 2}, "provider-2", tokens=20, latency=200),
    ]
    requests = []

    def fake_invoke(_self, request):
        requests.append(request)
        return responses.pop(0)

    monkeypatch.setattr(
        "apps.website_audits.semantic_provider.WebsiteAuditSemanticAdapter.invoke",
        fake_invoke,
    )
    monkeypatch.setattr(
        "apps.website_audits.semantic_provider.validate_semantic_audit_output",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SemanticAuditSchemaError("invented_evidence_page_id")
        ),
    )

    with pytest.raises(SemanticAuditSchemaError, match="invented_evidence_page_id"):
        execute_semantic_provider(audit_id="audit-2", context=_context())

    assert len(requests) == 2


def test_semantic_schema_error_code_keeps_diagnostic_reason():
    code = _semantic_schema_error_code(
        SemanticAuditSchemaError("invented_evidence_page_id")
    )
    assert code == "SEMANTIC_SCHEMA_INVENTED_EVIDENCE_PAGE_ID"
    assert len(code) <= 64
