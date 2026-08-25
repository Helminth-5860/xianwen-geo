from apps.website_audits.browser_rules import evaluate_browser_checks
from apps.website_audits.browser_runner import BrowserPageResult


def _result(**overrides):
    values = dict(
        page_id="page-1",
        url="https://example.com/product",
        profile="mobile",
        status="succeeded",
        final_url="https://example.com/product",
        navigation_ms=1200,
        ttfb_ms=350,
        fcp_ms=900,
        lcp_ms=1600,
        cls=0.03,
        tbt_ms=80,
        request_count=40,
        failed_request_count=0,
        blocked_request_count=0,
        transfer_bytes=800_000,
        cross_host_request_count=5,
        cross_host_transfer_bytes=100_000,
        resource_summary={"Document": {"requests": 1, "bytes": 50_000}},
        console_error_count=0,
        page_error_count=0,
        dom_nodes=700,
        rendered_html_characters=50_000,
        rendered_text_characters=1800,
        static_text_characters=1700,
        text_delta=100,
        text_growth_ratio=1.0588,
        rendered_title="产品页",
        rendered_meta_description="产品描述",
        rendered_canonical_url="https://example.com/product",
        rendered_schema_types=("Product",),
        rendered_heading_counts={"h1": 1},
        visible_image_count=3,
        images_without_alt=0,
        static_title="产品页",
        static_meta_description="产品描述",
        static_canonical_url="https://example.com/product",
        static_schema_types=("Product",),
        evidence={},
    )
    values.update(overrides)
    return BrowserPageResult(**values)


def test_browser_rules_pass_for_stable_server_rendered_page():
    findings = evaluate_browser_checks([_result()])
    by_key = {item.check_key: item for item in findings}

    assert by_key["browser.execution_coverage"].result == "pass"
    assert by_key["browser.js_text_dependency"].result == "pass"
    assert by_key["browser.dynamic_metadata"].result == "pass"
    assert by_key["browser.performance_lcp"].result == "pass"
    assert by_key["browser.performance_cls"].result == "pass"


def test_browser_rules_flag_js_dependency_dynamic_metadata_and_slow_lcp():
    findings = evaluate_browser_checks(
        [
            _result(
                rendered_text_characters=2400,
                static_text_characters=120,
                text_delta=2280,
                text_growth_ratio=20.0,
                rendered_title="JS 后标题",
                static_title="静态标题",
                rendered_schema_types=("Product", "Organization"),
                static_schema_types=("Product",),
                lcp_ms=5200,
                cls=0.31,
                tbt_ms=900,
                blocked_request_count=2,
            )
        ]
    )
    by_key = {item.check_key: item for item in findings}

    assert by_key["browser.js_text_dependency"].result == "warn"
    assert by_key["browser.dynamic_metadata"].result == "warn"
    assert by_key["browser.dynamic_schema"].result == "warn"
    assert by_key["browser.blocked_private_requests"].result == "warn"
    assert by_key["browser.performance_lcp"].result == "fail"
    assert by_key["browser.performance_cls"].result == "fail"
    assert by_key["browser.performance_tbt"].result == "fail"
    assert all(item.method == "browser" for item in findings)
