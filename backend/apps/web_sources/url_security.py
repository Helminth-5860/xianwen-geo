from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

import idna
from django.conf import settings

from .exceptions import WebSourceUrlInvalid, WebSourceUrlNotAllowed

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NUMERICISH = re.compile(r"^[0-9a-fA-FxX.:]+$")
_BLOCKED_EXACT = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
}


@dataclass(frozen=True)
class CanonicalUrl:
    value: str
    display: str
    has_query: bool
    scheme: str
    host: str
    port: int
    target: str


def _host_ascii(host: str) -> str:
    if "%" in host:
        raise WebSourceUrlInvalid
    candidate = host.rstrip(".")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    try:
        return idna.encode(candidate, uts46=True, std3_rules=True).decode("ascii").lower()
    except (idna.IDNAError, UnicodeError) as exc:
        raise WebSourceUrlInvalid from exc


def canonicalize_url(raw: str, *, base: str | None = None) -> CanonicalUrl:
    if not isinstance(raw, str) or not raw or _CONTROL.search(raw) or "\\" in raw:
        raise WebSourceUrlInvalid
    if len(raw.encode("utf-8")) > settings.WEB_IMPORT_MAX_URL_BYTES:
        raise WebSourceUrlInvalid
    value = urljoin(base, raw) if base else raw
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise WebSourceUrlInvalid from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise WebSourceUrlInvalid
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise WebSourceUrlInvalid
    scheme = parsed.scheme.lower()
    host = _host_ascii(parsed.hostname)
    port = port or (443 if scheme == "https" else 80)
    if (
        port not in {80, 443}
        or (scheme == "http" and port != 80)
        or (scheme == "https" and port != 443)
    ):
        raise WebSourceUrlNotAllowed
    if _NUMERICISH.fullmatch(host):
        try:
            host = str(ipaddress.ip_address(host.strip("[]")))
        except ValueError as exc:
            raise WebSourceUrlNotAllowed from exc
    path = parsed.path or "/"
    netloc = f"[{host}]" if ":" in host else host
    canonical = urlunsplit(SplitResult(scheme, netloc, path, parsed.query, ""))
    display = urlunsplit(SplitResult(scheme, netloc, path, "", ""))
    target = path + (f"?{parsed.query}" if parsed.query else "")
    return CanonicalUrl(canonical, display, bool(parsed.query), scheme, host, port, target)


def _test_allowed(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if getattr(settings, "APP_ENV", "") != "test":
        return False
    return any(address in network for network in settings.WEB_IMPORT_TEST_ALLOWED_CIDRS)


def is_allowed_address(raw: str) -> bool:
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return _test_allowed(address) or (address.is_global and address not in _BLOCKED_EXACT)


def resolve_and_validate(host: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        from .exceptions import WebSourceTransientError

        raise WebSourceTransientError from exc
    addresses = tuple(sorted({str(item[4][0]) for item in infos}))
    if not addresses or any(not is_allowed_address(address) for address in addresses):
        raise WebSourceUrlNotAllowed
    return addresses


def fingerprint(label: str, value: str) -> str:
    key = hmac.new(
        settings.WEB_IMPORT_IDEMPOTENCY_HMAC_KEY.encode(),
        f"web-import:{label}:v1".encode(),
        hashlib.sha256,
    ).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
