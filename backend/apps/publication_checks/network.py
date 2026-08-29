from __future__ import annotations

import time
from dataclasses import dataclass

from django.conf import settings

from apps.web_sources.exceptions import (
    WebSourceTransientError,
    WebSourceUrlInvalid,
    WebSourceUrlNotAllowed,
)
from apps.web_sources.http_transport import _request_once
from apps.web_sources.url_security import canonicalize_url


@dataclass(frozen=True)
class PublicationProbeResult:
    request_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    redirect_count: int
    peer_ip: str


def probe_publication_url(raw_url: str) -> PublicationProbeResult:
    initial = canonicalize_url(raw_url)
    current = initial
    deadline = time.monotonic() + settings.WEB_IMPORT_TOTAL_TIMEOUT_SECONDS
    redirect_count = 0

    while True:
        if deadline - time.monotonic() <= 0:
            raise WebSourceTransientError
        status, headers, body, peer = _request_once(current, deadline)
        header_map: dict[str, list[str]] = {}
        for name, value in headers:
            header_map.setdefault(name.lower(), []).append(value)

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

        content_types = header_map.get("content-type", [])
        content_type = content_types[0][:128] if len(content_types) == 1 else ""
        return PublicationProbeResult(
            request_url=initial.value,
            final_url=current.value,
            status=status,
            content_type=content_type,
            body=body,
            redirect_count=redirect_count,
            peer_ip=peer,
        )
