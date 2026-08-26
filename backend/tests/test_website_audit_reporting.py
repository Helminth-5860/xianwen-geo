from types import SimpleNamespace

from apps.website_audits.reporting import build_website_audit_report, score_findings


class Related(list):
    def all(self):
        return list(self)


def finding(check_key, category, result="pass", severity="info", method="deterministic"):
    return SimpleNamespace(
        check_key=check_key,
        category=category,
        result=result,
        severity=severity,
        method=method,
        title=check_key,
        dimension="测试维度",
        summary="测试摘要",
        recommendation="测试建议",
        affected_count=1,
    )


def audit(**overrides):
    base = {
        "status": "succeeded",
        "browser_status": "succeeded",
        "semantic_status": "succeeded",
        "semantic_scores": {
            "entity_clarity": 85,
            "fact_density": 80,
            "citation_readiness": 85,
            "topic_coverage": 70,
            "credibility": 90,
            "answer_readiness": 65,
        },
        "semantic_result": {
            "summary": "整体准备度良好。",
            "question_assessments": [
                {"status": "answered"},
                {"status": "answered"},
                {"status": "partial"},
                {"status": "missing"},
            ],
            "content_findings": [{"key": "a"}],
            "topic_gaps": [{"topic": "价格"}],
            "citeable_passages": [{"span_id": "s1"}, {"span_id": "s2"}],
        },
        "findings": Related(
            [
                finding("seo.https", "seo"),
                finding("seo.title", "seo"),
                finding("technical.http", "technical"),
                finding("technical.browser", "technical"),
                finding("geo.entity", "geo"),
                finding("geo.schema", "geo"),
                finding("geo.semantic.issue", "geo", result="warn", severity="medium", method="semantic"),
            ]
        ),
        "browser_snapshots": Related(
            [
                SimpleNamespace(
                    status="succeeded",
                    profile="mobile",
                    ttfb_ms=100,
                    lcp_ms=800,
                    cls=0.02,
                    tbt_ms=30,
                    failed_request_count=1,
                    transfer_bytes=200000,
                ),
                SimpleNamespace(
                    status="succeeded",
                    profile="desktop",
                    ttfb_ms=80,
                    lcp_ms=600,
                    cls=0.01,
                    tbt_ms=20,
                    failed_request_count=0,
                    transfer_bytes=180000,
                ),
            ]
        ),
        "fetched_count": 8,
        "failed_count": 0,
        "browser_completed_count": 12,
        "browser_failed_count": 0,
        "semantic_page_count": 6,
        "semantic_question_count": 18,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_rule_scoring_caps_critical_and_high_failures():
    critical = score_findings(
        [
            finding("a", "seo"),
            finding("b", "seo"),
            finding("c", "seo", result="fail", severity="critical"),
        ]
    )
    assert critical.score == 49
    assert critical.critical_fail_count == 1

    high = score_findings(
        [
            finding("a", "seo"),
            finding("b", "seo", result="fail", severity="high"),
        ]
    )
    assert high.score == 58
    assert high.high_fail_count == 1


def test_complete_report_uses_semantic_dimensions_and_explainable_weights():
    report = build_website_audit_report(audit())

    assert report["status"] == "complete"
    assert report["missing_layers"] == []
    assert report["scores"]["seo"] == 100
    assert report["scores"]["technical_health"] == 100
    assert report["scores"]["ai_readability"] == 86
    assert report["scores"]["content_readiness"] == 71
    assert report["scores"]["geo"] == 86
    assert report["overall_score"] == 94
    assert report["components"]["geo_rules"]["check_count"] == 2
    assert report["semantic_summary"]["question_coverage"] == {
        "total": 4,
        "answered": 2,
        "partial": 1,
        "missing": 1,
    }
    assert report["browser_metrics"]["mobile"]["lcp_p75_ms"] == 800


def test_report_refuses_final_scores_when_semantic_or_browser_layer_is_missing():
    semantic_failed = build_website_audit_report(
        audit(semantic_status="failed", semantic_scores={}, semantic_result={})
    )
    assert semantic_failed["status"] == "partial"
    assert semantic_failed["scores"]["geo"] is None
    assert semantic_failed["overall_score"] is None
    assert "semantic" in semantic_failed["missing_layers"]
    assert semantic_failed["components"]["geo_rules"]["score"] == 100

    browser_failed = build_website_audit_report(audit(browser_status="failed"))
    assert browser_failed["status"] == "partial"
    assert browser_failed["scores"]["geo"] == 86
    assert browser_failed["overall_score"] is None
    assert "browser" in browser_failed["missing_layers"]
