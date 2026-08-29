from __future__ import annotations

import os
from typing import Any

import httpx
from django.conf import settings

from .platform_health import platform_circuit_open, record_platform_failure, record_platform_success


class PublishingWorkerError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _configuration() -> tuple[str, str]:
    base_url = getattr(settings, "PUBLISHING_WORKER_BASE_URL", "").strip().rstrip("/")
    secret = getattr(settings, "PUBLISHING_WORKER_INTERNAL_SECRET", "").strip()
    if not base_url or len(secret) < 32:
        raise PublishingWorkerError("worker_not_configured")
    return base_url, secret


def _positive_timeout(name: str, default: int, maximum: int) -> float:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return float(max(5, min(maximum, value)))


def _headers(secret: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {secret}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _decode_response(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise PublishingWorkerError("worker_invalid_response") from exc
    if not isinstance(data, dict):
        raise PublishingWorkerError("worker_invalid_response")
    return data


def _record_result_health(platform_key: str, data: dict[str, Any]) -> None:
    status = str(data.get("status") or "")
    safe_code = str(data.get("safeErrorCode") or "")
    if bool(data.get("success")) or status in {"submitted", "published", "drafted"}:
        record_platform_success(platform_key)
        return
    if safe_code in {
        "platform_unavailable",
        "editor_changed",
        "publish_control_changed",
        "publish_result_unconfirmed",
    }:
        record_platform_failure(platform_key, safe_code)


def _uncertain_publish_result(platform_key: str) -> dict[str, Any]:
    # 发布 POST 可能已经抵达平台。结果不确定时不能盲目重放，否则可能生成重复文章。
    record_platform_failure(platform_key, "publish_result_unconfirmed")
    return {
        "success": False,
        "platformKey": platform_key,
        "status": "action_required",
        "safeErrorCode": "publish_result_unconfirmed",
    }


def start_authorization_session(*, session_id: str, platform_key: str, expires_at) -> dict[str, Any]:
    base_url, secret = _configuration()
    try:
        response = httpx.post(
            f"{base_url}/v1/auth-sessions",
            json={
                "id": session_id,
                "platform_key": platform_key,
                "expires_at": expires_at.isoformat(),
            },
            headers=_headers(secret),
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        raise PublishingWorkerError("worker_unavailable") from exc
    if response.status_code == 409:
        raise PublishingWorkerError("platform_not_ready")
    if response.status_code >= 400:
        raise PublishingWorkerError("worker_unavailable")
    return _decode_response(response)


def get_authorization_session(*, remote_session_ref: str) -> dict[str, Any]:
    base_url, secret = _configuration()
    try:
        response = httpx.get(
            f"{base_url}/v1/auth-sessions/{remote_session_ref}",
            headers=_headers(secret),
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise PublishingWorkerError("worker_unavailable") from exc
    if response.status_code == 404:
        raise PublishingWorkerError("remote_session_missing")
    if response.status_code >= 400:
        raise PublishingWorkerError("worker_unavailable")
    return _decode_response(response)


def delete_authorization_session(*, remote_session_ref: str) -> None:
    if not remote_session_ref:
        return
    try:
        base_url, secret = _configuration()
        response = httpx.delete(
            f"{base_url}/v1/auth-sessions/{remote_session_ref}",
            headers=_headers(secret),
            timeout=10.0,
        )
    except (httpx.HTTPError, PublishingWorkerError):
        return
    if response.status_code not in {204, 404}:
        return


def publishing_capabilities() -> dict[str, Any]:
    base_url, secret = _configuration()
    try:
        response = httpx.get(
            f"{base_url}/v1/capabilities",
            headers=_headers(secret),
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise PublishingWorkerError("worker_unavailable") from exc
    if response.status_code >= 400:
        raise PublishingWorkerError("worker_unavailable")
    return _decode_response(response)


def publish_to_platform(
    *,
    platform_key: str,
    target_id: str,
    title: str,
    content_html: str,
    content_text: str,
    summary: str,
    tags: list[str],
    assets: list[dict[str, Any]],
    credentials: dict[str, Any],
    publish_mode: str = "public",
) -> dict[str, Any]:
    if platform_circuit_open(platform_key):
        raise PublishingWorkerError("platform_circuit_open")
    base_url, secret = _configuration()
    payload = {
        "platform_key": platform_key,
        "target_id": target_id,
        "title": title,
        "content_html": content_html,
        "content_text": content_text,
        "summary": summary,
        "tags": tags,
        "assets": assets,
        "credentials": credentials,
        "publish_mode": publish_mode,
    }
    try:
        response = httpx.post(
            f"{base_url}/v1/publish",
            json=payload,
            headers=_headers(secret),
            timeout=_positive_timeout("PUBLISHING_WORKER_PUBLISH_TIMEOUT_SECONDS", 120, 300),
        )
    except httpx.ConnectError as exc:
        # 连接建立失败时请求没有送达 Worker，可以由上层安全重试。
        record_platform_failure(platform_key, "worker_unavailable")
        raise PublishingWorkerError("worker_unavailable") from exc
    except httpx.TimeoutException:
        return _uncertain_publish_result(platform_key)
    except httpx.HTTPError:
        return _uncertain_publish_result(platform_key)
    if response.status_code == 409:
        raise PublishingWorkerError("platform_not_ready")
    if response.status_code >= 500:
        return _uncertain_publish_result(platform_key)
    if response.status_code >= 400:
        raise PublishingWorkerError("worker_rejected_request")
    data = _decode_response(response)
    _record_result_health(platform_key, data)
    return data


def check_platform_publication_status(
    *,
    platform_key: str,
    external_post_id: str,
    management_url: str,
    expected_title: str,
    credentials: dict[str, Any],
) -> dict[str, Any]:
    base_url, secret = _configuration()
    payload = {
        "platform_key": platform_key,
        "external_post_id": external_post_id,
        "management_url": management_url,
        "expected_title": expected_title,
        "credentials": credentials,
    }
    try:
        response = httpx.post(
            f"{base_url}/v1/status",
            json=payload,
            headers=_headers(secret),
            timeout=_positive_timeout("PUBLISHING_WORKER_STATUS_TIMEOUT_SECONDS", 75, 180),
        )
    except httpx.TimeoutException as exc:
        record_platform_failure(platform_key, "status_timeout")
        raise PublishingWorkerError("worker_timeout") from exc
    except httpx.HTTPError as exc:
        record_platform_failure(platform_key, "status_unavailable")
        raise PublishingWorkerError("worker_unavailable") from exc
    if response.status_code == 409:
        raise PublishingWorkerError("platform_not_ready")
    if response.status_code >= 500:
        record_platform_failure(platform_key, "status_unavailable")
        raise PublishingWorkerError("worker_unavailable")
    if response.status_code >= 400:
        raise PublishingWorkerError("worker_rejected_request")
    data = _decode_response(response)
    if str(data.get("status") or "") == "published":
        record_platform_success(platform_key)
    return data
