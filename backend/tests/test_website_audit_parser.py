from apps.website_audits.parser import parse_html


def test_parse_html_collects_seo_geo_evidence():
    html = """
    <html lang="zh-CN">
      <head>
        <title>显问 GEO</title>
        <meta name="description" content="显问 GEO 官网">
        <meta name="robots" content="index,follow">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta property="og:title" content="显问 GEO">
        <meta name="twitter:card" content="summary_large_image">
        <link rel="canonical" href="/official">
        <script type="application/ld+json">{"@type":"Organization","name":"显问"}</script>
      </head>
      <body>
        <h1>AI 搜索可见度</h1>
        <h2>官网检测</h2>
        <img src="ok.png" alt="检测报告">
        <img src="missing.png">
        <a href="/about" rel="nofollow">关于我们</a>
        <a href="https://example.net/news">外部报道</a>
      </body>
    </html>
    """

    evidence = parse_html(html, "https://example.com/")

    assert evidence.title == "显问 GEO"
    assert evidence.meta_description == "显问 GEO 官网"
    assert evidence.canonical_url == "https://example.com/official"
    assert evidence.robots_meta == "index,follow"
    assert evidence.html_lang == "zh-CN"
    assert evidence.viewport.startswith("width=device-width")
    assert evidence.headings["h1"] == ["AI 搜索可见度"]
    assert evidence.headings["h2"] == ["官网检测"]
    assert evidence.open_graph["og:title"] == "显问 GEO"
    assert evidence.twitter_card["twitter:card"] == "summary_large_image"
    assert evidence.schema_types == ["Organization"]
    assert evidence.image_count == 2
    assert evidence.image_alt_missing_count == 1
    assert [link.url for link in evidence.links] == [
        "https://example.com/about",
        "https://example.net/news",
    ]
