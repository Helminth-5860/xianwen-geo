from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings

from apps.web_sources.exceptions import (
    WebSourceContentTooLarge,
    WebSourceContentUnsupported,
    WebSourceTransientError,
    WebSourceUrlInvalid,
    WebSourceUrlNotAllowed,
)

from .parser import ExtractedLink, PageEvidence, normalize_link, parse_html
from .transport import AuditFetchResult, fetch_audit_url

_NON_HTML_EXTENSIONS = re.compile(
    r"\.(?:7z|avi|bmp|css|csv|docx?|eot|exe|gif|gz|ico|jpe?g|js|json|m4a|mov|mp3|mp4|mpeg|pdf|png|pptx?|rar|rss|svg|tar|tiff?|ttf|txt|wav|webm|webp|woff2?|xlsx?|xml|zip)$",
    re.I,
)
_TRACKING_KEYS = {"fbclid", "gclid", "msclkid", "ref", "source", "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term"}


@dataclass(frozen=True)
class CrawledPage:
    url: str
    final_url: str
    source: str
    depth: int
    status: int | None
    content_type: str
    response_ms: int | None
    response_bytes: int
    redirect_count: int
    response_sha256: str
    evidence: PageEvidence | None
    fetch_error: str = ""


@dataclass(frozen=True)
class CrawledLink:
    source_url: str
    destination_url: str
    is_internal: bool
    anchor_text: str
    rel: str


@dataclass
class CrawlResult:
    root_url: str
    root_host: str
    robots_url: str = ""
    robots_status: int | None = None
    robots_text: str = ""
    sitemap_urls: list[str] = field(default_factory=list)
    discovered_urls: set[str] = field(default_factory=set)
    pages: list[CrawledPage] = field(default_factory=list)
    links: list[CrawledLink] = field(default_factory=list)
    timed_out: bool = False


def _clean_url(raw: str, base: str) -> str:
    normalized = normalize_link(raw, base)
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    if _NON_HTML_EXTENSIONS.search(parsed.path):
        return ""
    if not parsed.query:
        return normalized
    pairs = []
    for chunk in parsed.query.split("&"):
        key = chunk.split("=", 1)[0].lower()
        if key not in _TRACKING_KEYS:
            pairs.append(chunk)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "&".join(pairs), ""))


def _same_host(url: str, host: str) -> bool:
    return (urlsplit(url).hostname or "").lower() == host.lower()


def _decode_text(result: AuditFetchResult) -> str:
    content_type = result.content_type.lower()
    match = re.search(r"charset\s*=\s*['\"]?([a-z0-9_-]+)", content_type, re.I)
    candidates = [match.group(1) if match else "", "utf-8", "gb18030", "big5"]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return result.body.decode(candidate, errors="strict")
        except (LookupError, UnicodeError):
            continue
    return result.body.decode("utf-8", errors="replace")


def _robots_sitemaps(text: str, robots_url: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        if key.strip().lower() != "sitemap":
            continue
        normalized = normalize_link(value.strip(), robots_url)
        if normalized and normalized not in found:
            found.append(normalized)
    return found


def _sitemap_locations(xml_text: str, sitemap_url: str) -> tuple[list[str], bool]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], False
    local_name = root.tag.rsplit("}", 1)[-1].lower()
    is_index = local_name == "sitemapindex"
    locations: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() != "loc" or not element.text:
            continue
        normalized = normalize_link(element.text.strip(), sitemap_url)
        if normalized and normalized not in locations:
            locations.append(normalized)
    return locations, is_index


def _error_code(exc: Exception) -> str:
    if isinstance(exc, WebSourceUrlNotAllowed):
        return "URL_NOT_ALLOWED"
    if isinstance(exc, WebSourceUrlInvalid):
        return "URL_INVALID"
    if isinstance(exc, WebSourceContentTooLarge):
        return "CONTENT_TOO_LARGE"
    if isinstance(exc, WebSourceContentUnsupported):
        return "CONTENT_UNSUPPORTED"
    if isinstance(exc, WebSourceTransientError):
        return "FETCH_TRANSIENT"
    return "FETCH_FAILED"


def _deadline_expired(deadline: float) -> bool:
    return time.monotonic() >= deadline


def crawl_website(root_url: str, *, max_pages: int = 200, max_sitemaps: int = 20) -> CrawlResult:
    started = time.monotonic()
    crawl_deadline = started + settings.WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS

    first = fetch_audit_url(root_url, deadline=crawl_deadline)
    final_root = first.final_url
    root_host = (urlsplit(final_root).hostname or "").lower()
    if not root_host:
        raise WebSourceUrlInvalid
    root_url = _clean_url(final_root, final_root) or final_root
    result = CrawlResult(root_url=root_url, root_host=root_host)

    # Robots/sitemap discovery is useful, but it must never consume the full scan.
    # Reserve most of the customer-facing budget for actual HTML evidence pages.
    discovery_deadline = min(crawl_deadline, time.monotonic() + 15)

    robots_url = f"{urlsplit(root_url).scheme}://{urlsplit(root_url).netloc}/robots.txt"
    result.robots_url = robots_url
    sitemap_candidates: list[str] = []
    if not _deadline_expired(discovery_deadline):
        try:
            robots = fetch_audit_url(
                robots_url,
                accept="text/plain,*/*;q=0.5",
                max_bytes=512_000,
                deadline=discovery_deadline,
            )
            result.robots_status = robots.status
            if robots.status == 200:
                result.robots_text = _decode_text(robots)[:500_000]
                sitemap_candidates.extend(_robots_sitemaps(result.robots_text, robots.final_url))
        except Exception:
            result.robots_status = None

    default_sitemap = f"{urlsplit(root_url).scheme}://{urlsplit(root_url).netloc}/sitemap.xml"
    if default_sitemap not in sitemap_candidates:
        sitemap_candidates.append(default_sitemap)

    sitemap_pages: list[str] = []
    sitemap_queue = deque(sitemap_candidates)
    seen_sitemaps: set[str] = set()
    while (
        sitemap_queue
        and len(seen_sitemaps) < max_sitemaps
        and not _deadline_expired(discovery_deadline)
    ):
        sitemap_url = sitemap_queue.popleft()
        if sitemap_url in seen_sitemaps or not _same_host(sitemap_url, root_host):
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            fetched = fetch_audit_url(
                sitemap_url,
                accept="application/xml,text/xml,text/plain,*/*;q=0.5",
                max_bytes=4_000_000,
                deadline=discovery_deadline,
            )
        except Exception:
            continue
        if fetched.status != 200:
            continue
        locations, is_index = _sitemap_locations(_decode_text(fetched), fetched.final_url)
        result.sitemap_urls.append(fetched.final_url)
        if is_index:
            for location in locations:
                if _same_host(location, root_host) and location not in seen_sitemaps:
                    sitemap_queue.append(location)
        else:
            for location in locations:
                cleaned = _clean_url(location, fetched.final_url)
                if cleaned and _same_host(cleaned, root_host) and cleaned not in sitemap_pages:
                    sitemap_pages.append(cleaned)

    queue: deque[tuple[str, str, int]] = deque()
    queue.append((root_url, "root", 0))
    for sitemap_page in sitemap_pages:
        if sitemap_page != root_url:
            queue.append((sitemap_page, "sitemap", 1))
    queued: set[str] = {item[0] for item in queue}
    visited: set[str] = set()

    while queue and len(result.pages) < max_pages:
        # The root response was already fetched above; let it become evidence even
        # if discovery consumed the remaining milliseconds. All new network calls
        # obey the hard crawl deadline.
        if _deadline_expired(crawl_deadline) and result.pages:
            result.timed_out = True
            break
        url, source, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        result.discovered_urls.add(url)
        try:
            if url == root_url and not result.pages:
                fetched = first
            else:
                if _deadline_expired(crawl_deadline):
                    result.timed_out = True
                    break
                fetched = fetch_audit_url(url, deadline=crawl_deadline)
            media_type = fetched.content_type.split(";", 1)[0].strip().lower()
            evidence = None
            if fetched.status == 200 and media_type in {"text/html", "application/xhtml+xml"}:
                evidence = parse_html(_decode_text(fetched), fetched.final_url)
            page = CrawledPage(
                url=url,
                final_url=fetched.final_url,
                source=source,
                depth=depth,
                status=fetched.status,
                content_type=fetched.content_type,
                response_ms=fetched.response_ms,
                response_bytes=len(fetched.body),
                redirect_count=fetched.redirect_count,
                response_sha256=__import__("hashlib").sha256(fetched.body).hexdigest(),
                evidence=evidence,
            )
        except Exception as exc:
            page = CrawledPage(
                url=url,
                final_url="",
                source=source,
                depth=depth,
                status=None,
                content_type="",
                response_ms=None,
                response_bytes=0,
                redirect_count=0,
                response_sha256="",
                evidence=None,
                fetch_error=_error_code(exc),
            )
        result.pages.append(page)
        if page.evidence is None:
            continue
        for link in page.evidence.links:
            cleaned = _clean_url(link.url, page.final_url or page.url)
            if not cleaned:
                continue
            internal = _same_host(cleaned, root_host)
            result.links.append(
                CrawledLink(page.url, cleaned, internal, link.anchor_text, link.rel)
            )
            if internal:
                result.discovered_urls.add(cleaned)
                if cleaned not in visited and cleaned not in queued and len(queued) < max_pages * 5:
                    queue.append((cleaned, "internal_link", min(depth + 1, 255)))
                    queued.add(cleaned)

    if queue and _deadline_expired(crawl_deadline):
        result.timed_out = True
    result.discovered_urls.update(sitemap_pages)
    return result
