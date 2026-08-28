from __future__ import annotations

from dataclasses import dataclass

from .platform_health import platform_health_payload


@dataclass(frozen=True)
class PlatformDefinition:
    key: str
    name: str
    category: str
    content_types: tuple[str, ...]
    auth_method: str
    supports_cover: bool = True
    supports_inline_images: bool = True
    supports_tags: bool = True
    supports_scheduling: bool = False
    supports_public_publish: bool = True
    verification_state: str = "validation"


PLATFORMS: tuple[PlatformDefinition, ...] = (
    PlatformDefinition("wechat", "微信公众号", "mainstream", ("long_article",), "official_api", True, True, False, True),
    PlatformDefinition("toutiao", "今日头条", "mainstream", ("long_article",), "browser_session"),
    PlatformDefinition("baijiahao", "百家号", "mainstream", ("long_article",), "browser_session"),
    PlatformDefinition("zhihu", "知乎", "mainstream", ("long_article", "answer"), "browser_session"),
    PlatformDefinition("xiaohongshu", "小红书", "mainstream", ("image_post",), "browser_session"),
    PlatformDefinition("weibo", "微博", "mainstream", ("short_post", "long_article"), "browser_session"),
    PlatformDefinition("bilibili", "B站专栏", "mainstream", ("long_article",), "browser_session"),
    PlatformDefinition("douyin", "抖音图文", "mainstream", ("image_post",), "browser_session"),
    PlatformDefinition("qq", "企鹅号", "mainstream", ("long_article",), "browser_session"),
    PlatformDefinition("sohu", "搜狐号", "mainstream", ("long_article",), "browser_session", verification_state="validation"),
    PlatformDefinition("csdn", "CSDN", "professional", ("technical_article",), "browser_session"),
    PlatformDefinition("juejin", "掘金", "professional", ("technical_article",), "browser_session"),
    PlatformDefinition("cnblogs", "博客园", "professional", ("technical_article",), "browser_session"),
    PlatformDefinition("oschina", "开源中国", "professional", ("technical_article",), "browser_session"),
    PlatformDefinition("segmentfault", "思否", "professional", ("technical_article",), "browser_session"),
    PlatformDefinition("jianshu", "简书", "professional", ("long_article",), "browser_session"),
    PlatformDefinition("douban", "豆瓣", "professional", ("long_article",), "browser_session"),
)

PLATFORM_BY_KEY = {item.key: item for item in PLATFORMS}


def _platform_runtime_ready(key: str) -> bool:
    if key != "wechat":
        return True
    # Local import avoids a module cycle: wechat_component -> services -> catalog.
    from .wechat_component import component_authorization_ready

    return component_authorization_ready()


def platform_payload(enabled_keys: set[str] | None = None) -> list[dict[str, object]]:
    enabled_keys = enabled_keys or set()
    result: list[dict[str, object]] = []
    for item in PLATFORMS:
        health = platform_health_payload(item.key)
        enabled = item.key in enabled_keys and _platform_runtime_ready(item.key)
        result.append(
            {
                "key": item.key,
                "name": item.name,
                "category": item.category,
                "content_types": list(item.content_types),
                "auth_method": item.auth_method,
                "supports_cover": item.supports_cover,
                "supports_inline_images": item.supports_inline_images,
                "supports_tags": item.supports_tags,
                "supports_scheduling": item.supports_scheduling,
                "supports_public_publish": item.supports_public_publish,
                "verification_state": "ready" if enabled else item.verification_state,
                "authorization_enabled": enabled,
                "runtime_status": health["status"],
                "recent_failures": health["recent_failures"],
            }
        )
    return result
