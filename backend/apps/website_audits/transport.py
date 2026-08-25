from __future__ import annotations

import http.client
import socket
import ssl
import time
from dataclasses import dataclass

from django.conf import settings

from apps.web_sources.exceptions import (
    WebSourceContentTooLarge,
    WebSourceTransientError,
    WebSourceUrlInvalid,
    WebSourceUrlNotAllowed,
)
from apps.web_sources.url_security import canonicalize_url, resolve_and_validate


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


def _timeout(deadline: float, configured: int) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WebSourceTransientError
    return min(float(configured), remaining)


def _request_once(target, deadline: float, *, accept: str, max_bytes: int):
    last_error = None
    for address in resolve_and_validate(target.host, target.port):
        connection = None
        try:
            timeout = _timeout(deadline, settings.WEB_IMPORT_CONNECT_TIMEOUT_SECONDS)
            if target.scheme == "https":
                context = ssl.create_default_context(
                    cafile=getattr(settings, "WEB_IMPORT_CA_FILE", None) or None
                )
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                connection = http.client.HTTPSConnection(
                    address,
                    target.port,
                    timeout=timeout,
                    context=context,
                )
                connection.set_tunnel(target.host, target.port) if False else None
            else:
                connection = http.client.HTTPConnection(address, target.port, timeout=timeout)
            host_header = target.host
            if target.port not in {80, 443}:
                host_header = f"{target.host}:{target.port}"
            connection.putrequest("GET", target.target, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", host_header)
            connection.putheader("User-Agent", settings.WEBSITE_AUDIT_USER_AGENT)
            connection.putheader("Accept", accept)
            connection.putheader("Accept-Encoding", "identity")
            connection.putheader("Connection", "close")
            connection.endheaders()
            response = connection.getresponse()
            peer = connection.sock.getpeername()[0] if connection.sock else address
            if peer != address:
                raise WebSourceUrlNotAllowed
            headers: dict[str, str] = {}
            total_header_bytes = 0
            for name, value in response.getheaders():
                total_header_bytes += len(name) + len(value) + 4
                if total_header_bytes > settings.WEB_IMPORT_MAX_HEADER_BYTES:
                    raise WebSourceContentTooLarge
                headers[name.lower()] = value
            declared = headers.get("content-length")
            if declared:
                try:
                    size = int(declared)
                except ValueError as exc:
                    raise WebSourceContentTooLarge from exc
                if size > max_bytes:
                    raise WebSourceContentTooLarge
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise WebSourceContentTooLarge
            return response.status, headers, body
        except (WebSourceContentTooLarge, WebSourceUrlNotAllowed):
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            if connection is not None:
                connection.close()
    raise WebSourceTransientError from last_error


def fetch_audit_url(
    raw_url: str,
    *,
    accept: str = "text/html,application/xhtml+xml,text/plain,application/xml,text/xml;q=0.9",
    max_bytes: int | None = None,
) -> AuditFetchResult:
    initial = canonicalize_url(raw_url)
    current = initial
    deadline = time.monotonic() + settings.WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS
    redirect_count = 0
    started = time.monotonic()
    byte_limit = max_bytes or settings.WEBSITE_AUDIT_MAX_RESPONSE_BYTES
    while True:
        status, headers, body = _request_once(current, deadline, accept=accept, max_bytes=byte_limit)
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location", "")
            if not location or redirect_count >= settings.WEB_IMPORT_MAX_REDIRECTS:
                raise WebSourceUrlInvalid
            following = canonicalize_url(location, base=current.value)
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
