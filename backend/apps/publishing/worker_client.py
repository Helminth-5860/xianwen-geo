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
    data = response.json()
    if not isinstance(data, dict):
        raise PublishingWorkerError("worker_invalid_response")
    return data


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
    data = response.json()
    if not isinstance(data, dict):
        raise PublishingWorkerError("worker_invalid_response")
    return data


def delete_authorization_session(*, remote_session_ref: str) -> None:
    if not remote_session_ref:
        return
    base_url, secret = _configuration()
    try:
        response = httpx.delete(
            f"{base_url}/v1/auth-sessions/{remote_session_ref}",
            headers=_headers(secret),
            timeout=10.0,
        )
    except httpx.HTTPError:
        return
    if response.status_code not in {204, 404}:
        return
