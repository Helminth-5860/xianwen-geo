import pytest

from apps.website_audits.semantic_validation import (
    SemanticAuditSchemaError,
    validate_semantic_audit_output,
)

_PAGE_URLS = {
    "p1": "https://example.com/",
    "p2": "https://example.com/service",
}


def _payload():
    return {
        "summary": "官网主体清晰，但问题覆盖仍有缺口。",
        "scores": {
            "entity_clarity": 82,
            "fact_density": 68,
            "citation_readiness": 72,
            "topic_coverage": 61,
            "credibility": 66,
            "answer_readiness": 58,
        },
        "entity_assessment": {
            "status": "clear",
            "recognized_entities": [
                {
                    "name": "显问",
                    "type": "brand",
                    "evidence_page_ids": ["p1"],
                }
            ],
            "conflicts": [],
        },
        "content_findings": [
            {
                "key": "pricing_gap",
                "severity": "medium",
                "title": "价格信息不足",
                "reason": "官网没有明确价格说明。",
                "evidence_page_ids": ["p2"],
                "recommendation": "增加价格口径或询价规则。",
            }
        ],
        "question_assessments": [
            {
                "source": "question_bank",
                "question_id": "q1",
                "question": "显问怎么收费？",
                "coverage_score": 20,
                "status": "partial",
                "evidence_page_ids": ["p2"],
                "answer_summary": "官网仅说明提供服务。",
                "missing_points": ["价格", "套餐差异"],
                "recommendation": "补充收费方式。",
            }
        ],
        "topic_gaps": [
            {
                "topic": "价格与套餐",
                "importance": "high",
                "reason": "影响采购决策。",
                "suggested_content": "增加套餐与计费说明。",
                "evidence_page_ids": ["p2"],
            }
        ],
        "citeable_passages": [
            {
                "page_id": "p1",
                "reason": "品牌与业务描述明确。",
                "excerpt": "显问提供 AI 搜索可见度诊断。",
            }
        ],
    }


def _validate(payload, *, question_ids=frozenset({"q1"}), page_text_by_id=None):
    return validate_semantic_audit_output(
        payload,
        allowed_page_ids=frozenset(_PAGE_URLS),
        allowed_question_ids=question_ids,
        page_url_by_id=_PAGE_URLS,
        page_text_by_id=page_text_by_id,
    )


def test_semantic_output_requires_real_input_page_ids_and_question_ids():
    validated = _validate(_payload())
    assert validated.scores["entity_clarity"] == 82
    assert validated.result["question_assessments"][0]["question_id"] == "q1"
    assert validated.result["content_findings"][0]["evidence_urls"] == [
        "https://example.com/service"
    ]


def test_semantic_output_rejects_invented_page_id():
    payload = _payload()
    payload["content_findings"][0]["evidence_page_ids"] = ["p999"]
    with pytest.raises(SemanticAuditSchemaError, match="invented_evidence_page_id"):
        _validate(payload)


def test_semantic_output_rejects_missing_formal_question():
    with pytest.raises(SemanticAuditSchemaError, match="question_bank_coverage_incomplete"):
        _validate(_payload(), question_ids=frozenset({"q1", "q2"}))


def test_semantic_output_accepts_bounded_derived_questions_without_question_bank():
    payload = _payload()
    payload["question_assessments"] = [
        {
            "source": "derived",
            "question_id": None,
            "question": f"核心问题 {index}",
            "coverage_score": 50,
            "status": "partial",
            "evidence_page_ids": ["p1"],
            "answer_summary": "有部分说明。",
            "missing_points": ["细节"],
            "recommendation": "补充明确答案。",
        }
        for index in range(1, 7)
    ]
    validated = _validate(payload, question_ids=frozenset())
    assert len(validated.result["question_assessments"]) == 6


def test_semantic_output_verifies_citeable_excerpt_against_crawled_text():
    source_text = "显问提供 AI 搜索可见度诊断。通过公开官网内容帮助企业发现 GEO 内容缺口。"
    validated = _validate(
        _payload(),
        page_text_by_id={
            "p1": source_text,
            "p2": "官网仅说明提供服务。",
        },
    )
    passage = validated.result["citeable_passages"][0]
    assert passage["excerpt"] == "显问提供 AI 搜索可见度诊断。"
    assert passage["url"] == "https://example.com/"


def test_semantic_output_rejects_citeable_excerpt_not_in_source():
    with pytest.raises(SemanticAuditSchemaError, match="passage_excerpt_not_in_source"):
        _validate(
            _payload(),
            page_text_by_id={
                "p1": "这里没有模型声称的引用句。",
                "p2": "官网仅说明提供服务。",
            },
        )


def test_semantic_output_rejects_invented_passage_page_id():
    payload = _payload()
    payload["citeable_passages"][0]["page_id"] = "p999"
    with pytest.raises(SemanticAuditSchemaError, match="invented_passage_page_id"):
        _validate(payload)
