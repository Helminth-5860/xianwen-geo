from __future__ import annotations

import hashlib
import http.client
import io
import socket
import ssl
import time
from dataclasses import dataclass
from typing import cast

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


def _remaining_timeout(deadline: float, configured_timeout: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WebSourceTransientError
    return min(configured_timeout, remaining)


class _DeadlineRawIO(io.RawIOBase):
    """Raw socket reader that reapplies the absolute fetch deadline per receive."""

    def __init__(self, sock: socket.socket, deadline: float):
        super().__init__()
        self._sock = sock
        self._deadline = deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int | None:
        if self.closed:
            return 0
        timeout = _remaining_timeout(self._deadline, settings.WEB_IMPORT_READ_TIMEOUT_SECONDS)
        self._sock.settimeout(timeout)
        return self._sock.recv_into(buffer)


class _DeadlineSocket:
    """HTTPResponse socket facade whose file reads share one absolute deadline."""

    def __init__(self, sock: socket.socket, deadline: float):
        self._sock = sock
        self._deadline = deadline

    def makefile(self, mode: str, buffering: int | None = None) -> io.RawIOBase | io.BufferedReader:
        if mode != "rb":
            raise ValueError("web import transport only supports binary reads")
        raw = _DeadlineRawIO(self._sock, self._deadline)
        if buffering is None or buffering == -1:
            size = io.DEFAULT_BUFFER_SIZE
        else:
            size = buffering
        if size == 0:
            return raw
        return io.BufferedReader(raw, buffer_size=size)


def _connect(target: CanonicalUrl, address: str, deadline: float):
    connect_timeout = _remaining_timeout(deadline, settings.WEB_IMPORT_CONNECT_TIMEOUT_SECONDS)
    raw = socket.create_connection(
        (address, target.port),
        timeout=connect_timeout,
    )
    raw.settimeout(_remaining_timeout(deadline, settings.WEB_IMPORT_READ_TIMEOUT_SECONDS))
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
            raw.settimeout(
                _remaining_timeout(deadline, settings.WEB_IMPORT_CONNECT_TIMEOUT_SECONDS)
            )
            raw = context.wrap_socket(raw, server_hostname=target.host)
        except Exception:
            raw.close()
            raise
        if raw.getpeername()[0] != address:
            raw.close()
            raise WebSourceUrlNotAllowed
    return raw


def _request_once(
    target: CanonicalUrl,
    deadline: float,
    *,
    accept: str = "text/html,text/plain;q=0.9",
    max_response_bytes: int | None = None,
):
    byte_limit = max_response_bytes or settings.WEB_IMPORT_MAX_RESPONSE_BYTES
    last_error = None
    for address in resolve_and_validate(target.host, target.port):
        sock = None
        response = None
        try:
            sock = _connect(target, address, deadline)
            host = f"[{target.host}]" if ":" in target.host else target.host
            request = (
                f"GET {target.target} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"User-Agent: {settings.WEB_IMPORT_USER_AGENT}\r\n"
                f"Accept: {accept}\r\n"
                "Accept-Encoding: identity\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            sock.settimeout(_remaining_timeout(deadline, settings.WEB_IMPORT_READ_TIMEOUT_SECONDS))
            sock.sendall(request)
            response = http.client.HTTPResponse(
                cast(socket.socket, _DeadlineSocket(sock, deadline))
            )
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
                if declared_size < 0 or declared_size > byte_limit:
                    raise WebSourceContentTooLarge
            else:
                declared_size = None
            chunks: list[bytes] = []
            total = 0
            while True:
                if deadline - time.monotonic() <= 0:
                    raise WebSourceTransientError
                chunk = response.read(min(64 * 1024, byte_limit + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > byte_limit:
                    raise WebSourceContentTooLarge
                chunks.append(chunk)
            if declared_size is not None and total != declared_size:
                raise WebSourceContentUnsupported
            return response.status, headers, b"".join(chunks), address
        except (WebSourceContentTooLarge, WebSourceContentUnsupported, WebSourceUrlNotAllowed):
            raise
        except WebSourceTransientError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            if response is not None:
                close_response = getattr(response, "close", None)
                if callable(close_response):
                    close_response()
            if sock is not None:
                sock.close()
    raise WebSourceTransientError from last_error


def fetch_url(raw_url: str) -> FetchResult:
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


def fetch_binary_url(
    raw_url: str,
    *,
    allowed_media_types: frozenset[str],
    max_response_bytes: int,
) -> FetchResult:
    initial = canonicalize_url(raw_url)
    current = initial
    deadline = time.monotonic() + settings.WEB_IMPORT_TOTAL_TIMEOUT_SECONDS
    redirect_count = 0
    while True:
        if deadline - time.monotonic() <= 0:
            raise WebSourceTransientError
        status, headers, body, peer = _request_once(
            current,
            deadline,
            accept=",".join(sorted(allowed_media_types)),
            max_response_bytes=max_response_bytes,
        )
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
        if media_type not in allowed_media_types:
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
