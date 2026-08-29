from __future__ import annotations

from django.utils import timezone

GOVERNMENT_ASSOCIATION = "government_association"
NEWS_MEDIA = "news_media"
INDUSTRY_MEDIA = "industry_media"
ENTERPRISE_SITE = "enterprise_site"
CONTENT_PLATFORM = "content_platform"
DIRECTORY_BUSINESS = "directory_business"
FORUM_COMMUNITY = "forum_community"
OTHER = "other"

KNOWN_DOMAINS: dict[str, tuple[str, int]] = {
    "xinhuanet.com": (NEWS_MEDIA, 98),
    "people.com.cn": (NEWS_MEDIA, 98),
    "cctv.com": (NEWS_MEDIA, 97),
    "chinanews.com.cn": (NEWS_MEDIA, 96),
    "gmw.cn": (NEWS_MEDIA, 95),
    "cnr.cn": (NEWS_MEDIA, 95),
    "ce.cn": (NEWS_MEDIA, 94),
    "china.com.cn": (NEWS_MEDIA, 94),
    "news.cn": (NEWS_MEDIA, 96),
    "thepaper.cn": (NEWS_MEDIA, 90),
    "bjnews.com.cn": (NEWS_MEDIA, 90),
    "yicai.com": (NEWS_MEDIA, 89),
    "caixin.com": (NEWS_MEDIA, 90),
    "finance.sina.com.cn": (NEWS_MEDIA, 84),
    "sina.com.cn": (NEWS_MEDIA, 82),
    "163.com": (NEWS_MEDIA, 82),
    "qq.com": (NEWS_MEDIA, 82),
    "sohu.com": (NEWS_MEDIA, 80),
    "ifeng.com": (NEWS_MEDIA, 84),
    "baijiahao.baidu.com": (CONTENT_PLATFORM, 58),
    "mp.weixin.qq.com": (CONTENT_PLATFORM, 60),
    "zhihu.com": (CONTENT_PLATFORM, 58),
    "toutiao.com": (CONTENT_PLATFORM, 58),
    "douyin.com": (CONTENT_PLATFORM, 55),
    "weibo.com": (CONTENT_PLATFORM, 58),
    "tieba.baidu.com": (FORUM_COMMUNITY, 45),
    "qcc.com": (DIRECTORY_BUSINESS, 55),
    "tianyancha.com": (DIRECTORY_BUSINESS, 55),
    "aiqicha.baidu.com": (DIRECTORY_BUSINESS, 53),
    "11467.com": (DIRECTORY_BUSINESS, 38),
}


def classify_source(
    *,
    root: str,
    domain: str,
    website: str,
    title: str,
    self_domains: set[str],
) -> tuple[str, int]:
    if root in self_domains or domain in self_domains:
        return ENTERPRISE_SITE, 65
    if root.endswith("gov.cn") or domain.endswith("gov.cn"):
        return GOVERNMENT_ASSOCIATION, 98
    for known, classification in KNOWN_DOMAINS.items():
        if domain == known or domain.endswith(f".{known}") or root == known:
            return classification

    text = f"{website} {title}".lower()
    government_tokens = (
        "人民政府",
        "政府网",
        "委员会",
        "管理局",
        "协会",
        "学会",
        "商会",
    )
    if any(token in text for token in government_tokens):
        return GOVERNMENT_ASSOCIATION, 88
    news_tokens = (
        "新闻网",
        "新闻中心",
        "日报",
        "晚报",
        "报业",
        "电视台",
        "融媒体",
        "广播电视",
    )
    if any(token in text for token in news_tokens):
        return NEWS_MEDIA, 80
    industry_tokens = (
        "行业网",
        "产业网",
        "财经网",
        "科技网",
        "商业评论",
        "行业媒体",
        "研究院",
        "研究中心",
    )
    if any(token in text for token in industry_tokens):
        return INDUSTRY_MEDIA, 74

    forum_domain = any(token in domain for token in ("bbs.", "forum."))
    forum_label = any(token in text for token in ("论坛", "社区", "贴吧"))
    if forum_domain or forum_label:
        return FORUM_COMMUNITY, 44
    if any(
        token in text
        for token in (
            "企业信息",
            "工商信息",
            "黄页",
            "企业名录",
            "信用查询",
        )
    ):
        return DIRECTORY_BUSINESS, 43
    if any(
        token in domain
        for token in (
            "weixin",
            "weibo",
            "zhihu",
            "toutiao",
            "baijiahao",
        )
    ):
        return CONTENT_PLATFORM, 55
    if any(token in text for token in ("号作者", "自媒体", "博客")):
        return CONTENT_PLATFORM, 50
    return OTHER, 42


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
    if official and any(
        query.casefold().strip() == official for query in matched_queries
    ):
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
