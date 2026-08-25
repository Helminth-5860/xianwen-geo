from apps.website_audits.crawler import CrawlResult, CrawledPage
from apps.website_audits.parser import PageEvidence
from apps.website_audits.rules import evaluate_deterministic_checks


def _evidence(**overrides):
    values = {
        "title": "显问 GEO 官网",
        "meta_description": "显问提供 GEO 与 SEO 深度检测。",
        "canonical_url": "https://example.com/",
        "robots_meta": "index,follow",
        "html_lang": "zh-CN",
        "viewport": "width=device-width, initial-scale=1",
        "headings": {"h1": ["显问 GEO"], "h2": ["官网深度检测"], "h3": [], "h4": [], "h5": [], "h6": []},
        "open_graph": {"og:title": "显问 GEO"},
        "twitter_card": {"twitter:card": "summary_large_image"},
        "schema_types": ["Organization", "WebSite"],
        "schema_entities": [
            {
                "types": ["Organization"],
                "name": "显问",
                "url": "https://example.com/",
                "same_as": ["https://example.net/xianwen"],
                "brand": "",
                "author": "",
                "date_published": "",
                "date_modified": "",
                "telephone": "",
            }
        ],
        "jsonld_block_count": 2,
        "jsonld_invalid_count": 0,
        "image_count": 2,
        "image_alt_missing_count": 0,
        "paragraph_count": 6,
        "list_count": 1,
        "table_count": 1,
        "links": [],
        "text": "显问提供专业 GEO 官网深度检测。" * 40,
    }
    values.update(overrides)
    return PageEvidence(**values)


def _page(evidence=None, **overrides):
    values = {
        "url": "https://example.com/",
        "final_url": "https://example.com/",
        "source": "root",
        "depth": 0,
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "response_ms": 120,
        "response_bytes": 12000,
        "redirect_count": 0,
        "response_sha256": "a" * 64,
        "evidence": evidence if evidence is not None else _evidence(),
        "fetch_error": "",
    }
    values.update(overrides)
    return CrawledPage(**values)


def _result(page, robots_text="User-agent: *\nAllow: /\n"):
    return CrawlResult(
        root_url="https://example.com/",
        root_host="example.com",
        robots_url="https://example.com/robots.txt",
        robots_status=200,
        robots_text=robots_text,
        sitemap_urls=["https://example.com/sitemap.xml"],
        discovered_urls={page.url},
        pages=[page],
        links=[],
    )


def _by_key(findings):
    return {finding.check_key: finding for finding in findings}


def test_deterministic_rules_pass_healthy_technical_foundation():
    findings = _by_key(evaluate_deterministic_checks(_result(_page())))

    assert findings["seo.https"].result == "pass"
    assert findings["seo.root_status"].result == "pass"
    assert findings["seo.title_missing"].result == "pass"
    assert findings["seo.jsonld_validity"].result == "pass"
    assert findings["geo.ai_crawl.openai"].result == "pass"
    assert findings["geo.ai_crawl.perplexity"].result == "pass"
    assert findings["geo.ai_crawl.claude"].result == "pass"
    assert findings["geo.organization_schema"].result == "pass"
    assert findings["geo.organization_schema_completeness"].result == "pass"
    assert findings["geo.website_schema"].result == "pass"


def test_deterministic_rules_surface_real_blockers_and_missing_evidence():
    evidence = _evidence(
        title="",
        meta_description="",
        canonical_url="",
        robots_meta="noindex,nofollow",
        html_lang="",
        viewport="",
        headings={"h1": [], "h2": [], "h3": [], "h4": [], "h5": [], "h6": []},
        schema_types=[],
        schema_entities=[],
        jsonld_block_count=1,
        jsonld_invalid_count=1,
        image_count=3,
        image_alt_missing_count=2,
        paragraph_count=1,
        list_count=0,
        table_count=0,
        text="内容很少",
    )
    robots = """
User-agent: OAI-SearchBot
Disallow: /
User-agent: PerplexityBot
Disallow: /
User-agent: Claude-SearchBot
Disallow: /
User-agent: *
Allow: /
"""
    findings = _by_key(evaluate_deterministic_checks(_result(_page(evidence), robots)))

    assert findings["seo.noindex"].result == "fail"
    assert findings["seo.noindex"].severity == "critical"
    assert findings["seo.title_missing"].result == "fail"
    assert findings["seo.meta_description_missing"].result == "warn"
    assert findings["seo.canonical_missing"].result == "warn"
    assert findings["seo.jsonld_validity"].result == "fail"
    assert findings["seo.image_alt"].affected_count == 2
    assert findings["geo.ai_crawl.openai"].result == "fail"
    assert findings["geo.ai_crawl.perplexity"].result == "fail"
    assert findings["geo.ai_crawl.claude"].result == "fail"
    assert findings["geo.ai_crawl.coverage"].severity == "critical"
    assert findings["geo.organization_schema"].result == "fail"
    assert findings["geo.homepage_identity_surface"].result == "warn"
