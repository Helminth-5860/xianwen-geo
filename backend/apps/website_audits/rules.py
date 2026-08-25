from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .crawler import CrawlResult, CrawledPage

RULESET_VERSION = "deterministic-v1"
_MAX_EVIDENCE_URLS = 50


@dataclass(frozen=True)
class FindingDraft:
    category: str
    dimension: str
    check_key: str
    severity: str
    result: str
    title: str
    summary: str
    impact: str
    recommendation: str
    affected_count: int
    evidence: dict[str, object]
    method: str = "deterministic"
    rule_version: str = RULESET_VERSION


def _html_pages(result: CrawlResult) -> list[CrawledPage]:
    pages: list[CrawledPage] = []
    for page in result.pages:
        media_type = page.content_type.split(";", 1)[0].strip().lower()
        if page.status == 200 and page.evidence is not None and media_type in {
            "text/html",
            "application/xhtml+xml",
        }:
            pages.append(page)
    return pages


def _root_page(result: CrawlResult) -> CrawledPage | None:
    for page in result.pages:
        if page.source == "root":
            return page
    return result.pages[0] if result.pages else None


def _urls(pages: list[CrawledPage], limit: int = _MAX_EVIDENCE_URLS) -> list[str]:
    return [page.url for page in pages[:limit]]


def _page_evidence(pages: list[CrawledPage]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for page in pages[:_MAX_EVIDENCE_URLS]:
        rows.append(
            {
                "url": page.url,
                "final_url": page.final_url,
                "status": page.status,
                "response_ms": page.response_ms,
                "source": page.source,
                "depth": page.depth,
            }
        )
    return rows


def _finding(
    *,
    category: str,
    dimension: str,
    check_key: str,
    severity: str,
    result: str,
    title: str,
    summary: str,
    impact: str,
    recommendation: str,
    affected_count: int = 0,
    evidence: dict[str, object] | None = None,
) -> FindingDraft:
    return FindingDraft(
        category=category,
        dimension=dimension,
        check_key=check_key,
        severity=severity,
        result=result,
        title=title,
        summary=summary,
        impact=impact,
        recommendation=recommendation,
        affected_count=affected_count,
        evidence=evidence or {},
    )


def _robots_parser(result: CrawlResult) -> RobotFileParser | None:
    if result.robots_status is None:
        return None
    parser = RobotFileParser()
    parser.set_url(result.robots_url)
    if result.robots_status == 200:
        parser.parse(result.robots_text.splitlines())
    else:
        # RFC-compatible operational interpretation: a missing/unavailable rule file
        # does not introduce an explicit disallow rule. We still surface the HTTP
        # status separately so the report does not pretend robots.txt exists.
        parser.parse([])
    return parser


def _contains_noindex(robots_meta: str) -> bool:
    values = {token.strip().lower() for token in robots_meta.replace(";", ",").split(",")}
    return "noindex" in values or "none" in values


def _canonical_host(page: CrawledPage) -> str:
    if page.evidence is None or not page.evidence.canonical_url:
        return ""
    return (urlsplit(page.evidence.canonical_url).hostname or "").lower()


def _duplicate_groups(pages: list[CrawledPage], attr: str) -> dict[str, list[CrawledPage]]:
    groups: dict[str, list[CrawledPage]] = defaultdict(list)
    for page in pages:
        evidence = page.evidence
        if evidence is None:
            continue
        value = getattr(evidence, attr, "").strip()
        if value:
            groups[value].append(page)
    return {value: rows for value, rows in groups.items() if len(rows) > 1}


def _probable_pages(pages: list[CrawledPage], terms: tuple[str, ...]) -> list[CrawledPage]:
    matched: list[CrawledPage] = []
    for page in pages:
        evidence = page.evidence
        haystack = f"{page.url} {(evidence.title if evidence else '')}".lower()
        if any(term in haystack for term in terms):
            matched.append(page)
    return matched


def evaluate_deterministic_checks(result: CrawlResult) -> list[FindingDraft]:
    findings: list[FindingDraft] = []
    html_pages = _html_pages(result)
    root = _root_page(result)

    # ---------------- SEO: crawlability and transport ----------------
    https_ok = urlsplit(result.root_url).scheme.lower() == "https"
    findings.append(
        _finding(
            category="seo",
            dimension="抓取与索引",
            check_key="seo.https",
            severity="high" if not https_ok else "info",
            result="pass" if https_ok else "fail",
            title="HTTPS 已启用" if https_ok else "官网未使用 HTTPS",
            summary="首页使用 HTTPS。" if https_ok else "检测入口最终地址不是 HTTPS。",
            impact="HTTPS 是搜索引擎抓取、浏览器信任和安全传输的基础条件。",
            recommendation="保持 HTTPS 全站可用，并将 HTTP 永久重定向到 HTTPS。",
            evidence={"root_url": result.root_url},
        )
    )

    root_ok = root is not None and root.status == 200 and not root.fetch_error
    findings.append(
        _finding(
            category="seo",
            dimension="抓取与索引",
            check_key="seo.root_status",
            severity="critical" if not root_ok else "info",
            result="pass" if root_ok else "fail",
            title="首页可正常访问" if root_ok else "首页无法正常返回 200",
            summary=(
                "首页返回 HTTP 200。"
                if root_ok
                else "首页不是稳定的 HTTP 200 响应，搜索系统和用户可能无法正常访问。"
            ),
            impact="首页不可用会直接影响整站发现、索引和品牌实体识别。",
            recommendation="修复首页状态码、网关、源站或重定向配置，确保最终页面稳定返回 200。",
            evidence=(
                {
                    "url": root.url if root else result.root_url,
                    "status": root.status if root else None,
                    "fetch_error": root.fetch_error if root else "ROOT_NOT_CAPTURED",
                }
            ),
        )
    )

    if result.robots_status == 200:
        robots_result, robots_severity = "pass", "info"
        robots_title = "robots.txt 可正常读取"
        robots_summary = "已成功获取 robots.txt。"
    elif result.robots_status in {404, 410}:
        robots_result, robots_severity = "warn", "medium"
        robots_title = "未提供 robots.txt"
        robots_summary = "robots.txt 返回不存在状态；当前没有发现显式抓取规则。"
    elif result.robots_status is None:
        robots_result, robots_severity = "warn", "high"
        robots_title = "robots.txt 无法验证"
        robots_summary = "扫描器无法确认 robots.txt 的真实状态。"
    else:
        robots_result, robots_severity = "warn", "high"
        robots_title = "robots.txt 返回异常状态"
        robots_summary = f"robots.txt 返回 HTTP {result.robots_status}。"
    findings.append(
        _finding(
            category="seo",
            dimension="抓取与索引",
            check_key="seo.robots",
            severity=robots_severity,
            result=robots_result,
            title=robots_title,
            summary=robots_summary,
            impact="robots.txt 会影响搜索爬虫与 AI 搜索爬虫对站点路径的访问策略。",
            recommendation="在站点根目录提供可稳定访问的 robots.txt，并避免误封核心公开页面。",
            evidence={"robots_url": result.robots_url, "robots_status": result.robots_status},
        )
    )

    sitemap_ok = bool(result.sitemap_urls)
    findings.append(
        _finding(
            category="seo",
            dimension="抓取与索引",
            check_key="seo.sitemap",
            severity="medium" if not sitemap_ok else "info",
            result="pass" if sitemap_ok else "warn",
            title="Sitemap 可发现" if sitemap_ok else "未发现可用 Sitemap",
            summary=(
                f"发现 {len(result.sitemap_urls)} 个已成功读取的 Sitemap。"
                if sitemap_ok
                else "robots.txt 与默认 sitemap.xml 路径均未得到可用站点地图。"
            ),
            impact="Sitemap 能帮助搜索系统更完整、更快地发现重要页面，尤其适用于大型网站。",
            recommendation="生成并维护 XML Sitemap，在 robots.txt 中声明并保持 URL 与规范地址一致。",
            evidence={"sitemap_urls": result.sitemap_urls[:50]},
        )
    )

    error_pages = [
        page
        for page in result.pages
        if page.fetch_error or (page.status is not None and page.status >= 400)
    ]
    server_error_pages = [page for page in error_pages if page.status is not None and page.status >= 500]
    findings.append(
        _finding(
            category="seo",
            dimension="抓取与索引",
            check_key="seo.http_errors",
            severity=("critical" if server_error_pages else "high") if error_pages else "info",
            result="fail" if error_pages else "pass",
            title="存在抓取失败或错误页面" if error_pages else "扫描页面均可正常获取",
            summary=(
                f"本次扫描中有 {len(error_pages)} 个页面发生抓取错误或返回 4xx/5xx。"
                if error_pages
                else "本次纳入扫描的页面未发现抓取失败或 4xx/5xx。"
            ),
            impact="错误页面会浪费抓取资源，并破坏搜索系统对网站结构和内容完整性的判断。",
            recommendation="逐项修复 4xx、5xx、超时和连接失败；已删除页面应正确处理内部链接与重定向。",
            affected_count=len(error_pages),
            evidence={"pages": _page_evidence(error_pages)},
        )
    )

    redirect_chains = [page for page in result.pages if page.redirect_count >= 2]
    findings.append(
        _finding(
            category="seo",
            dimension="抓取与索引",
            check_key="seo.redirect_chains",
            severity="medium" if redirect_chains else "info",
            result="warn" if redirect_chains else "pass",
            title="存在多跳重定向" if redirect_chains else "未发现多跳重定向",
            summary=(
                f"有 {len(redirect_chains)} 个页面经历至少 2 次重定向。"
                if redirect_chains
                else "扫描页面未出现两跳及以上的重定向链。"
            ),
            impact="多跳重定向增加延迟、抓取成本，并可能削弱规范 URL 信号。",
            recommendation="将内部链接直接指向最终 URL，并尽量把重定向链压缩为单跳。",
            affected_count=len(redirect_chains),
            evidence={"pages": _page_evidence(redirect_chains)},
        )
    )

    # ---------------- SEO: on-page ----------------
    noindex_pages = [page for page in html_pages if _contains_noindex(page.evidence.robots_meta)]
    root_noindex = any(page.source == "root" for page in noindex_pages)
    findings.append(
        _finding(
            category="seo",
            dimension="抓取与索引",
            check_key="seo.noindex",
            severity=("critical" if root_noindex else "high") if noindex_pages else "info",
            result="fail" if noindex_pages else "pass",
            title="发现 noindex 页面" if noindex_pages else "未发现 noindex 阻断",
            summary=(
                f"扫描页面中有 {len(noindex_pages)} 个页面声明 noindex。"
                if noindex_pages
                else "扫描样本未发现通过 meta robots 声明 noindex 的 HTML 页面。"
            ),
            impact="noindex 会明确要求支持该指令的搜索系统不要将页面纳入索引。",
            recommendation="确认这些页面是否确实需要排除；核心首页、产品页和内容页不要误设 noindex。",
            affected_count=len(noindex_pages),
            evidence={"pages": _urls(noindex_pages)},
        )
    )

    missing_title = [page for page in html_pages if not page.evidence.title.strip()]
    findings.append(
        _finding(
            category="seo",
            dimension="页面基础SEO",
            check_key="seo.title_missing",
            severity="high" if missing_title else "info",
            result="fail" if missing_title else "pass",
            title="存在缺失标题的页面" if missing_title else "页面标题完整",
            summary=(
                f"有 {len(missing_title)} 个 HTML 页面未检测到有效 title。"
                if missing_title
                else "扫描到的 HTML 页面均包含 title。"
            ),
            impact="Title 是搜索结果理解页面主题和区分页面的重要信号。",
            recommendation="为每个可索引页面提供唯一、准确、与页面主体内容一致的标题。",
            affected_count=len(missing_title),
            evidence={"pages": _urls(missing_title)},
        )
    )

    duplicate_titles = _duplicate_groups(html_pages, "title")
    duplicate_title_pages = sum(len(rows) for rows in duplicate_titles.values())
    findings.append(
        _finding(
            category="seo",
            dimension="页面基础SEO",
            check_key="seo.title_duplicate",
            severity="medium" if duplicate_titles else "info",
            result="warn" if duplicate_titles else "pass",
            title="存在重复页面标题" if duplicate_titles else "未发现重复页面标题",
            summary=(
                f"发现 {len(duplicate_titles)} 组重复 title，涉及 {duplicate_title_pages} 个页面。"
                if duplicate_titles
                else "扫描样本中未发现完全相同的非空 title。"
            ),
            impact="大量重复标题会降低页面主题区分度，也常伴随重复内容或模板问题。",
            recommendation="让不同页面的 title 能准确区分各自主题；对重复 URL 同时检查 canonical 与内容重复。",
            affected_count=duplicate_title_pages,
            evidence={
                "groups": [
                    {"title": title[:300], "urls": _urls(rows, 20)}
                    for title, rows in list(duplicate_titles.items())[:20]
                ]
            },
        )
    )

    missing_description = [page for page in html_pages if not page.evidence.meta_description.strip()]
    findings.append(
        _finding(
            category="seo",
            dimension="页面基础SEO",
            check_key="seo.meta_description_missing",
            severity="medium" if missing_description else "info",
            result="warn" if missing_description else "pass",
            title="存在缺失描述的页面" if missing_description else "页面描述完整",
            summary=(
                f"有 {len(missing_description)} 个 HTML 页面未检测到 meta description。"
                if missing_description
                else "扫描到的 HTML 页面均包含 meta description。"
            ),
            impact="描述不直接保证排名，但会影响搜索结果摘要控制、页面主题表达和点击理解。",
            recommendation="为重要页面提供清晰、独立、与正文一致的描述，避免模板化重复。",
            affected_count=len(missing_description),
            evidence={"pages": _urls(missing_description)},
        )
    )

    duplicate_descriptions = _duplicate_groups(html_pages, "meta_description")
    duplicate_description_pages = sum(len(rows) for rows in duplicate_descriptions.values())
    findings.append(
        _finding(
            category="seo",
            dimension="页面基础SEO",
            check_key="seo.meta_description_duplicate",
            severity="low" if duplicate_descriptions else "info",
            result="warn" if duplicate_descriptions else "pass",
            title="存在重复页面描述" if duplicate_descriptions else "未发现重复页面描述",
            summary=(
                f"发现 {len(duplicate_descriptions)} 组重复描述，涉及 {duplicate_description_pages} 个页面。"
                if duplicate_descriptions
                else "扫描样本中未发现完全相同的非空 meta description。"
            ),
            impact="重复描述会降低不同页面在搜索结果中的区分度。",
            recommendation="优先为首页、产品、服务、分类和核心内容页编写独立描述。",
            affected_count=duplicate_description_pages,
            evidence={
                "groups": [
                    {"description": text[:300], "urls": _urls(rows, 20)}
                    for text, rows in list(duplicate_descriptions.items())[:20]
                ]
            },
        )
    )

    missing_h1 = [page for page in html_pages if not page.evidence.headings.get("h1")]
    multiple_h1 = [page for page in html_pages if len(page.evidence.headings.get("h1", [])) > 1]
    findings.append(
        _finding(
            category="seo",
            dimension="页面结构",
            check_key="seo.h1_missing",
            severity="medium" if missing_h1 else "info",
            result="warn" if missing_h1 else "pass",
            title="存在缺少 H1 的页面" if missing_h1 else "页面 H1 基础结构正常",
            summary=(
                f"有 {len(missing_h1)} 个 HTML 页面没有 H1。"
                if missing_h1
                else "扫描到的 HTML 页面均至少包含一个 H1。"
            ),
            impact="清晰的主标题有助于用户和机器快速确认页面主要主题。",
            recommendation="为重要页面设置一个能准确表达页面主题的主标题，并保持标题层级清晰。",
            affected_count=len(missing_h1),
            evidence={"pages": _urls(missing_h1)},
        )
    )
    findings.append(
        _finding(
            category="seo",
            dimension="页面结构",
            check_key="seo.h1_multiple",
            severity="low" if multiple_h1 else "info",
            result="warn" if multiple_h1 else "pass",
            title="存在多个 H1 的页面" if multiple_h1 else "未发现多个 H1 的页面",
            summary=(
                f"有 {len(multiple_h1)} 个页面检测到多个 H1。"
                if multiple_h1
                else "扫描样本未发现一个页面包含多个 H1。"
            ),
            impact="多个 H1 并非绝对错误，但在复杂模板中可能导致页面主题层级不清晰。",
            recommendation="检查页面标题结构；若多个 H1 并无明确语义必要，建议保留一个核心主标题。",
            affected_count=len(multiple_h1),
            evidence={"pages": _urls(multiple_h1)},
        )
    )

    missing_canonical = [page for page in html_pages if not page.evidence.canonical_url.strip()]
    cross_host_canonical = [
        page
        for page in html_pages
        if _canonical_host(page) and _canonical_host(page) != result.root_host
    ]
    findings.append(
        _finding(
            category="seo",
            dimension="规范化",
            check_key="seo.canonical_missing",
            severity="medium" if missing_canonical else "info",
            result="warn" if missing_canonical else "pass",
            title="存在缺失 Canonical 的页面" if missing_canonical else "Canonical 覆盖完整",
            summary=(
                f"有 {len(missing_canonical)} 个 HTML 页面未声明 canonical。"
                if missing_canonical
                else "扫描到的 HTML 页面均声明 canonical。"
            ),
            impact="Canonical 可帮助搜索系统理解重复或近似页面应归并到哪个规范 URL。",
            recommendation="对可索引页面设置准确的自引用或规范 canonical，并确保目标地址可访问。",
            affected_count=len(missing_canonical),
            evidence={"pages": _urls(missing_canonical)},
        )
    )
    findings.append(
        _finding(
            category="seo",
            dimension="规范化",
            check_key="seo.canonical_cross_host",
            severity="high" if cross_host_canonical else "info",
            result="fail" if cross_host_canonical else "pass",
            title="Canonical 指向站外域名" if cross_host_canonical else "未发现异常站外 Canonical",
            summary=(
                f"有 {len(cross_host_canonical)} 个页面的 canonical 指向其他主机。"
                if cross_host_canonical
                else "扫描样本未发现 canonical 指向其他主机。"
            ),
            impact="错误的跨域 canonical 可能把当前页面的规范信号归给其他站点。",
            recommendation="逐项确认跨域 canonical 是否有明确业务意图；无明确意图时应改为本站规范 URL。",
            affected_count=len(cross_host_canonical),
            evidence={
                "pages": [
                    {"url": page.url, "canonical": page.evidence.canonical_url}
                    for page in cross_host_canonical[:_MAX_EVIDENCE_URLS]
                ]
            },
        )
    )

    missing_lang = [page for page in html_pages if not page.evidence.html_lang.strip()]
    missing_viewport = [page for page in html_pages if not page.evidence.viewport.strip()]
    findings.append(
        _finding(
            category="seo",
            dimension="移动端与技术质量",
            check_key="seo.html_lang_missing",
            severity="low" if missing_lang else "info",
            result="warn" if missing_lang else "pass",
            title="存在缺失语言声明的页面" if missing_lang else "HTML 语言声明完整",
            summary=(
                f"有 {len(missing_lang)} 个 HTML 页面没有 lang 属性。"
                if missing_lang
                else "扫描页面均声明 HTML lang。"
            ),
            impact="语言声明有助于浏览器、辅助技术和机器理解页面主要语言。",
            recommendation="在 html 标签上声明准确的 lang，例如简体中文使用 zh-CN 或 zh-Hans。",
            affected_count=len(missing_lang),
            evidence={"pages": _urls(missing_lang)},
        )
    )
    findings.append(
        _finding(
            category="seo",
            dimension="移动端与技术质量",
            check_key="seo.viewport_missing",
            severity="medium" if missing_viewport else "info",
            result="warn" if missing_viewport else "pass",
            title="存在缺失 Viewport 的页面" if missing_viewport else "Viewport 配置完整",
            summary=(
                f"有 {len(missing_viewport)} 个 HTML 页面没有 viewport meta。"
                if missing_viewport
                else "扫描页面均包含 viewport meta。"
            ),
            impact="缺失 viewport 常导致移动端页面缩放和布局异常。",
            recommendation="为响应式页面提供正确 viewport 配置，并结合真实移动端浏览器检测验证布局。",
            affected_count=len(missing_viewport),
            evidence={"pages": _urls(missing_viewport)},
        )
    )

    alt_pages = [page for page in html_pages if page.evidence.image_alt_missing_count > 0]
    missing_alt_total = sum(page.evidence.image_alt_missing_count for page in alt_pages)
    image_total = sum(page.evidence.image_count for page in html_pages)
    findings.append(
        _finding(
            category="seo",
            dimension="内容与媒体基础",
            check_key="seo.image_alt",
            severity="medium" if alt_pages else "info",
            result="warn" if alt_pages else "pass",
            title="存在缺少 Alt 的图片" if alt_pages else "图片 Alt 基础检查通过",
            summary=(
                f"共检测 {image_total} 张图片，其中 {missing_alt_total} 张缺少非空 alt。"
                if alt_pages
                else f"共检测 {image_total} 张图片，未发现缺少 alt 的图片。"
            ),
            impact="Alt 文本有助于无障碍访问，也让搜索和 AI 系统更容易理解图片表达的内容。",
            recommendation="为有信息价值的图片编写准确 alt；纯装饰图片可使用空 alt 而不是无语义堆词。",
            affected_count=missing_alt_total,
            evidence={
                "pages": [
                    {
                        "url": page.url,
                        "images": page.evidence.image_count,
                        "missing_alt": page.evidence.image_alt_missing_count,
                    }
                    for page in alt_pages[:_MAX_EVIDENCE_URLS]
                ]
            },
        )
    )

    slow_pages = [page for page in html_pages if (page.response_ms or 0) >= 2000]
    findings.append(
        _finding(
            category="seo",
            dimension="性能基础",
            check_key="seo.server_response_slow",
            severity="medium" if slow_pages else "info",
            result="warn" if slow_pages else "pass",
            title="部分页面服务器响应偏慢" if slow_pages else "服务器响应基础检查正常",
            summary=(
                f"有 {len(slow_pages)} 个页面本次抓取耗时达到或超过 2000ms。该指标受扫描节点网络影响，后续需结合浏览器性能检测。"
                if slow_pages
                else "本次抓取未发现响应时间达到 2000ms 的 HTML 页面。"
            ),
            impact="高响应延迟会增加抓取成本和用户等待时间，也可能拖慢真实页面性能指标。",
            recommendation="检查源站 TTFB、缓存、数据库和 CDN；最终以浏览器阶段的真实性能指标交叉验证。",
            affected_count=len(slow_pages),
            evidence={"pages": _page_evidence(slow_pages), "threshold_ms": 2000},
        )
    )

    large_pages = [page for page in html_pages if page.response_bytes >= 1_000_000]
    findings.append(
        _finding(
            category="seo",
            dimension="性能基础",
            check_key="seo.large_html",
            severity="medium" if large_pages else "info",
            result="warn" if large_pages else "pass",
            title="存在体积较大的 HTML" if large_pages else "HTML 体积基础检查正常",
            summary=(
                f"有 {len(large_pages)} 个 HTML 响应达到或超过 1MB。"
                if large_pages
                else "扫描样本没有 HTML 响应达到 1MB。"
            ),
            impact="过大的 HTML 会增加传输、解析和渲染成本。",
            recommendation="减少重复 DOM、内联大数据和无用标记；资源文件应独立加载并压缩。",
            affected_count=len(large_pages),
            evidence={"pages": _page_evidence(large_pages), "threshold_bytes": 1_000_000},
        )
    )

    thin_pages = [page for page in html_pages if page.evidence and len(page.evidence.text) < 300]
    findings.append(
        _finding(
            category="seo",
            dimension="内容与媒体基础",
            check_key="seo.thin_visible_text",
            severity="low" if thin_pages else "info",
            result="warn" if thin_pages else "pass",
            title="部分页面可读取正文偏少" if thin_pages else "静态正文基础覆盖正常",
            summary=(
                f"有 {len(thin_pages)} 个 HTML 页面在原始 HTML 中可提取正文少于 300 个字符。"
                if thin_pages
                else "扫描样本中的 HTML 页面均可提取至少 300 个字符的静态正文。"
            ),
            impact="正文过少可能是内容确实不足，也可能说明核心内容依赖 JavaScript 渲染。",
            recommendation="确认重要页面是否提供充分正文；后续浏览器检测应对比原始 HTML 与渲染后 DOM。",
            affected_count=len(thin_pages),
            evidence={"pages": _urls(thin_pages), "threshold_characters": 300},
        )
    )

    invalid_jsonld_pages = [
        page for page in html_pages if page.evidence and page.evidence.jsonld_invalid_count > 0
    ]
    invalid_jsonld_total = sum(page.evidence.jsonld_invalid_count for page in invalid_jsonld_pages)
    findings.append(
        _finding(
            category="seo",
            dimension="结构化数据",
            check_key="seo.jsonld_validity",
            severity="high" if invalid_jsonld_pages else "info",
            result="fail" if invalid_jsonld_pages else "pass",
            title="存在无法解析的 JSON-LD" if invalid_jsonld_pages else "JSON-LD 语法基础检查通过",
            summary=(
                f"发现 {invalid_jsonld_total} 个无法解析的 JSON-LD 区块，涉及 {len(invalid_jsonld_pages)} 个页面。"
                if invalid_jsonld_pages
                else "已扫描页面中的 JSON-LD 区块未发现 JSON 语法解析失败。"
            ),
            impact="无效 JSON-LD 无法被可靠解析，结构化实体和内容信号可能失效。",
            recommendation="修复 JSON 语法、转义和数据类型，并使用对应 Schema 类型的验证工具复核字段。",
            affected_count=invalid_jsonld_total,
            evidence={
                "pages": [
                    {"url": page.url, "invalid_blocks": page.evidence.jsonld_invalid_count}
                    for page in invalid_jsonld_pages[:_MAX_EVIDENCE_URLS]
                ]
            },
        )
    )

    incoming = Counter(link.destination_url for link in result.links if link.is_internal)
    sitemap_orphans = [
        page
        for page in html_pages
        if page.source == "sitemap" and incoming.get(page.url, 0) == 0
    ]
    findings.append(
        _finding(
            category="seo",
            dimension="网站结构与内链",
            check_key="seo.sitemap_orphan_sample",
            severity="low" if sitemap_orphans else "info",
            result="warn" if sitemap_orphans else "pass",
            title="Sitemap 页面在扫描样本中缺少内链入口" if sitemap_orphans else "Sitemap 页面内链发现正常",
            summary=(
                f"有 {len(sitemap_orphans)} 个由 Sitemap 发现的页面，在本次已扫描页面中没有发现指向它们的站内链接。"
                if sitemap_orphans
                else "本次已扫描的 Sitemap 页面均至少发现一个站内链接入口或属于首页。"
            ),
            impact="缺少内部链接的页面更难从网站结构中被持续发现，也可能意味着信息架构孤立。",
            recommendation="检查这些页面是否应从导航、分类、正文或相关推荐获得合理内链。由于本次扫描有页数上限，应结合完整爬取复核。",
            affected_count=len(sitemap_orphans),
            evidence={"pages": _urls(sitemap_orphans), "scope": "scanned_sample"},
        )
    )

    # ---------------- GEO: AI search crawl accessibility ----------------
    robots = _robots_parser(result)
    ai_bots = (
        ("OAI-SearchBot", "ChatGPT 搜索", "geo.ai_crawl.openai"),
        ("PerplexityBot", "Perplexity 搜索", "geo.ai_crawl.perplexity"),
        ("Claude-SearchBot", "Claude 搜索", "geo.ai_crawl.claude"),
    )
    blocked_bot_count = 0
    for user_agent, display_name, check_key in ai_bots:
        if robots is None:
            findings.append(
                _finding(
                    category="geo",
                    dimension="AI抓取可访问性",
                    check_key=check_key,
                    severity="high",
                    result="warn",
                    title=f"无法验证 {display_name} 抓取规则",
                    summary="robots.txt 无法获取，因此无法确定该 AI 搜索爬虫的路径访问策略。",
                    impact="无法验证抓取策略意味着 GEO 检测无法确认该搜索系统是否被 robots 规则阻断。",
                    recommendation="先修复 robots.txt 可访问性，再重新检测各 AI 搜索爬虫规则。",
                    evidence={"user_agent": user_agent, "robots_status": result.robots_status},
                )
            )
            continue

        blocked = [page for page in html_pages if not robots.can_fetch(user_agent, page.url)]
        if blocked:
            blocked_bot_count += 1
        findings.append(
            _finding(
                category="geo",
                dimension="AI抓取可访问性",
                check_key=check_key,
                severity="high" if blocked else "info",
                result="fail" if blocked else "pass",
                title=(
                    f"{display_name} 被 robots.txt 阻止部分页面"
                    if blocked
                    else f"{display_name} robots 规则允许扫描样本"
                ),
                summary=(
                    f"本次扫描样本中有 {len(blocked)} 个 HTML 页面对 {user_agent} 不允许抓取。"
                    if blocked
                    else f"本次扫描样本未发现 robots.txt 对 {user_agent} 的路径阻断。"
                ),
                impact="阻止搜索型 AI 爬虫可能降低对应平台发现、索引和引用公开网页内容的能力。",
                recommendation=f"如果希望提升 {display_name} 的公开网页可发现性，检查并调整 {user_agent} 的 robots.txt 规则；不要为了 GEO 开放原本应受保护的私有路径。",
                affected_count=len(blocked),
                evidence={"user_agent": user_agent, "pages": _urls(blocked)},
            )
        )

    if robots is not None:
        findings.append(
            _finding(
                category="geo",
                dimension="AI抓取可访问性",
                check_key="geo.ai_crawl.coverage",
                severity="critical" if blocked_bot_count == len(ai_bots) else ("high" if blocked_bot_count else "info"),
                result="fail" if blocked_bot_count else "pass",
                title="主要 AI 搜索爬虫存在阻断" if blocked_bot_count else "主要 AI 搜索爬虫 robots 基础检查通过",
                summary=(
                    f"检测的 {len(ai_bots)} 类主要 AI 搜索爬虫中，有 {blocked_bot_count} 类在扫描样本存在 robots 阻断。"
                    if blocked_bot_count
                    else f"检测的 {len(ai_bots)} 类主要 AI 搜索爬虫均未在扫描样本发现 robots 阻断。"
                ),
                impact="多个 AI 搜索入口同时被阻断会显著降低官网内容进入生成式搜索答案链路的机会。",
                recommendation="根据业务公开范围分别配置搜索型 AI 爬虫，而不是使用过宽的 User-agent: * 全站封禁。",
                evidence={"tested_user_agents": [item[0] for item in ai_bots]},
            )
        )

    geo_noindex = noindex_pages
    findings.append(
        _finding(
            category="geo",
            dimension="AI抓取可访问性",
            check_key="geo.noindex",
            severity=("critical" if root_noindex else "high") if geo_noindex else "info",
            result="fail" if geo_noindex else "pass",
            title="核心内容存在 noindex 风险" if geo_noindex else "未发现 noindex 阻断 GEO 内容",
            summary=(
                f"扫描样本有 {len(geo_noindex)} 个页面声明 noindex。"
                if geo_noindex
                else "扫描样本未发现 HTML 页面声明 noindex。"
            ),
            impact="即使爬虫能访问页面，noindex 也可能阻止页面进入依赖索引的搜索发现链路。",
            recommendation="确认公开品牌、产品、服务、FAQ 和内容页面不要误用 noindex。",
            affected_count=len(geo_noindex),
            evidence={"pages": _urls(geo_noindex)},
        )
    )

    # ---------------- GEO: entity machine readability ----------------
    schema_types = Counter()
    all_entities: list[tuple[CrawledPage, dict[str, object]]] = []
    for page in html_pages:
        for schema_type in page.evidence.schema_types:
            schema_types[schema_type.lower()] += 1
        for entity in page.evidence.schema_entities:
            if isinstance(entity, dict):
                all_entities.append((page, entity))

    organization_types = {
        "organization",
        "corporation",
        "localbusiness",
        "professionalservice",
        "store",
    }
    organization_entities = [
        (page, entity)
        for page, entity in all_entities
        if any(str(value).lower() in organization_types for value in entity.get("types", []))
    ]
    org_ok = bool(organization_entities)
    findings.append(
        _finding(
            category="geo",
            dimension="主体实体清晰度",
            check_key="geo.organization_schema",
            severity="high" if not org_ok else "info",
            result="fail" if not org_ok else "pass",
            title="未发现企业主体结构化数据" if not org_ok else "已发现企业主体结构化数据",
            summary=(
                "扫描页面没有发现 Organization、Corporation 或 LocalBusiness 等企业主体 JSON-LD。"
                if not org_ok
                else f"发现 {len(organization_entities)} 个企业主体相关 JSON-LD 实体。"
            ),
            impact="清晰的企业实体结构有助于机器区分公司、品牌、官网和业务主体之间的关系。",
            recommendation="在官网提供准确的 Organization/Corporation/LocalBusiness JSON-LD，并包含真实名称、官网 URL、Logo、联系方式和可验证的 sameAs。",
            affected_count=0 if org_ok else 1,
            evidence={
                "entities": [
                    {"url": page.url, "entity": entity}
                    for page, entity in organization_entities[:20]
                ]
            },
        )
    )

    incomplete_org_entities: list[tuple[CrawledPage, dict[str, object], list[str]]] = []
    for page, entity in organization_entities:
        missing: list[str] = []
        if not str(entity.get("name", "")).strip():
            missing.append("name")
        if not str(entity.get("url", "")).strip():
            missing.append("url")
        same_as = entity.get("same_as")
        if not isinstance(same_as, list) or not same_as:
            missing.append("sameAs")
        if missing:
            incomplete_org_entities.append((page, entity, missing))
    findings.append(
        _finding(
            category="geo",
            dimension="主体实体清晰度",
            check_key="geo.organization_schema_completeness",
            severity="medium" if incomplete_org_entities else "info",
            result="warn" if incomplete_org_entities else ("pass" if organization_entities else "info"),
            title="企业主体结构化信息不完整" if incomplete_org_entities else "企业主体结构化信息基础完整",
            summary=(
                f"有 {len(incomplete_org_entities)} 个企业主体实体缺少 name、url 或 sameAs 等基础字段。"
                if incomplete_org_entities
                else (
                    "已发现的企业主体实体均包含 name、url 和至少一个 sameAs。"
                    if organization_entities
                    else "当前未发现企业主体实体，因此无法继续检查字段完整度。"
                )
            ),
            impact="主体字段不完整会降低跨页面、跨平台实体对齐的清晰度。",
            recommendation="优先补全企业正式名称、官网规范 URL 与权威外部主页 sameAs；所有值必须与真实主体一致。",
            affected_count=len(incomplete_org_entities),
            evidence={
                "entities": [
                    {"url": page.url, "missing": missing, "entity": entity}
                    for page, entity, missing in incomplete_org_entities[:20]
                ]
            },
        )
    )

    website_schema_ok = schema_types.get("website", 0) > 0
    findings.append(
        _finding(
            category="geo",
            dimension="机器可理解性",
            check_key="geo.website_schema",
            severity="medium" if not website_schema_ok else "info",
            result="warn" if not website_schema_ok else "pass",
            title="未发现 WebSite 结构化数据" if not website_schema_ok else "已发现 WebSite 结构化数据",
            summary=(
                "扫描页面没有发现 WebSite JSON-LD。"
                if not website_schema_ok
                else f"WebSite 类型在 {schema_types.get('website', 0)} 个页面中出现。"
            ),
            impact="WebSite 结构化数据可辅助机器明确站点名称、规范 URL 与站内搜索等网站级信息。",
            recommendation="在首页配置与真实站点一致的 WebSite JSON-LD；不要添加不存在或不可用的功能字段。",
            affected_count=0 if website_schema_ok else 1,
            evidence={"schema_type_counts": dict(schema_types)},
        )
    )

    root_entity_ready = bool(
        root
        and root.evidence
        and root.evidence.title.strip()
        and root.evidence.meta_description.strip()
        and root.evidence.headings.get("h1")
        and len(root.evidence.text) >= 300
    )
    findings.append(
        _finding(
            category="geo",
            dimension="主体实体清晰度",
            check_key="geo.homepage_identity_surface",
            severity="high" if not root_entity_ready else "info",
            result="warn" if not root_entity_ready else "pass",
            title="首页主体表达基础不足" if not root_entity_ready else "首页主体表达基础完整",
            summary=(
                "首页至少有一项缺失：title、meta description、H1 或足量静态正文。"
                if not root_entity_ready
                else "首页同时具备 title、description、H1 与至少 300 个字符的静态可读正文。"
            ),
            impact="首页通常承担品牌/企业是谁、做什么、提供什么的第一层机器理解入口。",
            recommendation="让首页用明确文本表达企业/品牌名称、核心业务、主要产品或服务，并避免关键信息只存在于图片或脚本交互中。",
            affected_count=0 if root_entity_ready else 1,
            evidence={
                "root_url": root.url if root else result.root_url,
                "title": root.evidence.title if root and root.evidence else "",
                "description_present": bool(root and root.evidence and root.evidence.meta_description),
                "h1": root.evidence.headings.get("h1", []) if root and root.evidence else [],
                "text_characters": len(root.evidence.text) if root and root.evidence else 0,
            },
        )
    )

    # ---------------- GEO: structured content coverage by page intent ----------------
    faq_pages = _probable_pages(html_pages, ("/faq", "faq", "常见问题", "问答", "questions"))
    faq_missing_schema = [
        page for page in faq_pages if "faqpage" not in {item.lower() for item in page.evidence.schema_types}
    ]
    findings.append(
        _finding(
            category="geo",
            dimension="内容可引用性",
            check_key="geo.faq_schema",
            severity="medium" if faq_missing_schema else "info",
            result="warn" if faq_missing_schema else ("pass" if faq_pages else "info"),
            title="FAQ 页面缺少 FAQPage 结构化数据" if faq_missing_schema else "FAQ 结构化数据基础检查完成",
            summary=(
                f"识别到 {len(faq_pages)} 个可能的 FAQ/问答页面，其中 {len(faq_missing_schema)} 个未发现 FAQPage 类型。"
                if faq_pages
                else "本次扫描未识别出明显的 FAQ/问答页面，因此不做强制扣分。"
            ),
            impact="结构清晰的问答内容更容易被机器识别为具体问题与答案；结构化数据可进一步明确页面语义。",
            recommendation="如果页面确实是公开 FAQ，请保证页面正文真实展示问题与答案，并使用与可见内容一致的 FAQPage 标记。",
            affected_count=len(faq_missing_schema),
            evidence={"pages": _urls(faq_missing_schema)},
        )
    )

    product_pages = _probable_pages(
        html_pages,
        ("/product", "/products", "/service", "/services", "产品", "服务", "solution", "解决方案"),
    )
    product_types = {"product", "service", "offer"}
    product_missing_schema = [
        page
        for page in product_pages
        if not ({item.lower() for item in page.evidence.schema_types} & product_types)
    ]
    findings.append(
        _finding(
            category="geo",
            dimension="主体实体清晰度",
            check_key="geo.product_service_schema",
            severity="medium" if product_missing_schema else "info",
            result="warn" if product_missing_schema else ("pass" if product_pages else "info"),
            title="产品/服务页面缺少实体结构化数据" if product_missing_schema else "产品/服务实体标记基础检查完成",
            summary=(
                f"识别到 {len(product_pages)} 个可能的产品/服务页面，其中 {len(product_missing_schema)} 个未发现 Product、Service 或 Offer 类型。"
                if product_pages
                else "本次扫描未识别出明显的产品/服务页面，因此不做强制扣分。"
            ),
            impact="明确的产品和服务实体能帮助机器区分企业主体与其具体供给内容。",
            recommendation="对真实产品或服务页面使用与页面可见内容一致的 Product/Service/Offer 数据；不要为不存在的价格、库存或评分造数据。",
            affected_count=len(product_missing_schema),
            evidence={"pages": _urls(product_missing_schema)},
        )
    )

    article_pages = _probable_pages(
        html_pages,
        ("/blog", "/news", "/article", "/articles", "新闻", "资讯", "博客", "文章"),
    )
    article_types = {"article", "newsarticle", "blogposting"}
    article_missing_schema = [
        page
        for page in article_pages
        if not ({item.lower() for item in page.evidence.schema_types} & article_types)
    ]
    findings.append(
        _finding(
            category="geo",
            dimension="可信度与证据",
            check_key="geo.article_schema",
            severity="low" if article_missing_schema else "info",
            result="warn" if article_missing_schema else ("pass" if article_pages else "info"),
            title="内容页面缺少 Article 类结构化数据" if article_missing_schema else "内容页面结构化数据基础检查完成",
            summary=(
                f"识别到 {len(article_pages)} 个可能的新闻/文章页面，其中 {len(article_missing_schema)} 个未发现 Article、NewsArticle 或 BlogPosting。"
                if article_pages
                else "本次扫描未识别出明显的新闻/文章页面，因此不做强制扣分。"
            ),
            impact="文章类结构化数据可明确内容类型、作者和发布时间等机器可读信息。",
            recommendation="对真实文章补充与页面一致的 Article 类数据，并准确提供 headline、author、datePublished、dateModified 等字段。",
            affected_count=len(article_missing_schema),
            evidence={"pages": _urls(article_missing_schema)},
        )
    )

    sparse_structure_pages = [
        page
        for page in html_pages
        if len(page.evidence.text) >= 1500
        and page.evidence.paragraph_count < 3
        and page.evidence.list_count == 0
        and page.evidence.table_count == 0
    ]
    findings.append(
        _finding(
            category="geo",
            dimension="机器可理解性",
            check_key="geo.content_structure",
            severity="low" if sparse_structure_pages else "info",
            result="warn" if sparse_structure_pages else "pass",
            title="部分长内容缺少明显结构" if sparse_structure_pages else "长内容基础结构检查正常",
            summary=(
                f"有 {len(sparse_structure_pages)} 个静态正文较长的页面，但几乎没有段落、列表或表格结构。"
                if sparse_structure_pages
                else "未发现正文较长但完全缺少基础内容结构的页面。"
            ),
            impact="清晰的段落、标题、列表和表格有助于机器切分内容并抽取独立事实片段。",
            recommendation="根据内容本身使用真实的标题、段落、列表和表格结构，不要为了评分机械堆叠标签。",
            affected_count=len(sparse_structure_pages),
            evidence={"pages": _urls(sparse_structure_pages)},
        )
    )

    schema_covered = [page for page in html_pages if page.evidence.schema_types]
    coverage = (len(schema_covered) / len(html_pages)) if html_pages else 0.0
    findings.append(
        _finding(
            category="geo",
            dimension="机器可理解性",
            check_key="geo.structured_data_coverage",
            severity="info",
            result="info",
            title="结构化数据覆盖情况",
            summary=f"{len(html_pages)} 个 HTML 页面中有 {len(schema_covered)} 个检测到 JSON-LD Schema 类型，覆盖率约 {coverage:.0%}。",
            impact="覆盖率本身不是排名指标；它用于帮助定位哪些页面已经具备机器可读实体结构，哪些页面需要结合页面类型进一步判断。",
            recommendation="只在页面确实对应相应实体或内容类型时添加结构化数据，优先保证真实性和字段完整度。",
            evidence={
                "html_pages": len(html_pages),
                "covered_pages": len(schema_covered),
                "coverage_ratio": round(coverage, 4),
                "schema_type_counts": dict(schema_types),
            },
        )
    )

    return findings
