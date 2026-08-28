from __future__ import annotations

import json
import re
import uuid
from typing import Any

import httpx

from .base import VideoCreateResult, VideoProviderError, VideoResult, VideoTaskStatus

ALIYUN_WAN_MODEL = "wan2.6-i2v-flash"
ALIYUN_WAN_RESOLUTION = "720P"
ALIYUN_WAN_DURATIONS = frozenset({5, 10})
ALIYUN_WAN_PROMPT_MAX_LENGTH = 1500

_CREATE_PATH = "/services/aigc/video-generation/video-synthesis"
_MAX_RESPONSE_BYTES = 1_000_000
_TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
_DASHSCOPE_API_HOSTS = frozenset(
    {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    }
)
_FIRST_FRAME_DATA_PREFIX = "data:image/jpeg;base64,"
_MAX_FIRST_FRAME_DATA_URI_LENGTH = len(_FIRST_FRAME_DATA_PREFIX) + ((20 * 1024 * 1024 + 2) // 3) * 4
_STATUS_MAP = {
    "PENDING": VideoTaskStatus.PENDING,
    "RUNNING": VideoTaskStatus.RUNNING,
    "SUCCEEDED": VideoTaskStatus.SUCCEEDED,
    "FAILED": VideoTaskStatus.FAILED,
    "CANCELED": VideoTaskStatus.CANCELED,
    "UNKNOWN": VideoTaskStatus.UNKNOWN,
}


def _safe_request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError):
        return None
    canonical = str(parsed)
    return value if value.lower() == canonical else None


def _is_supported_image_input(value: str) -> bool:
    if value.startswith(_FIRST_FRAME_DATA_PREFIX):
        payload = value[len(_FIRST_FRAME_DATA_PREFIX) :]
        return (
            bool(payload)
            and len(value) <= _MAX_FIRST_FRAME_DATA_URI_LENGTH
            and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", payload) is not None
        )
    try:
        parsed = httpx.URL(value)
    except (TypeError, ValueError):
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.host) and parsed.userinfo == b""


def _map_status(value: object) -> VideoTaskStatus:
    if not isinstance(value, str):
        return VideoTaskStatus.UNKNOWN
    return _STATUS_MAP.get(value.strip().upper(), VideoTaskStatus.UNKNOWN)


def _http_error(status_code: int) -> VideoProviderError:
    if status_code == 429:
        return VideoProviderError(
            "rate_limited",
            retryable=True,
            status_code=status_code,
        )
    if 500 <= status_code <= 599:
        return VideoProviderError(
            "temporary_provider_failure",
            retryable=True,
            status_code=status_code,
        )
    if status_code == 408:
        return VideoProviderError("timeout", retryable=True, status_code=status_code)
    if status_code == 400:
        code = "invalid_request"
    elif status_code == 401:
        code = "authentication_failed"
    elif status_code == 403:
        code = "permission_denied"
    else:
        code = "request_rejected"
    return VideoProviderError(code, retryable=False, status_code=status_code)


def _is_aliyun_api_host(host: str) -> bool:
    return host in _DASHSCOPE_API_HOSTS or (
        host.endswith(".maas.aliyuncs.com") and host != "maas.aliyuncs.com"
    )


class AliyunWanVideoProvider:
    model = ALIYUN_WAN_MODEL
    resolution = ALIYUN_WAN_RESOLUTION

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        try:
            parsed_url = httpx.URL(base_url)
        except (TypeError, ValueError):
            parsed_url = httpx.URL("")
        if (
            parsed_url.scheme != "https"
            or not parsed_url.host
            or not _is_aliyun_api_host(parsed_url.host)
            or parsed_url.userinfo
            or parsed_url.query
            or parsed_url.fragment
            or parsed_url.path.rstrip("/") != "/api/v1"
        ):
            raise ValueError("A valid HTTPS Aliyun base URL is required.")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("An Aliyun API key is required.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = float(timeout_seconds)
        self._transport = transport

    def __repr__(self) -> str:
        return f"AliyunWanVideoProvider(model={self.model!r})"

    def create_video(
        self,
        *,
        prompt: str,
        image_url: str,
        duration_seconds: int,
    ) -> VideoCreateResult:
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt) > ALIYUN_WAN_PROMPT_MAX_LENGTH
        ):
            raise ValueError("prompt must contain between 1 and 1500 characters.")
        if not isinstance(image_url, str) or not _is_supported_image_input(image_url):
            raise ValueError("image_url must be a supported image input.")
        if duration_seconds not in ALIYUN_WAN_DURATIONS:
            raise ValueError("duration_seconds must be 5 or 10.")

        payload = self._request(
            "POST",
            _CREATE_PATH,
            json_body={
                "model": self.model,
                "input": {
                    "prompt": prompt,
                    "img_url": image_url,
                },
                "parameters": {
                    "resolution": self.resolution,
                    "duration": duration_seconds,
                    "audio": False,
                    "prompt_extend": True,
                    "shot_type": "single",
                    "watermark": False,
                },
            },
            asynchronous=True,
        )
        output = self._output(payload)
        task_id = output.get("task_id")
        if not isinstance(task_id, str) or _TASK_ID_PATTERN.fullmatch(task_id) is None:
            raise VideoProviderError("invalid_response", retryable=False)
        return VideoCreateResult(
            task_id=task_id,
            status=_map_status(output.get("task_status")),
            request_id=_safe_request_id(payload.get("request_id")),
        )

    def get_status(self, task_id: str) -> VideoTaskStatus:
        payload = self._query_task(task_id)
        return _map_status(self._task_output(payload, task_id).get("task_status"))

    def get_result(self, task_id: str) -> VideoResult:
        payload = self._query_task(task_id)
        output = self._task_output(payload, task_id)

        status = _map_status(output.get("task_status"))
        video_url: str | None = None
        if status == VideoTaskStatus.SUCCEEDED:
            raw_video_url = output.get("video_url")
            if not isinstance(raw_video_url, str) or not raw_video_url.startswith("https://"):
                raise VideoProviderError("invalid_response", retryable=False)
            video_url = raw_video_url

        return VideoResult(
            task_id=task_id,
            status=status,
            video_url=video_url,
            request_id=_safe_request_id(payload.get("request_id")),
        )

    def _query_task(self, task_id: str) -> dict[str, Any]:
        if not isinstance(task_id, str) or _TASK_ID_PATTERN.fullmatch(task_id) is None:
            raise ValueError("task_id is invalid.")
        return self._request("GET", f"/tasks/{task_id}")

    @staticmethod
    def _output(payload: dict[str, Any]) -> dict[str, Any]:
        output = payload.get("output")
        if not isinstance(output, dict):
            raise VideoProviderError("invalid_response", retryable=False)
        return output

    @classmethod
    def _task_output(cls, payload: dict[str, Any], task_id: str) -> dict[str, Any]:
        output = cls._output(payload)
        if output.get("task_id") != task_id:
            raise VideoProviderError("invalid_response", retryable=False)
        return output

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        asynchronous: bool = False,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if asynchronous:
            headers["X-DashScope-Async"] = "enable"

        client = httpx.Client(
            follow_redirects=False,
            trust_env=False,
            timeout=self._timeout_seconds,
            transport=self._transport,
        )
        try:
            try:
                response = client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    json=json_body,
                )
            except httpx.TimeoutException:
                raise VideoProviderError("timeout", retryable=True) from None
            except httpx.NetworkError:
                raise VideoProviderError("network_failure", retryable=True) from None
            except httpx.HTTPError:
                raise VideoProviderError("network_failure", retryable=True) from None

            if response.status_code >= 400:
                raise _http_error(response.status_code)
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise VideoProviderError("invalid_response", retryable=False)
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError):
                raise VideoProviderError("invalid_response", retryable=False) from None
            if not isinstance(payload, dict):
                raise VideoProviderError("invalid_response", retryable=False)
            return payload
        finally:
            client.close()
