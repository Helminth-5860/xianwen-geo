from __future__ import annotations

from collections import defaultdict

from .browser_runner import BrowserPageResult
from .rules import FindingDraft

RULESET_VERSION = "browser-v1"
_MAX_EVIDENCE = 30


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
        method="browser",
        rule_version=RULESET_VERSION,
    )


def _rows(results: list[BrowserPageResult], predicate) -> list[BrowserPageResult]:
    return [item for item in results if predicate(item)]


def _evidence(results: list[BrowserPageResult]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in results[:_MAX_EVIDENCE]:
        rows.append(
            {
                "url": item.url,
                "profile": item.profile,
                "status": item.status,
                "ttfb_ms": item.ttfb_ms,
                "fcp_ms": item.fcp_ms,
                "lcp_ms": item.lcp_ms,
                "cls": item.cls,
                "tbt_ms": item.tbt_ms,
                "requests": item.request_count,
                "transfer_bytes": item.transfer_bytes,
                "failure_code": item.failure_code,
            }
        )
    return rows


def _performance_finding(
    *,
    successful: list[BrowserPageResult],
    metric: str,
    label: str,
    warning: float,
    poor: float,
    check_key: str,
    impact: str,
    recommendation: str,
) -> FindingDraft:
    values = [item for item in successful if getattr(item, metric) is not None]
    poor_rows = [item for item in values if float(getattr(item, metric)) > poor]
    warning_rows = [
        item for item in values if warning < float(getattr(item, metric)) <= poor
    ]
    affected = poor_rows or warning_rows
    if poor_rows:
        severity, result = "high", "fail"
        title = f"部分页面实验室 {label} 表现较差"
    elif warning_rows:
        severity, result = "medium", "warn"
        title = f"部分页面实验室 {label} 有优化空间"
    else:
        severity, result = "info", "pass"
        title = f"实验室 {label} 基础检查正常"
    summary = (
        f"检测到 {len(poor_rows)} 个明显偏慢、{len(warning_rows)} 个需要优化的浏览器样本。"
        if affected
        else f"本次浏览器样本未发现超过预警阈值的 {label}。"
    )
    return _finding(
        category="technical",
        dimension="浏览器性能",
        check_key=check_key,
        severity=severity,
        result=result,
        title=title,
        summary=summary,
        impact=impact,
        recommendation=recommendation,
        affected_count=len(affected),
        evidence={
            "warning_threshold": warning,
            "poor_threshold": poor,
            "samples": _evidence(affected),
            "measurement_scope": "实验室浏览器快照，不等同于真实用户75分位Core Web Vitals",
        },
    )


def evaluate_browser_checks(results: list[BrowserPageResult]) -> list[FindingDraft]:
    findings: list[FindingDraft] = []
    successful = [item for item in results if item.status == "succeeded"]
    failed = [item for item in results if item.status != "succeeded"]

    findings.append(
        _finding(
            category="technical",
            dimension="浏览器渲染",
            check_key="browser.execution_coverage",
            severity="high" if failed and not successful else ("medium" if failed else "info"),
            result="fail" if failed and not successful else ("warn" if failed else "pass"),
            title="浏览器检测存在失败样本" if failed else "浏览器检测样本均成功完成",
            summary=(
                f"共 {len(results)} 个浏览器样本，成功 {len(successful)} 个，失败 {len(failed)} 个。"
            ),
            impact="浏览器样本失败会降低对 JavaScript 渲染、资源加载和实验室性能的判断完整度。",
            recommendation="优先检查超时、浏览器运行环境、目标站点反自动化策略及页面网络错误。",
            affected_count=len(failed),
            evidence={"failed_samples": _evidence(failed)},
        )
    )

    if not successful:
        return findings

    js_dependent = _rows(
        successful,
        lambda item: (
            (item.static_text_characters < 300 and item.rendered_text_characters >= 1000)
            or (
                item.text_growth_ratio is not None
                and item.text_growth_ratio >= 3.0
                and item.text_delta >= 1000
            )
        ),
    )
    findings.append(
        _finding(
            category="geo",
            dimension="机器可理解性",
            check_key="browser.js_text_dependency",
            severity="high" if js_dependent else "info",
            result="warn" if js_dependent else "pass",
            title="关键正文高度依赖 JavaScript 渲染" if js_dependent else "正文未发现明显的重度 JavaScript 依赖",
            summary=(
                f"有 {len(js_dependent)} 个浏览器样本在执行 JavaScript 后才出现大量正文。"
                if js_dependent
                else "静态 HTML 与浏览器可见正文的体量差异未达到重度依赖阈值。"
            ),
            impact="搜索或 AI 抓取系统的执行能力、资源预算和渲染时机会影响其能否稳定看到延迟出现的正文。",
            recommendation="核心品牌、产品、服务和事实信息优先在服务器返回的 HTML 中直接存在；交互增强可以继续使用 JavaScript。",
            affected_count=len(js_dependent),
            evidence={
                "samples": [
                    {
                        "url": item.url,
                        "profile": item.profile,
                        "static_text": item.static_text_characters,
                        "rendered_text": item.rendered_text_characters,
                        "delta": item.text_delta,
                        "growth_ratio": item.text_growth_ratio,
                    }
                    for item in js_dependent[:_MAX_EVIDENCE]
                ]
            },
        )
    )

    dynamic_metadata = _rows(
        successful,
        lambda item: (
            (item.rendered_title.strip() and item.rendered_title.strip() != item.static_title.strip())
            or (
                item.rendered_meta_description.strip()
                and item.rendered_meta_description.strip() != item.static_meta_description.strip()
            )
            or (
                item.rendered_canonical_url.strip()
                and item.rendered_canonical_url.strip() != item.static_canonical_url.strip()
            )
        ),
    )
    findings.append(
        _finding(
            category="seo",
            dimension="页面基础SEO",
            check_key="browser.dynamic_metadata",
            severity="medium" if dynamic_metadata else "info",
            result="warn" if dynamic_metadata else "pass",
            title="部分 SEO 元数据依赖浏览器执行后变化" if dynamic_metadata else "静态与渲染后的核心 SEO 元数据一致",
            summary=(
                f"有 {len(dynamic_metadata)} 个浏览器样本的 title、description 或 canonical 在渲染后与静态 HTML 不一致。"
                if dynamic_metadata
                else "未发现 title、description、canonical 在浏览器渲染后发生明显变化。"
            ),
            impact="不同抓取器对 JavaScript 的执行能力不同，动态注入核心 SEO 元数据可能造成抓取结果不一致。",
            recommendation="重要 title、description 与 canonical 尽量由服务器直接输出，并保证客户端渲染不改变其语义。",
            affected_count=len(dynamic_metadata),
            evidence={
                "samples": [
                    {
                        "url": item.url,
                        "profile": item.profile,
                        "static_title": item.static_title,
                        "rendered_title": item.rendered_title,
                        "static_description": item.static_meta_description,
                        "rendered_description": item.rendered_meta_description,
                        "static_canonical": item.static_canonical_url,
                        "rendered_canonical": item.rendered_canonical_url,
                    }
                    for item in dynamic_metadata[:_MAX_EVIDENCE]
                ]
            },
        )
    )

    dynamic_schema = _rows(
        successful,
        lambda item: bool(
            {value.lower() for value in item.rendered_schema_types}
            - {value.lower() for value in item.static_schema_types}
        ),
    )
    findings.append(
        _finding(
            category="geo",
            dimension="机器可理解性",
            check_key="browser.dynamic_schema",
            severity="medium" if dynamic_schema else "info",
            result="warn" if dynamic_schema else "pass",
            title="部分结构化数据仅在 JavaScript 执行后出现" if dynamic_schema else "结构化数据未发现明显的客户端依赖",
            summary=(
                f"有 {len(dynamic_schema)} 个浏览器样本在渲染后出现静态 HTML 中不存在的 Schema 类型。"
                if dynamic_schema
                else "浏览器渲染没有新增静态抓取无法看到的关键 Schema 类型。"
            ),
            impact="仅客户端生成的实体结构化数据可能无法被所有抓取系统稳定获取。",
            recommendation="Organization、Product、Service、Article 等关键结构化数据优先随服务器 HTML 一起输出。",
            affected_count=len(dynamic_schema),
            evidence={
                "samples": [
                    {
                        "url": item.url,
                        "profile": item.profile,
                        "static_schema": list(item.static_schema_types),
                        "rendered_schema": list(item.rendered_schema_types),
                    }
                    for item in dynamic_schema[:_MAX_EVIDENCE]
                ]
            },
        )
    )

    blocked = _rows(successful, lambda item: item.blocked_request_count > 0)
    findings.append(
        _finding(
            category="technical",
            dimension="浏览器安全与网络",
            check_key="browser.blocked_private_requests",
            severity="high" if blocked else "info",
            result="warn" if blocked else "pass",
            title="页面触发了受安全策略拦截的网络请求" if blocked else "未发现受限网络请求",
            summary=(
                f"有 {len(blocked)} 个浏览器样本尝试请求非 HTTP(S)、非标准端口、私有或不可验证网络地址，已被显问安全策略阻断。"
                if blocked
                else "浏览器检测期间未触发显问的受限网络地址拦截。"
            ),
            impact="异常网络依赖可能导致页面在不同抓取环境中加载失败，也可能形成安全风险。",
            recommendation="检查前端配置、接口地址和第三方脚本，公开官网不应依赖 localhost、内网 IP 或非公开网络资源。",
            affected_count=len(blocked),
            evidence={"samples": _evidence(blocked)},
        )
    )

    browser_errors = _rows(
        successful,
        lambda item: item.page_error_count > 0 or item.console_error_count >= 3,
    )
    findings.append(
        _finding(
            category="technical",
            dimension="浏览器渲染",
            check_key="browser.javascript_errors",
            severity="medium" if browser_errors else "info",
            result="warn" if browser_errors else "pass",
            title="浏览器执行发现 JavaScript 错误" if browser_errors else "未发现明显 JavaScript 执行错误",
            summary=(
                f"有 {len(browser_errors)} 个样本存在页面异常或较多 console error。"
                if browser_errors
                else "浏览器样本未达到 JavaScript 错误告警阈值。"
            ),
            impact="JavaScript 错误可能导致正文、导航、结构化数据或关键资源无法正常渲染。",
            recommendation="根据浏览器错误栈和失败资源定位前端异常，优先修复影响核心内容渲染的问题。",
            affected_count=len(browser_errors),
            evidence={
                "samples": [
                    {
                        "url": item.url,
                        "profile": item.profile,
                        "console_errors": item.console_error_count,
                        "page_errors": item.page_error_count,
                        "details": item.evidence or {},
                    }
                    for item in browser_errors[:10]
                ]
            },
        )
    )

    resource_failures = _rows(
        successful,
        lambda item: item.failed_request_count >= 3
        and item.failed_request_count / max(1, item.request_count) >= 0.05,
    )
    findings.append(
        _finding(
            category="technical",
            dimension="资源加载",
            check_key="browser.failed_resources",
            severity="medium" if resource_failures else "info",
            result="warn" if resource_failures else "pass",
            title="部分页面存在较明显的资源加载失败" if resource_failures else "资源加载失败率基础检查正常",
            summary=(
                f"有 {len(resource_failures)} 个样本的失败请求数和失败比例达到告警阈值。"
                if resource_failures
                else "未发现失败请求比例明显偏高的浏览器样本。"
            ),
            impact="CSS、JS、图片、字体或接口加载失败可能造成页面内容缺失和抓取环境差异。",
            recommendation="修复 4xx/5xx、跨域、证书、DNS 和第三方资源稳定性问题，并移除无效资源引用。",
            affected_count=len(resource_failures),
            evidence={"samples": _evidence(resource_failures)},
        )
    )

    heavy_pages = _rows(
        successful,
        lambda item: item.request_count > 150 or item.transfer_bytes > 5 * 1024 * 1024,
    )
    findings.append(
        _finding(
            category="technical",
            dimension="资源加载",
            check_key="browser.page_weight",
            severity="medium" if heavy_pages else "info",
            result="warn" if heavy_pages else "pass",
            title="部分页面请求数或传输体积较大" if heavy_pages else "页面请求数与传输体积基础检查正常",
            summary=(
                f"有 {len(heavy_pages)} 个样本超过 150 个网络请求或约 5MB 实际编码传输量。"
                if heavy_pages
                else "本次浏览器样本未超过页面体积基础告警阈值。"
            ),
            impact="过重页面会增加加载时间、抓取资源成本和移动网络下的失败概率。",
            recommendation="压缩图片和脚本、拆除无用第三方依赖、启用缓存并减少非关键首屏资源。",
            affected_count=len(heavy_pages),
            evidence={"samples": _evidence(heavy_pages)},
        )
    )

    large_dom = _rows(successful, lambda item: item.dom_nodes > 2500)
    findings.append(
        _finding(
            category="technical",
            dimension="浏览器渲染",
            check_key="browser.dom_size",
            severity="low" if large_dom else "info",
            result="warn" if large_dom else "pass",
            title="部分页面 DOM 规模较大" if large_dom else "DOM 规模基础检查正常",
            summary=(
                f"有 {len(large_dom)} 个样本的 DOM 节点数超过 2500。"
                if large_dom
                else "浏览器样本未发现明显超大的 DOM。"
            ),
            impact="DOM 过大会增加样式计算、布局和脚本处理成本，也会增加机器解析噪音。",
            recommendation="减少无意义嵌套、隐藏模板和重复组件，保留清晰的语义结构。",
            affected_count=len(large_dom),
            evidence={"samples": _evidence(large_dom)},
        )
    )

    rendered_alt_missing = _rows(
        successful,
        lambda item: item.visible_image_count > 0 and item.images_without_alt > 0,
    )
    findings.append(
        _finding(
            category="seo",
            dimension="内容与媒体基础",
            check_key="browser.visible_image_alt",
            severity="low" if rendered_alt_missing else "info",
            result="warn" if rendered_alt_missing else "pass",
            title="渲染后的可见图片仍有 Alt 缺失" if rendered_alt_missing else "渲染后可见图片 Alt 基础检查正常",
            summary=(
                f"有 {len(rendered_alt_missing)} 个浏览器样本存在可见图片缺少 alt。"
                if rendered_alt_missing
                else "浏览器渲染后的可见图片未发现 Alt 缺失样本。"
            ),
            impact="Alt 有助于图片语义理解、无障碍访问和图片搜索。",
            recommendation="为承载内容信息的图片提供准确简洁的 Alt；纯装饰图片可使用空 Alt。",
            affected_count=len(rendered_alt_missing),
            evidence={
                "samples": [
                    {
                        "url": item.url,
                        "profile": item.profile,
                        "visible_images": item.visible_image_count,
                        "missing_alt": item.images_without_alt,
                    }
                    for item in rendered_alt_missing[:_MAX_EVIDENCE]
                ]
            },
        )
    )

    findings.extend(
        [
            _performance_finding(
                successful=successful,
                metric="ttfb_ms",
                label="TTFB",
                warning=800,
                poor=1800,
                check_key="browser.performance_ttfb",
                impact="服务端响应慢会延迟 HTML 获取和后续所有渲染资源。",
                recommendation="优化源站响应、缓存、数据库和 CDN，降低首字节等待时间。",
            ),
            _performance_finding(
                successful=successful,
                metric="fcp_ms",
                label="FCP",
                warning=1800,
                poor=3000,
                check_key="browser.performance_fcp",
                impact="首次内容绘制过慢会延迟用户和浏览器看到有效页面内容。",
                recommendation="优化首屏关键资源、字体、CSS 和服务端响应。",
            ),
            _performance_finding(
                successful=successful,
                metric="lcp_ms",
                label="LCP",
                warning=2500,
                poor=4000,
                check_key="browser.performance_lcp",
                impact="较慢的最大内容绘制通常意味着首屏核心内容出现较晚。",
                recommendation="优化首屏主图、字体、关键 CSS、服务端响应与资源优先级。",
            ),
            _performance_finding(
                successful=successful,
                metric="cls",
                label="CLS",
                warning=0.1,
                poor=0.25,
                check_key="browser.performance_cls",
                impact="布局偏移会降低视觉稳定性，并影响页面使用体验。",
                recommendation="为图片、广告和异步组件预留尺寸，避免加载后突然插入内容。",
            ),
            _performance_finding(
                successful=successful,
                metric="tbt_ms",
                label="TBT",
                warning=200,
                poor=600,
                check_key="browser.performance_tbt",
                impact="主线程长任务过多会阻塞渲染和交互。",
                recommendation="拆分长任务、减少 JavaScript 执行量并延迟非关键脚本。",
            ),
        ]
    )

    by_page: dict[str, list[BrowserPageResult]] = defaultdict(list)
    for item in successful:
        by_page[item.page_id].append(item)
    parity_issues: list[dict[str, object]] = []
    for page_results in by_page.values():
        mobile = next((x for x in page_results if x.profile == "mobile"), None)
        desktop = next((x for x in page_results if x.profile == "desktop"), None)
        if not mobile or not desktop:
            continue
        maximum = max(mobile.rendered_text_characters, desktop.rendered_text_characters, 1)
        difference = abs(mobile.rendered_text_characters - desktop.rendered_text_characters)
        if difference >= 500 and difference / maximum >= 0.25:
            parity_issues.append(
                {
                    "url": mobile.url,
                    "mobile_text": mobile.rendered_text_characters,
                    "desktop_text": desktop.rendered_text_characters,
                    "difference": difference,
                }
            )
    findings.append(
        _finding(
            category="geo",
            dimension="机器可理解性",
            check_key="browser.mobile_desktop_content_parity",
            severity="medium" if parity_issues else "info",
            result="warn" if parity_issues else "pass",
            title="部分页面移动端与桌面端正文差异较大" if parity_issues else "移动端与桌面端正文一致性基础检查正常",
            summary=(
                f"有 {len(parity_issues)} 个页面的两种视口正文字符量差异超过 25% 且超过 500 字符。"
                if parity_issues
                else "未发现移动端与桌面端正文体量显著不一致的页面。"
            ),
            impact="不同设备展示完全不同的核心内容会增加搜索与 AI 抓取结果的不确定性。",
            recommendation="响应式布局可以不同，但核心品牌、产品、服务和事实信息应在不同设备上保持一致可访问。",
            affected_count=len(parity_issues),
            evidence={"pages": parity_issues[:_MAX_EVIDENCE]},
        )
    )

    return findings
