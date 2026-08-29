from __future__ import annotations

from django.core.cache import cache
from django.utils import timezone

from .models import PlatformAccount, PlatformAuthorizationSession
from .services import PublishingInputError, complete_authorization_session, create_authorization_session
from .wechat_component import WechatComponentUnavailable, begin_wechat_component_authorization
from .worker_client import (
    PublishingWorkerError,
    delete_authorization_session,
    get_authorization_session,
    start_authorization_session,
)


_TERMINAL = {
    PlatformAuthorizationSession.Status.SUCCEEDED,
    PlatformAuthorizationSession.Status.FAILED,
    PlatformAuthorizationSession.Status.EXPIRED,
}


def _safe_remote_label(value: object, *, max_length: int = 255) -> str:
    """Keep worker-provided account labels bounded and free of control whitespace."""

    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", "").split())[:max_length]


def _mark_failed(session: PlatformAuthorizationSession, code: str) -> None:
    session.status = PlatformAuthorizationSession.Status.FAILED
    session.safe_error_code = code
    session.completed_at = timezone.now()
    session.save(update_fields=("status", "safe_error_code", "completed_at", "updated_at"))
    if session.account_id:
        PlatformAccount.objects.filter(id=session.account_id).update(
            status=PlatformAccount.Status.ACTION_REQUIRED,
            last_error_code=code,
            last_checked_at=timezone.now(),
        )


def begin_browser_authorization(*, user, subject_id, platform_key: str) -> PlatformAuthorizationSession:
    """Start the platform's approved authorization flow.

    The historical function name is kept for API compatibility; official-API platforms
    are routed to their formal OAuth/component flow rather than the browser worker.
    """
    session, one_time_token = create_authorization_session(
        user=user,
        subject_id=subject_id,
        platform_key=platform_key,
    )

    # Repeated clicks reuse the live database session.  Only the request that
    # received the newly issued token is allowed to launch a worker browser.
    if not one_time_token:
        return session

    if session.auth_method == PlatformAccount.AuthMethod.OFFICIAL_API:
        if platform_key != "wechat":
            _mark_failed(session, "official_authorization_required")
            raise PublishingInputError("该平台的正式授权尚未开放")
        try:
            return begin_wechat_component_authorization(session)
        except WechatComponentUnavailable as exc:
            _mark_failed(session, "platform_unavailable")
            raise PublishingInputError("微信公众号正式授权暂未就绪，请稍后再试") from exc

    try:
        remote = start_authorization_session(
            session_id=str(session.id),
            platform_key=platform_key,
            expires_at=session.expires_at,
        )
    except PublishingWorkerError as exc:
        code = {
            "platform_not_ready": "platform_unavailable",
            "worker_not_configured": "platform_unavailable",
            "worker_unavailable": "platform_unavailable",
        }.get(exc.code, "platform_unavailable")
        _mark_failed(session, code)
        raise PublishingInputError("当前平台授权暂不可用，请稍后再试") from exc

    session.remote_session_ref = str(remote.get("remote_session_ref") or "")[:255]
    session.action_url = str(remote.get("action_url") or "")
    session.status = PlatformAuthorizationSession.Status.WAITING_USER
    session.started_at = timezone.now()
    session.save(
        update_fields=(
            "remote_session_ref",
            "action_url",
            "status",
            "started_at",
            "updated_at",
        )
    )

    # Do not depend on the browser UI staying open: the backend itself keeps polling
    # the worker and imports the encrypted session credentials as soon as login succeeds.
    from .tasks import sync_authorization_session_task

    sync_authorization_session_task.delay(str(session.pk))
    return session


def sync_authorization_session(session: PlatformAuthorizationSession) -> PlatformAuthorizationSession:
    # Both the UI and the background task may poll the same authorization session.
    # A short distributed cache lock prevents credentials being imported twice.
    lock_key = f"publishing:auth-sync:{session.pk}"
    if not cache.add(lock_key, "1", timeout=20):
        session.refresh_from_db()
        return session
    try:
        session.refresh_from_db()
        if session.status in _TERMINAL:
            return session
        if session.expires_at <= timezone.now():
            session.status = PlatformAuthorizationSession.Status.EXPIRED
            session.safe_error_code = "authorization_timeout"
            session.completed_at = timezone.now()
            session.save(update_fields=("status", "safe_error_code", "completed_at", "updated_at"))
            if session.auth_method == PlatformAccount.AuthMethod.BROWSER_SESSION and session.remote_session_ref:
                delete_authorization_session(remote_session_ref=session.remote_session_ref)
            return session

        # Official component/OAuth flows complete asynchronously through their signed callback.
        # Polling this endpoint only reads the database state; it must never send the official
        # authorization reference to the browser worker.
        if session.auth_method == PlatformAccount.AuthMethod.OFFICIAL_API:
            return session

        if not session.remote_session_ref:
            return session

        try:
            remote = get_authorization_session(remote_session_ref=session.remote_session_ref)
        except PublishingWorkerError as exc:
            if exc.code == "remote_session_missing":
                _mark_failed(session, "authorization_cancelled")
            return session

        remote_status = str(remote.get("status") or "")
        if remote_status == "succeeded":
            credentials = remote.get("credentials")
            if not isinstance(credentials, dict) or not credentials:
                _mark_failed(session, "authorization_cancelled")
                return session
            complete_authorization_session(
                session=session,
                secret_payload=credentials,
                display_name=_safe_remote_label(remote.get("displayName")),
                external_account_id=_safe_remote_label(remote.get("externalAccountId")),
            )
            delete_authorization_session(remote_session_ref=session.remote_session_ref)
            session.refresh_from_db()
            return session
        if remote_status == "expired":
            session.status = PlatformAuthorizationSession.Status.EXPIRED
            session.safe_error_code = "authorization_timeout"
            session.completed_at = timezone.now()
            session.save(update_fields=("status", "safe_error_code", "completed_at", "updated_at"))
            delete_authorization_session(remote_session_ref=session.remote_session_ref)
            return session
        if remote_status == "failed":
            _mark_failed(session, str(remote.get("errorCode") or "platform_unavailable")[:100])
            delete_authorization_session(remote_session_ref=session.remote_session_ref)
            return session

        if session.status != PlatformAuthorizationSession.Status.WAITING_USER:
            session.status = PlatformAuthorizationSession.Status.WAITING_USER
            session.save(update_fields=("status", "updated_at"))
        return session
    finally:
        cache.delete(lock_key)
