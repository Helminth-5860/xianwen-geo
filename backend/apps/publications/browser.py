from __future__ import annotations

import base64
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from django.utils import timezone

from apps.ai.credential_crypto import encrypt_secret
from apps.documents.storage import storage_provider

from .models import AuthorizationSession, PlatformAccount, PublicationTarget
from .platforms import browser_spec


class PublicationBrowserUnavailable(RuntimeError):
    pass


class PublicationAuthorizationRequired(RuntimeError):
    pass


class PublicationBrowserFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserPublishResult:
    public_url: str = ""
    external_post_id: str = ""


def _safe_snapshot(page) -> str:
    raw = page.screenshot(type="jpeg", quality=72, full_page=False)
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _looks_authenticated(page, spec) -> bool:
    cookies = page.context.cookies()
    names = {str(row.get("name", "")) for row in cookies}
    has_session_cookie = any(name in names for name in spec.authenticated_cookie_names)
    current = page.url.casefold()
    still_login = any(marker in current for marker in spec.login_path_markers)
    return has_session_cookie and not still_login


def _requires_extra_verification(page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=1500)[:12000]
    except Exception:
        return False
    markers = ("请完成安全验证", "请完成验证", "拖动滑块", "异常验证", "账号存在风险")
    return any(marker in text for marker in markers)


def execute_browser_authorization(session_id: str):
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PublicationBrowserUnavailable("Playwright is not installed") from exc

    try:
        session = AuthorizationSession.objects.select_related("platform__channel", "account").get(
            pk=session_id
        )
    except AuthorizationSession.DoesNotExist:
        return {"status": "missing"}
    if session.status != AuthorizationSession.Status.QUEUED:
        return {"status": session.status}
    spec = browser_spec(session.platform.channel.key)
    if spec is None:
        session.status = AuthorizationSession.Status.NEEDS_INTERACTION
        session.safe_error_code = "PUBLICATION_BROWSER_AUTH_NOT_VALIDATED"
        session.finished_at = timezone.now()
        session.save(update_fields=("status", "safe_error_code", "finished_at", "updated_at"))
        return {"status": session.status}

    session.status = AuthorizationSession.Status.WAITING
    session.started_at = timezone.now()
    session.save(update_fields=("status", "started_at", "updated_at"))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=("--disable-dev-shm-usage", "--no-first-run"),
        )
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 900},
            service_workers="block",
            accept_downloads=False,
        )
        page = context.new_page()
        try:
            page.goto(session.platform.login_url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            last_snapshot = 0.0
            while timezone.now() < session.expires_at:
                current = AuthorizationSession.objects.only("status").get(pk=session.pk)
                if current.status == AuthorizationSession.Status.CANCELLED:
                    return {"status": "cancelled"}
                if _looks_authenticated(page, spec):
                    storage_state = context.storage_state()
                    account = PlatformAccount.objects.get(pk=session.account_id)
                    account.encrypted_auth_state = encrypt_secret(
                        json.dumps(
                            {"kind": "browser_storage_state", "storage_state": storage_state},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
                    account.auth_status = PlatformAccount.AuthStatus.AUTHORIZED
                    account.authorized_at = timezone.now()
                    account.last_auth_check_at = timezone.now()
                    account.display_name = account.display_name or f"{session.platform.channel.name}账号"
                    account.version += 1
                    account.save()
                    AuthorizationSession.objects.filter(pk=session.pk).update(
                        status=AuthorizationSession.Status.AUTHORIZED,
                        login_snapshot_data_url="",
                        safe_error_code="",
                        finished_at=timezone.now(),
                        updated_at=timezone.now(),
                    )
                    return {"status": "authorized"}
                if _requires_extra_verification(page):
                    AuthorizationSession.objects.filter(pk=session.pk).update(
                        status=AuthorizationSession.Status.NEEDS_INTERACTION,
                        login_snapshot_data_url=_safe_snapshot(page),
                        safe_error_code="PUBLICATION_PLATFORM_EXTRA_VERIFICATION_REQUIRED",
                        finished_at=timezone.now(),
                        updated_at=timezone.now(),
                    )
                    PlatformAccount.objects.filter(pk=session.account_id).update(
                        auth_status=PlatformAccount.AuthStatus.NEEDS_VERIFICATION,
                        updated_at=timezone.now(),
                    )
                    return {"status": "needs_interaction"}
                if time.monotonic() - last_snapshot >= 8:
                    AuthorizationSession.objects.filter(pk=session.pk).update(
                        login_snapshot_data_url=_safe_snapshot(page),
                        last_snapshot_at=timezone.now(),
                        updated_at=timezone.now(),
                    )
                    last_snapshot = time.monotonic()
                page.wait_for_timeout(2500)
        except Exception:
            AuthorizationSession.objects.filter(pk=session.pk).update(
                status=AuthorizationSession.Status.FAILED,
                login_snapshot_data_url="",
                safe_error_code="PUBLICATION_AUTH_PAGE_UNAVAILABLE",
                finished_at=timezone.now(),
                updated_at=timezone.now(),
            )
            PlatformAccount.objects.filter(pk=session.account_id).update(
                auth_status=PlatformAccount.AuthStatus.FAILED,
                updated_at=timezone.now(),
            )
            return {"status": "failed"}
        finally:
            context.close()
            browser.close()

    AuthorizationSession.objects.filter(pk=session.pk).update(
        status=AuthorizationSession.Status.EXPIRED,
        login_snapshot_data_url="",
        safe_error_code="PUBLICATION_AUTH_SESSION_EXPIRED",
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )
    PlatformAccount.objects.filter(pk=session.account_id).update(
        auth_status=PlatformAccount.AuthStatus.EXPIRED,
        updated_at=timezone.now(),
    )
    return {"status": "expired"}


def _first_visible(page, selectors: tuple[str, ...]):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1200):
                return locator
        except Exception:
            continue
    return None


def _asset_temp_file(image):
    suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(
        image.mime_type, ".img"
    )
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    path = Path(handle.name)
    try:
        with storage_provider().open_object(image.object_key) as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        handle.flush()
    finally:
        handle.close()
    return path


def _click_publish(page, texts: tuple[str, ...]) -> bool:
    for text in texts:
        for locator in (
            page.get_by_role("button", name=text, exact=False).first,
            page.get_by_text(text, exact=True).first,
        ):
            try:
                if locator.is_visible(timeout=1200) and locator.is_enabled():
                    locator.click(timeout=5000)
                    return True
            except Exception:
                continue
    return False


def publish_browser_target(target: PublicationTarget, auth_state: dict) -> BrowserPublishResult:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PublicationBrowserUnavailable("Playwright is not installed") from exc

    spec = browser_spec(target.platform.channel.key)
    storage_state = auth_state.get("storage_state") if auth_state.get("kind") == "browser_storage_state" else None
    if spec is None or not isinstance(storage_state, dict):
        raise PublicationAuthorizationRequired("authorization unavailable")

    payload = target.payload_snapshot or {}
    title = str(payload.get("title", "")).strip()
    content = str(payload.get("content", "")).strip()
    if not title or not content:
        raise PublicationBrowserFailed("prepared content missing")

    visuals = list(target.job.visuals.select_related("image").filter(target__isnull=True))
    cover = next((row.image for row in visuals if row.role == "cover"), None)
    temp_paths: list[Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=("--disable-dev-shm-usage", "--no-first-run"),
        )
        context = browser.new_context(
            storage_state=storage_state,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1365, "height": 900},
            service_workers="block",
            accept_downloads=False,
        )
        page = context.new_page()
        try:
            page.goto(target.platform.publish_url, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            if not _looks_authenticated(page, spec):
                raise PublicationAuthorizationRequired("session expired")
            if _requires_extra_verification(page):
                raise PublicationAuthorizationRequired("extra verification required")

            title_box = _first_visible(page, spec.title_selectors)
            content_box = _first_visible(page, spec.content_selectors)
            if title_box is None or content_box is None:
                raise PublicationBrowserFailed("publisher editor changed")
            title_box.fill(title[:120])
            content_box.fill(content)

            if cover is not None:
                path = _asset_temp_file(cover)
                temp_paths.append(path)
                uploaded = False
                for selector in spec.cover_selectors:
                    try:
                        locator = page.locator(selector).first
                        if selector.startswith("input"):
                            locator.set_input_files(str(path), timeout=4000)
                            uploaded = True
                            break
                        if locator.is_visible(timeout=1000):
                            locator.click(timeout=3000)
                            file_input = page.locator('input[type="file"]').last
                            file_input.set_input_files(str(path), timeout=4000)
                            uploaded = True
                            break
                    except Exception:
                        continue
                if uploaded:
                    page.wait_for_timeout(1200)

            before_url = page.url
            if not _click_publish(page, spec.publish_texts):
                raise PublicationBrowserFailed("publish control unavailable")
            page.wait_for_timeout(2500)
            if _requires_extra_verification(page):
                raise PublicationAuthorizationRequired("extra verification required")
            try:
                text = page.locator("body").inner_text(timeout=2000)[:20000]
            except Exception:
                text = ""
            success = any(marker in text for marker in ("发布成功", "提交成功", "发布完成"))
            current_url = page.url
            if not success and current_url == before_url:
                raise PublicationBrowserFailed("publish result not confirmed")
            public_url = current_url if current_url != before_url and "publish" not in current_url else ""
            return BrowserPublishResult(public_url=public_url)
        finally:
            context.close()
            browser.close()
            for path in temp_paths:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
