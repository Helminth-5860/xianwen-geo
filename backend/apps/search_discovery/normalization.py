from __future__ import annotations

from datetime import datetime, time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

TRACKING_KEYS = {
    "gclid",
    "fbclid",
    "msclkid",
    "spm",
    "from",
    "source",
}
COMMON_CN_SUFFIXES = {
    "com.cn",
    "net.cn",
    "org.cn",
    "gov.cn",
    "ac.cn",
    "edu.cn",
}


def normalize_url(url: str) -> tuple[str, str, str] | None:
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    netloc = host
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    if port and not default_port:
        netloc = f"{host}:{port}"
    clean_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_KEYS:
            continue
        clean_pairs.append((key, value))
    query = urlencode(clean_pairs, doseq=True)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    normalized = urlunsplit(("https", netloc, path, query, ""))
    return normalized, host, root_domain(host)


def root_domain(host: str) -> str:
    labels = [part for part in host.split(".") if part]
    if len(labels) <= 2:
        return host
    suffix2 = ".".join(labels[-2:])
    if suffix2 in COMMON_CN_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return suffix2


def parse_provider_datetime(raw: str):
    value = (raw or "").strip()
    if not value:
        return None
    dt = parse_datetime(value)
    if dt is not None:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt
    day = parse_date(value[:10])
    if day is None:
        return None
    midday = datetime.combine(day, time(hour=12))
    return timezone.make_aware(midday, timezone.get_current_timezone())
