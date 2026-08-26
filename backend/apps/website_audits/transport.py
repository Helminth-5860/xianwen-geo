from __future__ import annotations

import os
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
    deadline: float | None = None,
) -> AuditFetchResult:
    """Fetch arbitrary audit evidence while preserving the existing SSRF/TLS protections.

    ``deadline`` is an absolute monotonic deadline shared by the whole crawl. Every
    individual request also receives its own shorter budget so a single slow page
    cannot consume the complete customer-facing scan window.
    """

    initial = canonicalize_url(raw_url)
    current = initial
    started = time.monotonic()
    request_timeout_seconds = int(
        getattr(
            settings,
            "WEBSITE_AUDIT_REQUEST_TIMEOUT_SECONDS",
            os.getenv("WEBSITE_AUDIT_REQUEST_TIMEOUT_SECONDS", "8"),
        )
    )
    request_deadline = started + request_timeout_seconds
    effective_deadline = min(deadline, request_deadline) if deadline is not None else request_deadline
    redirect_count = 0
    byte_limit = max_bytes or settings.WEBSITE_AUDIT_MAX_RESPONSE_BYTES
    while True:
        if effective_deadline - time.monotonic() <= 0:
            raise WebSourceTransientError
        status, raw_headers, body, _peer = _request_once(
            current,
            effective_deadline,
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
