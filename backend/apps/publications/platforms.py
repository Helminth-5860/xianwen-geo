from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserPlatformSpec:
    key: str
    authenticated_cookie_names: tuple[str, ...]
    login_path_markers: tuple[str, ...]
    title_selectors: tuple[str, ...] = ()
    content_selectors: tuple[str, ...] = ()
    publish_texts: tuple[str, ...] = ("发布", "提交")
    cover_selectors: tuple[str, ...] = ()


# Runtime specs intentionally contain only normal login/publishing selectors.
# Xianwen does not hide webdriver, forge browser fingerprints, bypass captcha,
# or simulate security-verification input. Any platform verification challenge
# is handed back to the customer as a re-authorization requirement.
BROWSER_PLATFORM_SPECS: dict[str, BrowserPlatformSpec] = {
    "toutiao": BrowserPlatformSpec(
        key="toutiao",
        authenticated_cookie_names=("sessionid", "sid_tt"),
        login_path_markers=("login", "passport"),
        title_selectors=("textarea",),
        content_selectors=('div[contenteditable="true"]',),
        publish_texts=("发布", "预览并发布"),
        cover_selectors=(".article-cover-add", 'input[type="file"]'),
    ),
    "zhihu": BrowserPlatformSpec(
        key="zhihu",
        authenticated_cookie_names=("z_c0",),
        login_path_markers=("signin", "login"),
        title_selectors=("textarea", 'input[placeholder*="标题"]'),
        content_selectors=('div[contenteditable="true"]',),
        publish_texts=("发布",),
    ),
    "xiaohongshu": BrowserPlatformSpec(
        key="xiaohongshu",
        authenticated_cookie_names=("web_session",),
        login_path_markers=("login",),
        title_selectors=('input[placeholder*="标题"]', "input"),
        content_selectors=('div[contenteditable="true"]', "textarea"),
        publish_texts=("发布",),
        cover_selectors=('input[type="file"]',),
    ),
    "weibo": BrowserPlatformSpec(
        key="weibo",
        authenticated_cookie_names=("SUB",),
        login_path_markers=("login", "passport"),
        content_selectors=("textarea", 'div[contenteditable="true"]'),
        publish_texts=("发布",),
    ),
    "bilibili": BrowserPlatformSpec(
        key="bilibili",
        authenticated_cookie_names=("SESSDATA",),
        login_path_markers=("login", "passport"),
        title_selectors=('input[placeholder*="标题"]', "input"),
        content_selectors=('div[contenteditable="true"]',),
        publish_texts=("发布", "提交"),
        cover_selectors=('input[type="file"]',),
    ),
    "douyin": BrowserPlatformSpec(
        key="douyin",
        authenticated_cookie_names=("sessionid", "sessionid_ss"),
        login_path_markers=("login", "passport"),
        title_selectors=('input[placeholder*="标题"]', "input"),
        content_selectors=("textarea", 'div[contenteditable="true"]'),
        publish_texts=("发布",),
        cover_selectors=('input[type="file"]',),
    ),
    "qq": BrowserPlatformSpec(
        key="qq",
        authenticated_cookie_names=("uin", "skey"),
        login_path_markers=("login",),
        title_selectors=('input[placeholder*="标题"]', "textarea"),
        content_selectors=('div[contenteditable="true"]',),
        publish_texts=("发布",),
    ),
    "csdn": BrowserPlatformSpec(
        key="csdn",
        authenticated_cookie_names=("UserName", "UserToken", "uuid_tt_dd"),
        login_path_markers=("login", "passport"),
        title_selectors=('input[placeholder*="标题"]', "input"),
        content_selectors=("textarea", '.monaco-editor textarea'),
        publish_texts=("发布文章", "发布"),
    ),
    "juejin": BrowserPlatformSpec(
        key="juejin",
        authenticated_cookie_names=("sessionid", "passport_csrf_token"),
        login_path_markers=("login",),
        title_selectors=('input[placeholder*="标题"]', "input"),
        content_selectors=("textarea", '.bytemd-editor textarea'),
        publish_texts=("发布",),
    ),
    "baijiahao": BrowserPlatformSpec(
        key="baijiahao",
        authenticated_cookie_names=("BDUSS", "STOKEN"),
        login_path_markers=("login", "passport"),
        title_selectors=('input[placeholder*="标题"]', "textarea"),
        content_selectors=('div[contenteditable="true"]',),
        publish_texts=("发布",),
        cover_selectors=('input[type="file"]',),
    ),
    "douban": BrowserPlatformSpec(
        key="douban",
        authenticated_cookie_names=("dbcl2",),
        login_path_markers=("login", "passport"),
        title_selectors=("input",),
        content_selectors=("textarea", 'div[contenteditable="true"]'),
        publish_texts=("发表", "发布"),
    ),
}


def browser_spec(platform_key: str) -> BrowserPlatformSpec | None:
    return BROWSER_PLATFORM_SPECS.get(platform_key)
