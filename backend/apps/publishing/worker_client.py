from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings


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
            timeout=float(getattr(settings, "PUBLISHING_WORKER_PUBLISH_TIMEOUT_SECONDS", 120)),
        )
    except httpx.TimeoutException as exc:
        raise PublishingWorkerError("worker_timeout") from exc
    except httpx.HTTPError as exc:
        raise PublishingWorkerError("worker_unavailable") from exc
    if response.status_code == 409:
        raise PublishingWorkerError("platform_not_ready")
    if response.status_code >= 500:
        raise PublishingWorkerError("worker_unavailable")
    if response.status_code >= 400:
        raise PublishingWorkerError("worker_rejected_request")
    return _decode_response(response)


def check_platform_publication_status(
    *,
    platform_key: str,
    external_post_id: str,
    management_url: str,
    credentials: dict[str, Any],
) -> dict[str, Any]:
    base_url, secret = _configuration()
    payload = {
        "platform_key": platform_key,
        "external_post_id": external_post_id,
        "management_url": management_url,
        "credentials": credentials,
    }
    try:
        response = httpx.post(
            f"{base_url}/v1/status",
            json=payload,
            headers=_headers(secret),
            timeout=float(getattr(settings, "PUBLISHING_WORKER_STATUS_TIMEOUT_SECONDS", 75)),
        )
    except httpx.TimeoutException as exc:
        raise PublishingWorkerError("worker_timeout") from exc
    except httpx.HTTPError as exc:
        raise PublishingWorkerError("worker_unavailable") from exc
    if response.status_code == 409:
        raise PublishingWorkerError("platform_not_ready")
    if response.status_code >= 500:
        raise PublishingWorkerError("worker_unavailable")
    if response.status_code >= 400:
        raise PublishingWorkerError("worker_rejected_request")
    return _decode_response(response)
