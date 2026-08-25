from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit


@dataclass(frozen=True)
class ExtractedLink:
    url: str
    anchor_text: str
    rel: str


@dataclass(frozen=True)
class PageEvidence:
    title: str
    meta_description: str
    canonical_url: str
    robots_meta: str
    html_lang: str
    viewport: str
    headings: dict[str, list[str]]
    open_graph: dict[str, str]
    twitter_card: dict[str, str]
    schema_types: list[str]
    image_count: int
    image_alt_missing_count: int
    links: list[ExtractedLink]
    text: str


class _AuditHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.current_heading: str | None = None
        self.current_heading_parts: list[str] = []
        self.headings: dict[str, list[str]] = {f"h{i}": [] for i in range(1, 7)}
        self.in_title = False
        self.blocked_depth = 0
        self.text_parts: list[str] = []
        self.meta_description = ""
        self.canonical_url = ""
        self.robots_meta = ""
        self.html_lang = ""
        self.viewport = ""
        self.open_graph: dict[str, str] = {}
        self.twitter_card: dict[str, str] = {}
        self.schema_types: set[str] = set()
        self.image_count = 0
        self.image_alt_missing_count = 0
        self.links: list[ExtractedLink] = []
        self._anchor_href = ""
        self._anchor_rel = ""
        self._anchor_parts: list[str] = []
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

    @staticmethod
    def _attrs(attrs) -> dict[str, str]:
        return {str(name).lower(): str(value or "") for name, value in attrs}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        data = self._attrs(attrs)
        if tag in {"script", "style", "noscript", "template", "iframe", "object", "embed"}:
            if tag == "script" and data.get("type", "").lower() == "application/ld+json":
                self._in_json_ld = True
                self._json_ld_parts = []
                return
            self.blocked_depth += 1
            return
        if tag == "html":
            self.html_lang = data.get("lang", "")[:64]
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            name = data.get("name", "").strip().lower()
            prop = data.get("property", "").strip().lower()
            content = data.get("content", "").strip()
            if name == "description" and not self.meta_description:
                self.meta_description = content
            elif name in {"robots", "googlebot"} and content:
                self.robots_meta = content if not self.robots_meta else f"{self.robots_meta}; {content}"
            elif name == "viewport" and not self.viewport:
                self.viewport = content
            if prop.startswith("og:") and content:
                self.open_graph[prop] = content
            if name.startswith("twitter:") and content:
                self.twitter_card[name] = content
        elif tag == "link":
            rel = data.get("rel", "").lower().split()
            href = data.get("href", "").strip()
            if "canonical" in rel and href and not self.canonical_url:
                self.canonical_url = urljoin(self.base_url, href)
        elif tag in self.headings:
            self.current_heading = tag
            self.current_heading_parts = []
        elif tag == "img":
            self.image_count += 1
            if not data.get("alt", "").strip():
                self.image_alt_missing_count += 1
        elif tag == "a":
            self._anchor_href = data.get("href", "").strip()
            self._anchor_rel = data.get("rel", "").strip()
            self._anchor_parts = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            self._consume_json_ld("".join(self._json_ld_parts))
            self._json_ld_parts = []
            return
        if tag in {"script", "style", "noscript", "template", "iframe", "object", "embed"}:
            if self.blocked_depth > 0:
                self.blocked_depth -= 1
            return
        if tag == "title":
            self.in_title = False
        elif self.current_heading == tag:
            value = " ".join(" ".join(self.current_heading_parts).split())
            if value:
                self.headings[tag].append(value[:500])
            self.current_heading = None
            self.current_heading_parts = []
        elif tag == "a" and self._anchor_href:
            absolute = normalize_link(self._anchor_href, self.base_url)
            if absolute:
                text = " ".join(" ".join(self._anchor_parts).split())[:500]
                self.links.append(ExtractedLink(absolute, text, self._anchor_rel[:255]))
            self._anchor_href = ""
            self._anchor_rel = ""
            self._anchor_parts = []

    def handle_data(self, data):
        if self._in_json_ld:
            self._json_ld_parts.append(data)
            return
        if self.blocked_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
        if self.current_heading:
            self.current_heading_parts.append(data)
        if self._anchor_href:
            self._anchor_parts.append(data)
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)

    def _consume_json_ld(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            return

        def walk(value):
            if isinstance(value, dict):
                raw_type = value.get("@type")
                if isinstance(raw_type, str):
                    self.schema_types.add(raw_type)
                elif isinstance(raw_type, list):
                    self.schema_types.update(item for item in raw_type if isinstance(item, str))
                for nested in value.values():
                    walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)

        walk(payload)


def normalize_link(raw: str, base_url: str) -> str:
    raw = raw.strip()
    if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return ""
    absolute = urljoin(base_url, raw)
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    port = parsed.port
    netloc = host
    if port and not ((parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def parse_html(html: str, final_url: str) -> PageEvidence:
    parser = _AuditHTMLParser(final_url)
    parser.feed(html)
    title = " ".join(" ".join(parser.title_parts).split())[:500]
    text = " ".join(parser.text_parts)
    return PageEvidence(
        title=title,
        meta_description=parser.meta_description[:2000],
        canonical_url=parser.canonical_url[:4096],
        robots_meta=parser.robots_meta[:500],
        html_lang=parser.html_lang,
        viewport=parser.viewport[:500],
        headings=parser.headings,
        open_graph=dict(sorted(parser.open_graph.items())),
        twitter_card=dict(sorted(parser.twitter_card.items())),
        schema_types=sorted(parser.schema_types),
        image_count=parser.image_count,
        image_alt_missing_count=parser.image_alt_missing_count,
        links=parser.links,
        text=text,
    )
