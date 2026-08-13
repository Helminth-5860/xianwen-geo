from __future__ import annotations

import hashlib
import http.client
import socket
import ssl
import time
from dataclasses import dataclass

from django.conf import settings

from .exceptions import (
    WebSourceContentTooLarge,
    WebSourceContentUnsupported,
    WebSourceTransientError,
    WebSourceUrlInvalid,
    WebSourceUrlNotAllowed,
)
from .url_security import CanonicalUrl, canonicalize_url, resolve_and_validate


@dataclass(frozen=True)
class FetchResult:
    request_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    response_sha256: str
    redirect_count: int
    peer_ip: str


def _connect(target: CanonicalUrl, address: str, deadline: float):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WebSourceTransientError
    raw = socket.create_connection(
        (address, target.port),
        timeout=min(settings.WEB_IMPORT_CONNECT_TIMEOUT_SECONDS, remaining),
    )
    raw.settimeout(min(settings.WEB_IMPORT_READ_TIMEOUT_SECONDS, remaining))
    peer = raw.getpeername()[0]
    if peer != address:
        raw.close()
        raise WebSourceUrlNotAllowed
    if target.scheme == "https":
        context = ssl.create_default_context(
            cafile=getattr(settings, "WEB_IMPORT_CA_FILE", None) or None
        )
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            raw = context.wrap_socket(raw, server_hostname=target.host)
        except Exception:
            raw.close()
            raise
        if raw.getpeername()[0] != address:
            raw.close()
            raise WebSourceUrlNotAllowed
    return raw


def _request_once(target: CanonicalUrl, deadline: float):
    last_error = None
    for address in resolve_and_validate(target.host, target.port):
        sock = None
        try:
            sock = _connect(target, address, deadline)
            host = f"[{target.host}]" if ":" in target.host else target.host
            request = (
                f"GET {target.target} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"User-Agent: {settings.WEB_IMPORT_USER_AGENT}\r\n"
                "Accept: text/html,text/plain;q=0.9\r\n"
                "Accept-Encoding: identity\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)
            response = http.client.HTTPResponse(sock)
            response.begin()
            headers = response.getheaders()
            status_line_size = 16 + len((response.reason or "").encode("latin1"))
            if status_line_size > settings.WEB_IMPORT_MAX_HEADER_LINE_BYTES:
                raise WebSourceContentTooLarge
            if len(headers) > settings.WEB_IMPORT_MAX_HEADER_COUNT:
                raise WebSourceContentTooLarge
            header_bytes = 0
            for name, value in headers:
                line_size = len(name.encode("latin1")) + len(value.encode("latin1")) + 4
                if line_size > settings.WEB_IMPORT_MAX_HEADER_LINE_BYTES:
                    raise WebSourceContentTooLarge
                header_bytes += line_size
            if header_bytes > settings.WEB_IMPORT_MAX_HEADER_BYTES:
                raise WebSourceContentTooLarge
            encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
            if encoding != "identity":
                raise WebSourceContentUnsupported
            transfer_encoding = response.getheader("Transfer-Encoding")
            if transfer_encoding and transfer_encoding.strip().lower() != "chunked":
                raise WebSourceContentUnsupported
            declared = response.getheader("Content-Length")
            if transfer_encoding and declared is not None:
                raise WebSourceContentUnsupported
            if declared is not None:
                try:
                    declared_size = int(declared)
                except ValueError as exc:
                    raise WebSourceContentUnsupported from exc
                if declared_size < 0 or declared_size > settings.WEB_IMPORT_MAX_RESPONSE_BYTES:
                    raise WebSourceContentTooLarge
            else:
                declared_size = None
            chunks: list[bytes] = []
            total = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WebSourceTransientError
                sock.settimeout(min(settings.WEB_IMPORT_READ_TIMEOUT_SECONDS, remaining))
                chunk = response.read(
                    min(64 * 1024, settings.WEB_IMPORT_MAX_RESPONSE_BYTES + 1 - total)
                )
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.WEB_IMPORT_MAX_RESPONSE_BYTES:
                    raise WebSourceContentTooLarge
                chunks.append(chunk)
            if declared_size is not None and total != declared_size:
                raise WebSourceContentUnsupported
            return response.status, headers, b"".join(chunks), address
        except (WebSourceContentTooLarge, WebSourceContentUnsupported, WebSourceUrlNotAllowed):
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            if sock is not None:
                sock.close()
    raise WebSourceTransientError from last_error


def fetch_url(raw_url: str) -> FetchResult:
    initial = canonicalize_url(raw_url)
    current = initial
    deadline = time.monotonic() + settings.WEB_IMPORT_TOTAL_TIMEOUT_SECONDS
    redirect_count = 0
    while True:
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
        if status in {408, 429} or 500 <= status < 600:
            raise WebSourceTransientError
        if status != 200:
            raise WebSourceContentUnsupported
        content_types = header_map.get("content-type", [])
        if len(content_types) != 1:
            raise WebSourceContentUnsupported
        raw_type = content_types[0]
        media_type = raw_type.split(";", 1)[0].strip().lower()
        if media_type not in {"text/html", "text/plain"}:
            raise WebSourceContentUnsupported
        return FetchResult(
            request_url=initial.value,
            final_url=current.value,
            status=status,
            content_type=raw_type[:128],
            body=body,
            response_sha256=hashlib.sha256(body).hexdigest(),
            redirect_count=redirect_count,
            peer_ip=peer,
        )
