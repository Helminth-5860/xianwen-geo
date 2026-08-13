from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser

from django.conf import settings

from .exceptions import WebSourceContentTooLarge, WebSourceContentUnsupported

PARSER_VERSION = "static-html-v1"
_META_CHARSET = re.compile(rb"charset\s*=\s*['\"]?([a-zA-Z0-9_-]+)", re.I)
_UNSAFE_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "object",
    "embed",
    "svg",
    "form",
}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked_tags: list[str] = []
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        hidden = any(name.lower() == "hidden" for name, _ in attrs)
        if tag in _UNSAFE_TAGS or hidden:
            self.blocked_tags.append(tag)
        if tag == "title" and not self.blocked_tags:
            self.in_title = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.blocked_tags and self.blocked_tags[-1] == tag:
            self.blocked_tags.pop()
        if tag == "title" and not self.blocked_tags:
            self.in_title = False

    def handle_data(self, data):
        if self.blocked_tags:
            return
        self.parts.append(data)
        if self.in_title:
            self.title_parts.append(data)


def _charset(content_type: str, body: bytes) -> str:
    header_match = re.search(r"charset\s*=\s*([a-zA-Z0-9_-]+)", content_type, re.I)
    candidate = header_match.group(1) if header_match else ""
    if body.startswith(b"\xef\xbb\xbf"):
        candidate = "utf-8-sig"
    if not candidate:
        match = _META_CHARSET.search(body[:4096])
        candidate = match.group(1).decode("ascii") if match else "utf-8"
    normalized = candidate.lower().replace("_", "-")
    aliases = {"utf8": "utf-8", "gbk": "gb18030", "gb2312": "gb18030", "big5-hkscs": "big5"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"utf-8", "utf-8-sig", "gb18030", "big5"}:
        raise WebSourceContentUnsupported
    return normalized


def parse_response(*, body: bytes, media_type: str, content_type: str) -> tuple[str, str, str, str]:
    charset = _charset(content_type, body)
    try:
        decoded = body.decode(charset, errors="strict")
    except UnicodeError as exc:
        raise WebSourceContentUnsupported from exc
    if media_type == "text/html":
        extractor = _TextExtractor()
        extractor.feed(decoded)
        text = " ".join(extractor.parts)
        title = " ".join(extractor.title_parts)
    else:
        text, title = decoded, ""
    text = " ".join(unicodedata.normalize("NFKC", text).split())
    title = " ".join(unicodedata.normalize("NFKC", title).split())[:500]
    if len(text) > settings.WEB_IMPORT_MAX_TEXT_CHARACTERS:
        raise WebSourceContentTooLarge
    digest = hashlib.sha256(
        json.dumps(
            {"parser": PARSER_VERSION, "text": text, "title": title},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return title, text, charset.replace("-sig", ""), digest
