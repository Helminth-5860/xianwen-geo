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


def platform_payload(
    enabled_keys: set[str] | None = None,
    *,
    worker_capabilities: dict[str, frozenset[str]] | None = None,
    implemented_capabilities: dict[str, frozenset[str]] | None = None,
    validation_keys: set[str] | None = None,
    worker_available: bool = False,
    internal_validation: bool = False,
) -> list[dict[str, object]]:
    # Local import avoids a module cycle: capabilities -> catalog -> capabilities.
    from .capabilities import (
        authorization_verified,
        draft_verified,
        image_upload_verified,
        public_publish_verified,
    )

    enabled_keys = enabled_keys or set()
    worker_capabilities = worker_capabilities or {}
    implemented_capabilities = implemented_capabilities or {}
    validation_keys = validation_keys or set()
    result: list[dict[str, object]] = []
    for item in PLATFORMS:
        health = platform_health_payload(item.key)
        configured = item.key in enabled_keys
        validation_configured = item.key in validation_keys
        runtime_ready = _platform_runtime_ready(item.key)
        verified = worker_capabilities.get(item.key, frozenset())
        implemented = implemented_capabilities.get(item.key, frozenset())
        verified_auth = bool(
            configured
            and runtime_ready
            and worker_available
            and authorization_verified(verified)
        )
        validation_auth = bool(
            validation_configured
            and internal_validation
            and runtime_ready
            and worker_available
            and authorization_verified(implemented)
        )
        auth_ready = bool(verified_auth or validation_auth)
        draft_ready = bool(verified_auth and draft_verified(verified))
        draft_validation_ready = bool(validation_auth and draft_verified(implemented))
        image_upload_ready = bool(verified_auth and image_upload_verified(verified))
        image_upload_validation_ready = bool(
            validation_auth and image_upload_verified(implemented)
        )
        public_ready = bool(
            verified_auth
            and item.supports_public_publish
            and public_publish_verified(verified)
        )
        authorization_enabled = auth_ready

        if not configured and not validation_configured:
            availability_stage = "closed"
            availability_message = "该平台尚未开放"
        elif not worker_available:
            availability_stage = "temporarily_unavailable"
            availability_message = "平台服务暂时不可用，请稍后再试"
        elif not runtime_ready:
            availability_stage = "internal_validation"
            availability_message = "该平台授权服务正在准备中"
        elif not auth_ready:
            availability_stage = "internal_validation"
            availability_message = "该平台正在准备中，暂未开放"
        elif public_ready:
            availability_stage = "public_ready"
            availability_message = "可授权并参与自动发文"
        elif verified_auth and draft_ready:
            availability_stage = "draft_ready"
            availability_message = "可授权并保存草稿，公开发布尚未开放"
        elif verified_auth:
            availability_stage = "authorization_ready"
            availability_message = "可授权账号，公开发布尚未开放"
        elif validation_auth and draft_validation_ready:
            availability_stage = "draft_validation"
            availability_message = "当前可体验账号授权和草稿保存，自动公开发布暂未开放"
        elif validation_auth:
            availability_stage = "internal_validation"
            availability_message = "当前可体验账号授权，自动公开发布暂未开放"
        else:
            availability_stage = "internal_validation"
            availability_message = "该平台正在准备中，暂未开放"

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
                # An environment allowlist is only a rollout candidate gate. The
                # worker's verified declaration remains the fail-closed capability
                # source of truth, so configuration alone can never advertise a
                # production publishing ability.
                "authorization_verified": verified_auth,
                "authorization_validation_available": validation_auth,
                "supports_draft": draft_ready,
                "image_upload_verified": image_upload_ready,
                "draft_validation_available": draft_validation_ready,
                "image_upload_validation_available": image_upload_validation_ready,
                "supports_public_publish": public_ready,
                "can_enable_auto": public_ready,
                "verification_state": (
                    "ready"
                    if public_ready
                    else (
                        "draft"
                        if authorization_enabled and (draft_ready or draft_validation_ready)
                        else (
                            "authorization"
                            if verified_auth
                            else (
                                "internal"
                                if authorization_enabled
                                else (
                                    "unavailable"
                                    if configured and not worker_available
                                    else item.verification_state
                                )
                            )
                        )
                    )
                ),
                "availability_stage": availability_stage,
                "availability_message": availability_message,
                "authorization_enabled": authorization_enabled,
                "runtime_status": health["status"],
                "recent_failures": health["recent_failures"],
            }
        )
    return result
