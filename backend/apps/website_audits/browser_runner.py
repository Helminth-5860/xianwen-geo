from __future__ import annotations

import math
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from apps.web_sources.url_security import canonicalize_url, resolve_and_validate

from .parser import parse_html

_PERF_INIT_SCRIPT = r"""
(() => {
  const metrics = {lcp: null, cls: 0, tbt: 0};
  Object.defineProperty(window, '__xianwenAuditMetrics', {value: metrics, configurable: false});
  try {
    new PerformanceObserver((list) => {
      const entries = list.getEntries();
      if (entries.length) metrics.lcp = entries[entries.length - 1].startTime;
    }).observe({type: 'largest-contentful-paint', buffered: true});
  } catch (_) {}
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) metrics.cls += entry.value;
      }
    }).observe({type: 'layout-shift', buffered: true});
  } catch (_) {}
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        metrics.tbt += Math.max(0, entry.duration - 50);
      }
    }).observe({type: 'longtask', buffered: true});
  } catch (_) {}
  // Browser audits do not need persistent realtime connections. Blocking them also
  // prevents a page from using WebSocket/EventSource as a side channel to private networks.
  try {
    window.WebSocket = class XianwenBlockedWebSocket {
      constructor() { throw new Error('XIANWEN_BROWSER_AUDIT_WEBSOCKET_BLOCKED'); }
    };
  } catch (_) {}
  try {
    window.EventSource = class XianwenBlockedEventSource {
      constructor() { throw new Error('XIANWEN_BROWSER_AUDIT_EVENTSOURCE_BLOCKED'); }
    };
  } catch (_) {}
})();
"""

_RENDER_METRICS_SCRIPT = r"""
() => {
  const nav = performance.getEntriesByType('navigation')[0] || null;
  const paints = performance.getEntriesByType('paint') || [];
  const fcp = paints.find((item) => item.name === 'first-contentful-paint');
  const xw = window.__xianwenAuditMetrics || {};
  const visibleImages = Array.from(document.images || []).filter((img) => {
    const style = getComputedStyle(img);
    const rect = img.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  });
  const headingCounts = {};
  for (let i = 1; i <= 6; i++) headingCounts['h' + i] = document.querySelectorAll('h' + i).length;
  const schemaTypes = new Set();
  const walk = (value) => {
    if (Array.isArray(value)) { value.forEach(walk); return; }
    if (!value || typeof value !== 'object') return;
    const type = value['@type'];
    if (typeof type === 'string') schemaTypes.add(type);
    if (Array.isArray(type)) type.filter((x) => typeof x === 'string').forEach((x) => schemaTypes.add(x));
    Object.values(value).forEach(walk);
  };
  for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
    try { walk(JSON.parse(node.textContent || '')); } catch (_) {}
  }
  const description = document.querySelector('meta[name="description"]')?.getAttribute('content') || '';
  const canonical = document.querySelector('link[rel~="canonical"]')?.href || '';
  const bodyText = document.body?.innerText || '';
  return {
    ttfb: nav ? Math.max(0, nav.responseStart - nav.requestStart) : null,
    dcl: nav && nav.domContentLoadedEventEnd > 0 ? nav.domContentLoadedEventEnd : null,
    load: nav && nav.loadEventEnd > 0 ? nav.loadEventEnd : null,
    fcp: fcp ? fcp.startTime : null,
    lcp: typeof xw.lcp === 'number' ? xw.lcp : null,
    cls: typeof xw.cls === 'number' ? xw.cls : null,
    tbt: typeof xw.tbt === 'number' ? xw.tbt : null,
    domNodes: document.getElementsByTagName('*').length,
    bodyText,
    title: document.title || '',
    description,
    canonical,
    schemaTypes: Array.from(schemaTypes).sort(),
    headingCounts,
    visibleImages: visibleImages.length,
    imagesWithoutAlt: visibleImages.filter((img) => !(img.getAttribute('alt') || '').trim()).length,
  };
}
"""


class BrowserRuntimeUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserPageInput:
    page_id: str
    url: str
    static_text_characters: int
    static_title: str
    static_meta_description: str
    static_canonical_url: str
    static_schema_types: tuple[str, ...]


@dataclass(frozen=True)
class BrowserPageResult:
    page_id: str
    url: str
    profile: str
    status: str
    final_url: str = ""
    navigation_ms: int | None = None
    ttfb_ms: int | None = None
    dom_content_loaded_ms: int | None = None
    load_ms: int | None = None
    fcp_ms: int | None = None
    lcp_ms: int | None = None
    cls: float | None = None
    tbt_ms: int | None = None
    request_count: int = 0
    failed_request_count: int = 0
    blocked_request_count: int = 0
    transfer_bytes: int = 0
    cross_host_request_count: int = 0
    cross_host_transfer_bytes: int = 0
    resource_summary: dict[str, dict[str, int]] | None = None
    console_error_count: int = 0
    page_error_count: int = 0
    dom_nodes: int = 0
    rendered_html_characters: int = 0
    rendered_text_characters: int = 0
    static_text_characters: int = 0
    text_delta: int = 0
    text_growth_ratio: float | None = None
    rendered_title: str = ""
    rendered_meta_description: str = ""
    rendered_canonical_url: str = ""
    rendered_schema_types: tuple[str, ...] = ()
    rendered_heading_counts: dict[str, int] | None = None
    visible_image_count: int = 0
    images_without_alt: int = 0
    static_title: str = ""
    static_meta_description: str = ""
    static_canonical_url: str = ""
    static_schema_types: tuple[str, ...] = ()
    failure_code: str = ""
    evidence: dict[str, object] | None = None


_PROFILE_SPECS = {
    "mobile": {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 1,
        "is_mobile": True,
        "has_touch": True,
    },
    "desktop": {
        "viewport": {"width": 1365, "height": 768},
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
    },
}


def normalize_profiles(raw_profiles: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    profiles: list[str] = []
    for raw in raw_profiles:
        value = str(raw).strip().lower()
        if value in _PROFILE_SPECS and value not in profiles:
            profiles.append(value)
    if not profiles:
        profiles = ["mobile", "desktop"]
    return tuple(profiles)


def _int_metric(value: object) -> int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return None
    return max(0, int(round(float(value))))


def _float_metric(value: object, *, digits: int = 5) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return None
    return round(max(0.0, float(value)), digits)


def _strip_fragment(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _safe_network_url(url: str, cache: dict[tuple[str, str, int], bool]) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme in {"data", "blob", "about"}:
        return True
    if parsed.scheme not in {"http", "https"}:
        return False
    try:
        target = canonicalize_url(_strip_fragment(url))
    except Exception:
        return False
    key = (target.scheme, target.host, target.port)
    if key in cache:
        return cache[key]
    try:
        resolve_and_validate(target.host, target.port)
    except Exception:
        cache[key] = False
        return False
    cache[key] = True
    return True


def _failure_code(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return "BROWSER_TIMEOUT"
    if "targetclosed" in name or "browser has been closed" in text:
        return "BROWSER_CLOSED"
    if isinstance(exc, BrowserRuntimeUnavailable):
        return "BROWSER_RUNTIME_UNAVAILABLE"
    return "BROWSER_NAVIGATION_FAILED"


def _clean_message(value: object, maximum: int = 500) -> str:
    text = " ".join(str(value).replace("\x00", " ").split())
    return text[:maximum]


def _run_single_page(
    *,
    context,
    item: BrowserPageInput,
    profile: str,
    timeout_ms: int,
    settle_ms: int,
    max_requests: int,
    max_dom_characters: int,
) -> BrowserPageResult:
    page = context.new_page()
    host_safety_cache: dict[tuple[str, str, int], bool] = {}
    blocked_requests = 0
    routed_requests = 0
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    request_meta: dict[str, tuple[str, str]] = {}
    resource_summary: dict[str, dict[str, int]] = {}
    total_transfer = 0
    cross_host_transfer = 0
    cross_host_requests = 0
    root_host = (urlsplit(item.url).hostname or "").lower()

    def route_handler(route):
        nonlocal blocked_requests, routed_requests
        routed_requests += 1
        if routed_requests > max_requests or not _safe_network_url(route.request.url, host_safety_cache):
            blocked_requests += 1
            route.abort("blockedbyclient")
            return
        route.continue_()

    page.route("**/*", route_handler)
    page.on(
        "console",
        lambda message: console_errors.append(_clean_message(message.text))
        if message.type == "error" and "XIANWEN_BROWSER_AUDIT_" not in message.text
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(_clean_message(error)))
    page.on(
        "requestfailed",
        lambda request: failed_requests.append(_clean_message(request.url, 4096)),
    )

    session = context.new_cdp_session(page)
    session.send("Network.enable")

    def on_request(params):
        request_id = str(params.get("requestId", ""))
        request = params.get("request") or {}
        resource_type = str(params.get("type") or "Other")
        url = str(request.get("url") or "")
        if request_id:
            request_meta[request_id] = (resource_type, url)

    def on_finished(params):
        nonlocal total_transfer, cross_host_transfer, cross_host_requests
        request_id = str(params.get("requestId", ""))
        encoded = params.get("encodedDataLength", 0)
        size = int(encoded) if isinstance(encoded, (int, float)) and encoded > 0 else 0
        resource_type, url = request_meta.get(request_id, ("Other", ""))
        bucket = resource_summary.setdefault(resource_type, {"requests": 0, "bytes": 0})
        bucket["requests"] += 1
        bucket["bytes"] += size
        total_transfer += size
        host = (urlsplit(url).hostname or "").lower()
        if host and root_host and host != root_host:
            cross_host_requests += 1
            cross_host_transfer += size

    session.on("Network.requestWillBeSent", on_request)
    session.on("Network.loadingFinished", on_finished)

    started = time.monotonic()
    try:
        response = page.goto(item.url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("load", timeout=min(timeout_ms, 10_000))
        except Exception:
            pass
        if settle_ms > 0:
            page.wait_for_timeout(settle_ms)
        navigation_ms = max(0, int((time.monotonic() - started) * 1000))
        metrics = page.evaluate(_RENDER_METRICS_SCRIPT)
        html = page.content()
        rendered_html_characters = len(html)
        html_for_parse = html[:max_dom_characters]
        parsed = parse_html(html_for_parse, page.url)
        rendered_text = str(metrics.get("bodyText") or "")
        rendered_text_characters = len(rendered_text)
        text_delta = rendered_text_characters - item.static_text_characters
        ratio = None
        if item.static_text_characters > 0:
            ratio = round(rendered_text_characters / item.static_text_characters, 4)
        status_code = response.status if response is not None else None
        evidence = {
            "http_status": status_code,
            "console_errors": console_errors[:20],
            "page_errors": page_errors[:20],
            "failed_request_urls": failed_requests[:30],
            "routed_request_count": routed_requests,
            "network_host_checks": len(host_safety_cache),
            "dom_truncated_for_parser": rendered_html_characters > max_dom_characters,
        }
        return BrowserPageResult(
            page_id=item.page_id,
            url=item.url,
            profile=profile,
            status="succeeded",
            final_url=page.url,
            navigation_ms=navigation_ms,
            ttfb_ms=_int_metric(metrics.get("ttfb")),
            dom_content_loaded_ms=_int_metric(metrics.get("dcl")),
            load_ms=_int_metric(metrics.get("load")),
            fcp_ms=_int_metric(metrics.get("fcp")),
            lcp_ms=_int_metric(metrics.get("lcp")),
            cls=_float_metric(metrics.get("cls")),
            tbt_ms=_int_metric(metrics.get("tbt")),
            request_count=len(request_meta),
            failed_request_count=len(failed_requests),
            blocked_request_count=blocked_requests,
            transfer_bytes=total_transfer,
            cross_host_request_count=cross_host_requests,
            cross_host_transfer_bytes=cross_host_transfer,
            resource_summary=resource_summary,
            console_error_count=len(console_errors),
            page_error_count=len(page_errors),
            dom_nodes=int(metrics.get("domNodes") or 0),
            rendered_html_characters=rendered_html_characters,
            rendered_text_characters=rendered_text_characters,
            static_text_characters=item.static_text_characters,
            text_delta=text_delta,
            text_growth_ratio=ratio,
            rendered_title=_clean_message(metrics.get("title"), 500),
            rendered_meta_description=_clean_message(metrics.get("description"), 2000),
            rendered_canonical_url=_clean_message(metrics.get("canonical"), 4096),
            rendered_schema_types=tuple(sorted({str(x) for x in metrics.get("schemaTypes", []) if x})),
            rendered_heading_counts={
                str(key): int(value)
                for key, value in dict(metrics.get("headingCounts") or {}).items()
                if isinstance(value, int) and value >= 0
            },
            visible_image_count=int(metrics.get("visibleImages") or 0),
            images_without_alt=int(metrics.get("imagesWithoutAlt") or 0),
            static_title=item.static_title,
            static_meta_description=item.static_meta_description,
            static_canonical_url=item.static_canonical_url,
            static_schema_types=item.static_schema_types,
            evidence=evidence,
        )
    except Exception as exc:
        return BrowserPageResult(
            page_id=item.page_id,
            url=item.url,
            profile=profile,
            status="failed",
            navigation_ms=max(0, int((time.monotonic() - started) * 1000)),
            request_count=len(request_meta),
            failed_request_count=len(failed_requests),
            blocked_request_count=blocked_requests,
            transfer_bytes=total_transfer,
            cross_host_request_count=cross_host_requests,
            cross_host_transfer_bytes=cross_host_transfer,
            resource_summary=resource_summary,
            console_error_count=len(console_errors),
            page_error_count=len(page_errors),
            static_text_characters=item.static_text_characters,
            static_title=item.static_title,
            static_meta_description=item.static_meta_description,
            static_canonical_url=item.static_canonical_url,
            static_schema_types=item.static_schema_types,
            failure_code=_failure_code(exc),
            evidence={
                "error_type": type(exc).__name__,
                "error": _clean_message(exc),
                "console_errors": console_errors[:20],
                "page_errors": page_errors[:20],
                "failed_request_urls": failed_requests[:30],
            },
        )
    finally:
        try:
            session.detach()
        except Exception:
            pass
        page.close()


def run_browser_audit(
    pages: list[BrowserPageInput],
    *,
    profiles: tuple[str, ...] | list[str] = ("mobile", "desktop"),
    timeout_seconds: int = 30,
    settle_ms: int = 1200,
    max_requests: int = 300,
    max_dom_characters: int = 2_000_000,
) -> list[BrowserPageResult]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise BrowserRuntimeUnavailable("Playwright is not installed in this worker image.") from exc

    normalized_profiles = normalize_profiles(profiles)
    results: list[BrowserPageResult] = []
    timeout_ms = max(1, int(timeout_seconds * 1000))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-sync",
                "--metrics-recording-only",
                "--no-first-run",
            ],
        )
        try:
            for profile in normalized_profiles:
                context = browser.new_context(
                    **_PROFILE_SPECS[profile],
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    service_workers="block",
                    ignore_https_errors=False,
                    accept_downloads=False,
                    reduced_motion="reduce",
                )
                context.add_init_script(_PERF_INIT_SCRIPT)
                try:
                    for item in pages:
                        results.append(
                            _run_single_page(
                                context=context,
                                item=item,
                                profile=profile,
                                timeout_ms=timeout_ms,
                                settle_ms=settle_ms,
                                max_requests=max_requests,
                                max_dom_characters=max_dom_characters,
                            )
                        )
                        context.clear_cookies()
                finally:
                    context.close()
        finally:
            browser.close()
    return results
