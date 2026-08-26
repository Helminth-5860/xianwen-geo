from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_SCORE_KEYS = (
    "entity_clarity",
    "fact_density",
    "citation_readiness",
    "topic_coverage",
    "credibility",
    "answer_readiness",
)
_ALLOWED_SEVERITIES = {"high", "medium", "low"}
_ALLOWED_QUESTION_STATUSES = {"answered", "partial", "missing"}
_ALLOWED_QUESTION_SOURCES = {"question_bank", "derived"}
_ALLOWED_ENTITY_STATUS = {"clear", "partial", "unclear"}
_ALLOWED_IMPORTANCE = {"high", "medium", "low"}


class SemanticAuditSchemaError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedSemanticAudit:
    summary: str
    scores: dict[str, int]
    result: dict[str, Any]


def _text(value: object, *, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        if required:
            raise SemanticAuditSchemaError("text_required")
        return ""
    normalized = " ".join(value.split())
    if required and not normalized:
        raise SemanticAuditSchemaError("text_required")
    return normalized[:maximum]


def _score(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 100:
        raise SemanticAuditSchemaError("score_out_of_range")
    return value


def _string_list(value: object, *, maximum_items: int, maximum_chars: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise SemanticAuditSchemaError("list_invalid")
    output: list[str] = []
    for item in value:
        text = _text(item, maximum=maximum_chars)
        if text not in output:
            output.append(text)
    return output


def _evidence_pages(
    value: object,
    *,
    allowed_page_ids: frozenset[str],
    page_url_by_id: dict[str, str],
) -> tuple[list[str], list[str]]:
    if value is None:
        raise SemanticAuditSchemaError("evidence_page_ids_required")
    page_ids = _string_list(value, maximum_items=20, maximum_chars=100)
    if any(page_id not in allowed_page_ids for page_id in page_ids):
        raise SemanticAuditSchemaError("invented_evidence_page_id")
    try:
        urls = [page_url_by_id[page_id] for page_id in page_ids]
    except KeyError as exc:
        raise SemanticAuditSchemaError("evidence_page_mapping_missing") from exc
    return page_ids, urls


def _normalized_evidence_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def validate_semantic_audit_output(
    payload: object,
    *,
    allowed_page_ids: frozenset[str],
    allowed_question_ids: frozenset[str],
    page_url_by_id: dict[str, str],
    page_text_by_id: dict[str, str] | None = None,
    evidence_span_by_id: dict[str, dict[str, str]] | None = None,
) -> ValidatedSemanticAudit:
    if not isinstance(payload, dict):
        raise SemanticAuditSchemaError("root_not_object")
    if not allowed_page_ids or set(page_url_by_id) != set(allowed_page_ids):
        raise SemanticAuditSchemaError("page_evidence_contract_invalid")

    raw_scores = payload.get("scores")
    if not isinstance(raw_scores, dict) or set(raw_scores) != set(_SCORE_KEYS):
        raise SemanticAuditSchemaError("scores_invalid")
    scores = {key: _score(raw_scores[key]) for key in _SCORE_KEYS}
    summary = _text(payload.get("summary"), maximum=1200)

    raw_entity = payload.get("entity_assessment")
    if not isinstance(raw_entity, dict):
        raise SemanticAuditSchemaError("entity_assessment_invalid")
    entity_status = _text(raw_entity.get("status"), maximum=20)
    if entity_status not in _ALLOWED_ENTITY_STATUS:
        raise SemanticAuditSchemaError("entity_status_invalid")
    recognized_entities = raw_entity.get("recognized_entities")
    if not isinstance(recognized_entities, list) or len(recognized_entities) > 30:
        raise SemanticAuditSchemaError("recognized_entities_invalid")
    normalized_entities: list[dict[str, object]] = []
    for row in recognized_entities:
        if not isinstance(row, dict):
            raise SemanticAuditSchemaError("entity_row_invalid")
        page_ids, urls = _evidence_pages(
            row.get("evidence_page_ids"),
            allowed_page_ids=allowed_page_ids,
            page_url_by_id=page_url_by_id,
        )
        normalized_entities.append(
            {
                "name": _text(row.get("name"), maximum=300),
                "type": _text(row.get("type"), maximum=50),
                "evidence_page_ids": page_ids,
                "evidence_urls": urls,
            }
        )

    raw_conflicts = raw_entity.get("conflicts", [])
    if not isinstance(raw_conflicts, list) or len(raw_conflicts) > 20:
        raise SemanticAuditSchemaError("entity_conflicts_invalid")
    conflicts: list[dict[str, object]] = []
    for row in raw_conflicts:
        if not isinstance(row, dict):
            raise SemanticAuditSchemaError("entity_conflict_row_invalid")
        page_ids, urls = _evidence_pages(
            row.get("evidence_page_ids"),
            allowed_page_ids=allowed_page_ids,
            page_url_by_id=page_url_by_id,
        )
        conflicts.append(
            {
                "description": _text(row.get("description"), maximum=800),
                "evidence_page_ids": page_ids,
                "evidence_urls": urls,
            }
        )

    raw_findings = payload.get("content_findings")
    if not isinstance(raw_findings, list) or len(raw_findings) > 30:
        raise SemanticAuditSchemaError("content_findings_invalid")
    findings: list[dict[str, object]] = []
    for row in raw_findings:
        if not isinstance(row, dict):
            raise SemanticAuditSchemaError("content_finding_row_invalid")
        severity = _text(row.get("severity"), maximum=20)
        if severity not in _ALLOWED_SEVERITIES:
            raise SemanticAuditSchemaError("content_finding_severity_invalid")
        page_ids, urls = _evidence_pages(
            row.get("evidence_page_ids"),
            allowed_page_ids=allowed_page_ids,
            page_url_by_id=page_url_by_id,
        )
        findings.append(
            {
                "key": _text(row.get("key"), maximum=80),
                "severity": severity,
                "title": _text(row.get("title"), maximum=300),
                "reason": _text(row.get("reason"), maximum=1200),
                "evidence_page_ids": page_ids,
                "evidence_urls": urls,
                "recommendation": _text(row.get("recommendation"), maximum=1200),
            }
        )

    raw_questions = payload.get("question_assessments")
    if not isinstance(raw_questions, list) or len(raw_questions) > 50:
        raise SemanticAuditSchemaError("question_assessments_invalid")
    questions: list[dict[str, object]] = []
    seen_question_ids: set[str] = set()
    for row in raw_questions:
        if not isinstance(row, dict):
            raise SemanticAuditSchemaError("question_row_invalid")
        source = _text(row.get("source"), maximum=20)
        if source not in _ALLOWED_QUESTION_SOURCES:
            raise SemanticAuditSchemaError("question_source_invalid")
        question_id_raw = row.get("question_id")
        question_id = "" if question_id_raw is None else _text(question_id_raw, maximum=100)
        if source == "question_bank":
            if not question_id or question_id not in allowed_question_ids or question_id in seen_question_ids:
                raise SemanticAuditSchemaError("question_id_invalid")
            seen_question_ids.add(question_id)
        elif question_id:
            raise SemanticAuditSchemaError("derived_question_id_forbidden")
        status = _text(row.get("status"), maximum=20)
        if status not in _ALLOWED_QUESTION_STATUSES:
            raise SemanticAuditSchemaError("question_status_invalid")
        coverage = _score(row.get("coverage_score"))
        missing_points = _string_list(
            row.get("missing_points", []),
            maximum_items=12,
            maximum_chars=500,
        )
        page_ids, urls = _evidence_pages(
            row.get("evidence_page_ids"),
            allowed_page_ids=allowed_page_ids,
            page_url_by_id=page_url_by_id,
        )
        questions.append(
            {
                "source": source,
                "question_id": question_id or None,
                "question": _text(row.get("question"), maximum=1000),
                "coverage_score": coverage,
                "status": status,
                "evidence_page_ids": page_ids,
                "evidence_urls": urls,
                "answer_summary": _text(row.get("answer_summary", ""), maximum=1000, required=False),
                "missing_points": missing_points,
                "recommendation": _text(row.get("recommendation"), maximum=1000),
            }
        )
    if allowed_question_ids and seen_question_ids != set(allowed_question_ids):
        raise SemanticAuditSchemaError("question_bank_coverage_incomplete")
    if not allowed_question_ids:
        if not 6 <= len(questions) <= 20 or any(row["source"] != "derived" for row in questions):
            raise SemanticAuditSchemaError("derived_questions_invalid")

    raw_gaps = payload.get("topic_gaps")
    if not isinstance(raw_gaps, list) or len(raw_gaps) > 25:
        raise SemanticAuditSchemaError("topic_gaps_invalid")
    topic_gaps: list[dict[str, object]] = []
    for row in raw_gaps:
        if not isinstance(row, dict):
            raise SemanticAuditSchemaError("topic_gap_row_invalid")
        importance = _text(row.get("importance"), maximum=20)
        if importance not in _ALLOWED_IMPORTANCE:
            raise SemanticAuditSchemaError("topic_gap_importance_invalid")
        page_ids, urls = _evidence_pages(
            row.get("evidence_page_ids"),
            allowed_page_ids=allowed_page_ids,
            page_url_by_id=page_url_by_id,
        )
        topic_gaps.append(
            {
                "topic": _text(row.get("topic"), maximum=300),
                "importance": importance,
                "reason": _text(row.get("reason"), maximum=1000),
                "suggested_content": _text(row.get("suggested_content"), maximum=1200),
                "evidence_page_ids": page_ids,
                "evidence_urls": urls,
            }
        )

    raw_passages = payload.get("citeable_passages")
    if not isinstance(raw_passages, list) or len(raw_passages) > 25:
        raise SemanticAuditSchemaError("citeable_passages_invalid")
    passages: list[dict[str, object]] = []

    if evidence_span_by_id is not None:
        if not evidence_span_by_id:
            raise SemanticAuditSchemaError("evidence_span_contract_invalid")
        for row in raw_passages:
            if not isinstance(row, dict):
                raise SemanticAuditSchemaError("citeable_passage_row_invalid")
            span_id = _text(row.get("evidence_span_id"), maximum=120)
            span = evidence_span_by_id.get(span_id)
            if not isinstance(span, dict):
                raise SemanticAuditSchemaError("invented_evidence_span_id")
            page_id = _text(span.get("page_id"), maximum=100)
            url = _text(span.get("url"), maximum=4096)
            excerpt = _text(span.get("text"), maximum=300)
            if page_id not in allowed_page_ids:
                raise SemanticAuditSchemaError("evidence_span_page_invalid")
            if page_url_by_id.get(page_id) != url:
                raise SemanticAuditSchemaError("evidence_span_url_mapping_invalid")
            passages.append(
                {
                    "evidence_span_id": span_id,
                    "page_id": page_id,
                    "url": url,
                    "reason": _text(row.get("reason"), maximum=800),
                    "excerpt": excerpt,
                }
            )
    else:
        source_texts = page_text_by_id or {}
        for row in raw_passages:
            if not isinstance(row, dict):
                raise SemanticAuditSchemaError("citeable_passage_row_invalid")
            page_id = _text(row.get("page_id"), maximum=100)
            if page_id not in allowed_page_ids:
                raise SemanticAuditSchemaError("invented_passage_page_id")
            excerpt = _text(row.get("excerpt"), maximum=300)
            if source_texts:
                source = _normalized_evidence_text(source_texts.get(page_id, ""))
                needle = _normalized_evidence_text(excerpt)
                if not source or not needle or needle not in source:
                    raise SemanticAuditSchemaError("passage_excerpt_not_in_source")
            passages.append(
                {
                    "page_id": page_id,
                    "url": page_url_by_id[page_id],
                    "reason": _text(row.get("reason"), maximum=800),
                    "excerpt": excerpt,
                }
            )

    normalized = {
        "summary": summary,
        "scores": scores,
        "entity_assessment": {
            "status": entity_status,
            "recognized_entities": normalized_entities,
            "conflicts": conflicts,
        },
        "content_findings": findings,
        "question_assessments": questions,
        "topic_gaps": topic_gaps,
        "citeable_passages": passages,
    }
    return ValidatedSemanticAudit(summary=summary, scores=scores, result=normalized)
