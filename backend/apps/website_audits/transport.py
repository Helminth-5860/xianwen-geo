from __future__ import annotations

import time
from dataclasses import dataclass

from django.conf import settings

from apps.web_sources.exceptions import WebSourceTransientError, WebSourceUrlInvalid, WebSourceUrlNotAllowed
from apps.web_sources.http_transport import _request_once
from apps.web_sources.url_security import canonicalize_url


@dataclass(frozen=True)
class AuditFetchResult:
    request_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    redirect_count: int
    response_ms: int
    headers: dict[str, str]


def fetch_audit_url(
    raw_url: str,
    *,
    accept: str = "text/html,application/xhtml+xml,text/plain,application/xml,text/xml;q=0.9",
    max_bytes: int | None = None,
) -> AuditFetchResult:
    """Fetch arbitrary audit evidence while preserving the existing SSRF/TLS protections."""

    initial = canonicalize_url(raw_url)
    current = initial
    deadline = time.monotonic() + settings.WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS
    redirect_count = 0
    started = time.monotonic()
    byte_limit = max_bytes or settings.WEBSITE_AUDIT_MAX_RESPONSE_BYTES
    while True:
        if deadline - time.monotonic() <= 0:
            raise WebSourceTransientError
        status, raw_headers, body, _peer = _request_once(
            current,
            deadline,
            accept=accept,
            max_response_bytes=byte_limit,
        )
        header_map: dict[str, list[str]] = {}
        for name, value in raw_headers:
            header_map.setdefault(name.lower(), []).append(value)
        headers = {name: values[-1] for name, values in header_map.items() if values}
        if status in {301, 302, 303, 307, 308}:
            locations = header_map.get("location", [])
            if len(locations) != 1 or redirect_count >= settings.WEB_IMPORT_MAX_REDIRECTS:
                raise WebSourceUrlInvalid
            following = canonicalize_url(locations[0], base=current.value)
            if current.scheme == "https" and following.scheme != "https":
                raise WebSourceUrlNotAllowed
            current = following
            redirect_count += 1
            continue
        return AuditFetchResult(
            request_url=initial.value,
            final_url=current.value,
            status=status,
            content_type=headers.get("content-type", "")[:128],
            body=body,
            redirect_count=redirect_count,
            response_ms=max(0, int((time.monotonic() - started) * 1000)),
            headers=headers,
        )
