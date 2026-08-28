from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .models import SourceIndexItem

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
KNOWN_DOMAINS: dict[str, tuple[str, int]] = {
    "xinhuanet.com": (SourceIndexItem.SourceType.NEWS_MEDIA, 98),
    "people.com.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 98),
    "cctv.com": (SourceIndexItem.SourceType.NEWS_MEDIA, 97),
    "chinanews.com.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 96),
    "gmw.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 95),
    "cnr.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 95),
    "ce.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 94),
    "china.com.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 94),
    "news.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 96),
    "thepaper.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 90),
    "bjnews.com.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 90),
    "yicai.com": (SourceIndexItem.SourceType.NEWS_MEDIA, 89),
    "caixin.com": (SourceIndexItem.SourceType.NEWS_MEDIA, 90),
    "finance.sina.com.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 84),
    "sina.com.cn": (SourceIndexItem.SourceType.NEWS_MEDIA, 82),
    "163.com": (SourceIndexItem.SourceType.NEWS_MEDIA, 82),
    "qq.com": (SourceIndexItem.SourceType.NEWS_MEDIA, 82),
    "sohu.com": (SourceIndexItem.SourceType.NEWS_MEDIA, 80),
    "ifeng.com": (SourceIndexItem.SourceType.NEWS_MEDIA, 84),
    "baijiahao.baidu.com": (SourceIndexItem.SourceType.CONTENT_PLATFORM, 58),
    "mp.weixin.qq.com": (SourceIndexItem.SourceType.CONTENT_PLATFORM, 60),
    "zhihu.com": (SourceIndexItem.SourceType.CONTENT_PLATFORM, 58),
    "toutiao.com": (SourceIndexItem.SourceType.CONTENT_PLATFORM, 58),
    "douyin.com": (SourceIndexItem.SourceType.CONTENT_PLATFORM, 55),
    "weibo.com": (SourceIndexItem.SourceType.CONTENT_PLATFORM, 58),
    "tieba.baidu.com": (SourceIndexItem.SourceType.FORUM_COMMUNITY, 45),
    "qcc.com": (SourceIndexItem.SourceType.DIRECTORY_BUSINESS, 55),
    "tianyancha.com": (SourceIndexItem.SourceType.DIRECTORY_BUSINESS, 55),
    "aiqicha.baidu.com": (SourceIndexItem.SourceType.DIRECTORY_BUSINESS, 53),
    "11467.com": (SourceIndexItem.SourceType.DIRECTORY_BUSINESS, 38),
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
    # Scheme is deliberately canonicalized for identity; original_url remains untouched
    # for navigation.
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


def classify_source(
    *,
    root: str,
    domain: str,
    website: str,
    title: str,
    self_domains: set[str],
) -> tuple[str, int]:
    if root in self_domains or domain in self_domains:
        return SourceIndexItem.SourceType.ENTERPRISE_SITE, 65
    if root.endswith("gov.cn") or domain.endswith("gov.cn"):
        return SourceIndexItem.SourceType.GOVERNMENT_ASSOCIATION, 98
    for known, classification in KNOWN_DOMAINS.items():
        if domain == known or domain.endswith(f".{known}") or root == known:
            return classification
    text = f"{website} {title}".lower()
    if any(token in text for token in ("人民政府", "政府网", "委员会", "管理局", "协会", "学会", "商会")):
        return SourceIndexItem.SourceType.GOVERNMENT_ASSOCIATION, 88
    if any(token in text for token in ("新闻网", "新闻中心", "日报", "晚报", "报业", "电视台", "融媒体", "广播电视")):
        return SourceIndexItem.SourceType.NEWS_MEDIA, 80
    if any(token in text for token in ("行业网", "产业网", "财经网", "科技网", "商业评论", "行业媒体", "研究院", "研究中心")):
        return SourceIndexItem.SourceType.INDUSTRY_MEDIA, 74
    forum_domain = any(token in domain for token in ("bbs.", "forum."))
    forum_label = any(token in text for token in ("论坛", "社区", "贴吧"))
    if forum_domain or forum_label:
        return SourceIndexItem.SourceType.FORUM_COMMUNITY, 44
    if any(token in text for token in ("企业信息", "工商信息", "黄页", "企业名录", "信用查询")):
        return SourceIndexItem.SourceType.DIRECTORY_BUSINESS, 43
    if any(token in domain for token in ("weixin", "weibo", "zhihu", "toutiao", "baijiahao")):
        return SourceIndexItem.SourceType.CONTENT_PLATFORM, 55
    if any(token in text for token in ("号作者", "自媒体", "博客")):
        return SourceIndexItem.SourceType.CONTENT_PLATFORM, 50
    return SourceIndexItem.SourceType.OTHER, 42


def relevance_score(
    *,
    title: str,
    snippet: str,
    website: str,
    anchors: list[str],
    official_name: str,
    matched_queries: set[str],
) -> int:
    title_l = title.casefold()
    snippet_l = snippet.casefold()
    website_l = website.casefold()
    official = official_name.casefold().strip()
    if official and official in title_l:
        return 100
    if official and official in snippet_l:
        return 90
    for anchor in anchors:
        token = anchor.casefold().strip()
        if not token or len(token) < 2:
            continue
        if token in title_l:
            return 92
        if token in snippet_l:
            return 80
        if token in website_l:
            return 70
    # A search hit is not counted merely because it came from the exact-name query.
    # Without a visible subject mention in title/snippet/site metadata we cannot verify it.
    if official and any(query.casefold().strip() == official for query in matched_queries):
        return 45
    return 35


def visibility_score(best_rank: int) -> int:
    if best_rank <= 3:
        return 100
    if best_rank <= 10:
        return 85
    if best_rank <= 20:
        return 70
    if best_rank <= 30:
        return 55
    return 40


def freshness_score(published_at) -> int:
    if published_at is None:
        return 50
    age = timezone.now() - published_at
    days = max(0, age.days)
    if days <= 30:
        return 100
    if days <= 90:
        return 85
    if days <= 180:
        return 70
    if days <= 365:
        return 55
    if days <= 730:
        return 40
    return 25


def source_weight(*, authority: int, relevance: int, visibility: int, freshness: int) -> Decimal:
    value = authority * 0.35 + relevance * 0.30 + visibility * 0.20 + freshness * 0.15
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def saturation_score(actual: int, target: int) -> float:
    if actual <= 0:
        return 0.0
    return min(100.0, 100.0 * math.log1p(actual) / math.log1p(target))


def calculate_index(items: list[dict]) -> tuple[Decimal, dict[str, float]]:
    if not items:
        return Decimal("0.00"), {
            "exposure": 0.0,
            "diversity": 0.0,
            "authority": 0.0,
            "visibility": 0.0,
            "freshness": 0.0,
        }
    exposure = saturation_score(len(items), 500)
    domains = {item["root_domain"] for item in items if item["root_domain"]}
    diversity = saturation_score(len(domains), 80)
    authority = sum(item["authority_score"] for item in items) / len(items)
    visibility = sum(item["visibility_score"] for item in items) / len(items)
    freshness = sum(item["freshness_score"] for item in items) / len(items)
    value = (
        exposure * 0.25
        + diversity * 0.25
        + authority * 0.25
        + visibility * 0.15
        + freshness * 0.10
    )
    factors = {
        "exposure": round(exposure, 2),
        "diversity": round(diversity, 2),
        "authority": round(authority, 2),
        "visibility": round(visibility, 2),
        "freshness": round(freshness, 2),
    }
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
