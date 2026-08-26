from apps.website_audits.semantic_spans import build_evidence_spans, prepare_provider_pages
from apps.website_audits.semantic_validation import validate_semantic_audit_output


def _semantic_payload(span_id: str):
    return {
        "summary": "官网主体清晰，但仍有内容缺口。",
        "scores": {
            "entity_clarity": 80,
            "fact_density": 60,
            "citation_readiness": 70,
            "topic_coverage": 60,
            "credibility": 60,
            "answer_readiness": 55,
        },
        "entity_assessment": {
            "status": "clear",
            "recognized_entities": [
                {"name": "显问", "type": "brand", "evidence_page_ids": ["p1"]}
            ],
            "conflicts": [],
        },
        "content_findings": [],
        "question_assessments": [
            {
                "source": "derived",
                "question_id": None,
                "question": f"核心问题 {index}",
                "coverage_score": 50,
                "status": "partial",
                "evidence_page_ids": ["p1"],
                "answer_summary": "官网有部分说明。",
                "missing_points": ["细节"],
                "recommendation": "补充明确答案。",
            }
            for index in range(1, 7)
        ],
        "topic_gaps": [],
        "citeable_passages": [
            {"evidence_span_id": span_id, "reason": "该片段是完整、可独立引用的陈述。"}
        ],
    }


def test_semantic_evidence_spans_are_deterministic_and_bounded():
    text = "显问提供AI搜索可见度诊断。通过公开官网内容帮助企业发现GEO内容缺口。" * 20
    first = build_evidence_spans(page_id="p1", text=text)
    second = build_evidence_spans(page_id="p1", text=text)

    assert first == second
    assert first
    assert all(row["span_id"].startswith("p1:s") for row in first)
    assert all(0 < len(row["text"]) <= 280 for row in first)
    assert len(first) <= 30


def test_provider_pages_replace_free_text_with_backend_evidence_spans():
    pages, span_by_id = prepare_provider_pages(
        [
            {
                "page_id": "p1",
                "url": "https://example.com/",
                "title": "显问",
                "text": "显问提供AI搜索可见度诊断。通过公开官网内容帮助企业发现GEO内容缺口。",
            }
        ]
    )

    assert "text" not in pages[0]
    assert pages[0]["evidence_spans"]
    assert span_by_id
    span = next(iter(span_by_id.values()))
    assert span["page_id"] == "p1"
    assert span["url"] == "https://example.com/"


def test_semantic_citeable_passage_is_derived_from_backend_span_not_model_quote():
    pages, span_by_id = prepare_provider_pages(
        [
            {
                "page_id": "p1",
                "url": "https://example.com/",
                "title": "显问",
                "text": "显问提供AI搜索可见度诊断。通过公开官网内容帮助企业发现GEO内容缺口。",
            }
        ]
    )
    span_id = pages[0]["evidence_spans"][0]["span_id"]

    validated = validate_semantic_audit_output(
        _semantic_payload(span_id),
        allowed_page_ids=frozenset({"p1"}),
        allowed_question_ids=frozenset(),
        page_url_by_id={"p1": "https://example.com/"},
        evidence_span_by_id=span_by_id,
    )

    passage = validated.result["citeable_passages"][0]
    assert passage["evidence_span_id"] == span_id
    assert passage["url"] == "https://example.com/"
    assert passage["excerpt"] == span_by_id[span_id]["text"]
