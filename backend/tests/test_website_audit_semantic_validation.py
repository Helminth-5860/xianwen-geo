import pytest

from apps.website_audits.semantic_validation import (
    SemanticAuditSchemaError,
    validate_semantic_audit_output,
)


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
                    "evidence_urls": ["https://example.com/"],
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
                "evidence_urls": ["https://example.com/service"],
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
                "evidence_urls": ["https://example.com/service"],
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
                "evidence_urls": ["https://example.com/service"],
            }
        ],
        "citeable_passages": [
            {
                "url": "https://example.com/",
                "reason": "品牌与业务描述明确。",
                "excerpt": "显问提供 AI 搜索可见度诊断。",
            }
        ],
    }


def test_semantic_output_requires_real_input_evidence_urls_and_question_ids():
    validated = validate_semantic_audit_output(
        _payload(),
        allowed_urls=frozenset({"https://example.com/", "https://example.com/service"}),
        allowed_question_ids=frozenset({"q1"}),
    )
    assert validated.scores["entity_clarity"] == 82
    assert validated.result["question_assessments"][0]["question_id"] == "q1"


def test_semantic_output_rejects_invented_url():
    payload = _payload()
    payload["content_findings"][0]["evidence_urls"] = ["https://invented.example/"]
    with pytest.raises(SemanticAuditSchemaError, match="invented_evidence_url"):
        validate_semantic_audit_output(
            payload,
            allowed_urls=frozenset({"https://example.com/", "https://example.com/service"}),
            allowed_question_ids=frozenset({"q1"}),
        )


def test_semantic_output_rejects_missing_formal_question():
    payload = _payload()
    with pytest.raises(SemanticAuditSchemaError, match="question_bank_coverage_incomplete"):
        validate_semantic_audit_output(
            payload,
            allowed_urls=frozenset({"https://example.com/", "https://example.com/service"}),
            allowed_question_ids=frozenset({"q1", "q2"}),
        )


def test_semantic_output_accepts_bounded_derived_questions_without_question_bank():
    payload = _payload()
    payload["question_assessments"] = [
        {
            "source": "derived",
            "question_id": None,
            "question": f"核心问题 {index}",
            "coverage_score": 50,
            "status": "partial",
            "evidence_urls": ["https://example.com/"],
            "answer_summary": "有部分说明。",
            "missing_points": ["细节"],
            "recommendation": "补充明确答案。",
        }
        for index in range(1, 7)
    ]
    validated = validate_semantic_audit_output(
        payload,
        allowed_urls=frozenset({"https://example.com/", "https://example.com/service"}),
        allowed_question_ids=frozenset(),
    )
    assert len(validated.result["question_assessments"]) == 6


def test_semantic_output_verifies_citeable_excerpt_against_crawled_text():
    source_text = "显问提供 AI 搜索可见度诊断。通过公开官网内容帮助企业发现 GEO 内容缺口。"
    validated = validate_semantic_audit_output(
        _payload(),
        allowed_urls=frozenset({"https://example.com/", "https://example.com/service"}),
        allowed_question_ids=frozenset({"q1"}),
        page_text_by_url={
            "https://example.com/": source_text,
            "https://example.com/service": "官网仅说明提供服务。",
        },
    )
    assert validated.result["citeable_passages"][0]["excerpt"] == "显问提供 AI 搜索可见度诊断。"


def test_semantic_output_rejects_citeable_excerpt_not_in_source():
    with pytest.raises(SemanticAuditSchemaError, match="passage_excerpt_not_in_source"):
        validate_semantic_audit_output(
            _payload(),
            allowed_urls=frozenset({"https://example.com/", "https://example.com/service"}),
            allowed_question_ids=frozenset({"q1"}),
            page_text_by_url={
                "https://example.com/": "这里没有模型声称的引用句。",
                "https://example.com/service": "官网仅说明提供服务。",
            },
        )
