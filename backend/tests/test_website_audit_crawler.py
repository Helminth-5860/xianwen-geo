from apps.website_audits.crawler import crawl_website
from apps.website_audits.transport import AuditFetchResult


def _result(url: str, body: str, *, content_type: str, status: int = 200):
    return AuditFetchResult(
        request_url=url,
        final_url=url,
        status=status,
        content_type=content_type,
        body=body.encode(),
        redirect_count=0,
        response_ms=25,
        headers={"content-type": content_type},
    )


def test_crawl_website_discovers_sitemap_and_internal_links(monkeypatch):
    fixtures = {
        "https://example.com/": _result(
            "https://example.com/",
            '<html><head><title>Home</title></head><body><a href="/about">About</a><a href="/missing">Missing</a><a href="https://outside.test/x">Outside</a></body></html>',
            content_type="text/html; charset=utf-8",
        ),
        "https://example.com/robots.txt": _result(
            "https://example.com/robots.txt",
            "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml",
            content_type="text/plain; charset=utf-8",
        ),
        "https://example.com/sitemap.xml": _result(
            "https://example.com/sitemap.xml",
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/about</loc></url><url><loc>https://example.com/contact</loc></url></urlset>',
            content_type="application/xml; charset=utf-8",
        ),
        "https://example.com/about": _result(
            "https://example.com/about",
            '<html><head><title>About</title></head><body><h1>About</h1><a href="/contact">Contact</a></body></html>',
            content_type="text/html; charset=utf-8",
        ),
        "https://example.com/contact": _result(
            "https://example.com/contact",
            '<html><head><title>Contact</title></head><body><h1>Contact</h1></body></html>',
            content_type="text/html; charset=utf-8",
        ),
        "https://example.com/missing": _result(
            "https://example.com/missing",
            "not found",
            content_type="text/html; charset=utf-8",
            status=404,
        ),
    }

    def fake_fetch(url, **_kwargs):
        if url in fixtures:
            return fixtures[url]
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr("apps.website_audits.crawler.fetch_audit_url", fake_fetch)

    result = crawl_website("https://example.com/", max_pages=10)

    assert result.root_host == "example.com"
    assert result.robots_status == 200
    assert result.sitemap_urls == ["https://example.com/sitemap.xml"]
    assert {page.url for page in result.pages} == {
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/contact",
        "https://example.com/missing",
    }
    missing = next(page for page in result.pages if page.url.endswith("/missing"))
    assert missing.status == 404
    assert any(not link.is_internal for link in result.links)
    assert "https://example.com/contact" in result.discovered_urls
