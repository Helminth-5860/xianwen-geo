from __future__ import annotations

import hashlib
import math
import re
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from apps.search_discovery.normalization import COMMON_CN_SUFFIXES, TRACKING_KEYS, normalize_url, parse_provider_datetime, root_domain
from apps.search_discovery.source_quality import KNOWN_DOMAINS, classify_source, freshness_score, relevance_score, visibility_score


def source_weight(*, authority: int, relevance: int, visibility: int, freshness: int) -> Decimal:
    value = authority * 0.35 + relevance * 0.30 + visibility * 0.20 + freshness * 0.15
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def saturation_score(actual: int, target: int) -> float:
    if actual <= 0:
        return 0.0
    return min(100.0, 100.0 * math.log1p(actual) / math.log1p(target))


def calculate_index(items: list[dict]) -> tuple[Decimal, dict[str, float]]:
    if not items:
        return Decimal("0.00"), {"exposure": 0.0, "diversity": 0.0, "authority": 0.0, "visibility": 0.0, "freshness": 0.0}
    exposure = saturation_score(len(items), 500)
    domains = {item["root_domain"] for item in items if item["root_domain"]}
    diversity = saturation_score(len(domains), 80)
    authority = sum(item["authority_score"] for item in items) / len(items)
    visibility = sum(item["visibility_score"] for item in items) / len(items)
    freshness = sum(item["freshness_score"] for item in items) / len(items)
    value = exposure * 0.25 + diversity * 0.25 + authority * 0.25 + visibility * 0.15 + freshness * 0.10
    factors = {"exposure": round(exposure, 2), "diversity": round(diversity, 2), "authority": round(authority, 2), "visibility": round(visibility, 2), "freshness": round(freshness, 2)}
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), factors


def normalized_title_signature(title: str) -> str:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", title.casefold())
    for suffix in ("手机新浪网", "新浪财经", "腾讯新闻", "网易新闻", "搜狐网", "百度百家号"):
        normalized = normalized.replace(suffix.casefold(), "")
    if len(normalized) < 8:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def is_recent_30d(published_at) -> bool:
    if published_at is None:
        return False
    return published_at >= timezone.now() - timedelta(days=30)


__all__ = ["COMMON_CN_SUFFIXES", "KNOWN_DOMAINS", "TRACKING_KEYS", "calculate_index", "classify_source", "freshness_score", "is_recent_30d", "normalize_url", "normalized_title_signature", "parse_provider_datetime", "relevance_score", "root_domain", "saturation_score", "source_weight", "visibility_score"]
