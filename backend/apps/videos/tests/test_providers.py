from __future__ import annotations

import json

import httpx
import pytest

from apps.videos.providers import (
    ALIYUN_WAN_MODEL,
    ALIYUN_WAN_PROMPT_MAX_LENGTH,
    AliyunWanVideoProvider,
    VideoProvider,
    VideoProviderError,
    VideoTaskStatus,
)

BASE_URL = "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"
API_KEY = "sk-test-provider-secret"
TASK_ID = "0385dc79-5ff8-4d82-bcb6-000000000001"
REQUEST_ID = "4909100c-7b5a-4f92-bfe5-000000000001"
RESULT_REQUEST_ID = "2ca1c497-f9e0-449d-9a3f-000000000001"


def provider_with_handler(handler) -> AliyunWanVideoProvider:
    return AliyunWanVideoProvider(
        base_url=BASE_URL,
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    )


def test_create_video_uses_fixed_safe_wan_contract() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["async"] = request.headers["X-DashScope-Async"]
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "request_id": REQUEST_ID,
                "output": {"task_id": TASK_ID, "task_status": "PENDING"},
            },
        )

    provider = provider_with_handler(handler)
    result = provider.create_video(
        prompt="一只猫在草地上奔跑",
        image_url="https://example.com/first-frame.png",
        duration_seconds=5,
    )

    assert isinstance(provider, VideoProvider)
    assert captured == {
        "method": "POST",
        "url": f"{BASE_URL}/services/aigc/video-generation/video-synthesis",
        "authorization": f"Bearer {API_KEY}",
        "async": "enable",
        "json": {
            "model": ALIYUN_WAN_MODEL,
            "input": {
                "prompt": "一只猫在草地上奔跑",
                "img_url": "https://example.com/first-frame.png",
            },
            "parameters": {
                "resolution": "720P",
                "duration": 5,
                "audio": False,
                "prompt_extend": True,
                "shot_type": "single",
                "watermark": False,
            },
        },
    }
    assert result.task_id == TASK_ID
    assert result.status == VideoTaskStatus.PENDING
    assert result.request_id == REQUEST_ID
    assert API_KEY not in repr(provider)
    assert API_KEY not in repr(result)
    assert REQUEST_ID not in repr(result)


def test_create_video_accepts_private_first_frame_as_jpeg_data_uri() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"output": {"task_id": TASK_ID, "task_status": "PENDING"}},
        )

    image_input = "data:image/jpeg;base64,/9j/2Q=="
    provider_with_handler(handler).create_video(
        prompt="画面轻微移动",
        image_url=image_input,
        duration_seconds=5,
    )

    assert captured["input"]["img_url"] == image_input


@pytest.mark.parametrize("prompt", ["", "   ", "x" * (ALIYUN_WAN_PROMPT_MAX_LENGTH + 1)])
def test_create_video_rejects_invalid_prompt_without_network(prompt: str) -> None:
    provider = provider_with_handler(
        lambda request: pytest.fail(f"network must not run: {request.url}")
    )

    with pytest.raises(ValueError, match="1 and 1500"):
        provider.create_video(
            prompt=prompt,
            image_url="https://example.com/frame.png",
            duration_seconds=5,
        )


@pytest.mark.parametrize("duration", [0, 4, 6, 15])
def test_create_video_rejects_unsupported_duration_without_network(duration: int) -> None:
    provider = provider_with_handler(
        lambda request: pytest.fail(f"network must not run: {request.url}")
    )

    with pytest.raises(ValueError, match="5 or 10"):
        provider.create_video(
            prompt="prompt",
            image_url="https://example.com/frame.png",
            duration_seconds=duration,
        )


@pytest.mark.parametrize(
    "image_url",
    [
        "",
        "file:///tmp/frame.png",
        "data:image/png;base64,AAAA",
        "https://user:password@example.com/frame.png",
        "not-a-url",
    ],
)
def test_create_video_rejects_unsupported_image_input_without_network(image_url: str) -> None:
    provider = provider_with_handler(
        lambda request: pytest.fail(f"network must not run: {request.url}")
    )

    with pytest.raises(ValueError, match="supported image input"):
        provider.create_video(
            prompt="prompt",
            image_url=image_url,
            duration_seconds=5,
        )


@pytest.mark.parametrize(
    ("upstream", "normalized"),
    [
        ("PENDING", VideoTaskStatus.PENDING),
        ("RUNNING", VideoTaskStatus.RUNNING),
        ("SUCCEEDED", VideoTaskStatus.SUCCEEDED),
        ("FAILED", VideoTaskStatus.FAILED),
        ("CANCELED", VideoTaskStatus.CANCELED),
        ("UNKNOWN", VideoTaskStatus.UNKNOWN),
        ("unexpected-provider-status", VideoTaskStatus.UNKNOWN),
        (None, VideoTaskStatus.UNKNOWN),
    ],
)
def test_get_status_safely_normalizes_provider_status(
    upstream: object, normalized: VideoTaskStatus
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == f"{BASE_URL}/tasks/{TASK_ID}"
        return httpx.Response(
            200,
            json={"output": {"task_id": TASK_ID, "task_status": upstream}},
        )

    assert provider_with_handler(handler).get_status(TASK_ID) == normalized


def test_get_result_returns_https_video_only_for_succeeded_task() -> None:
    video_url = "https://dashscope-result.example.com/video.mp4?Expires=123"

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "request_id": RESULT_REQUEST_ID,
                "output": {
                    "task_id": TASK_ID,
                    "task_status": "SUCCEEDED",
                    "video_url": video_url,
                },
            },
        )

    result = provider_with_handler(handler).get_result(TASK_ID)

    assert result.ready is True
    assert result.status == VideoTaskStatus.SUCCEEDED
    assert result.video_url == video_url
    assert result.request_id == RESULT_REQUEST_ID


def test_non_uuid_request_id_is_not_exposed_to_business_layer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "request_id": f"unsafe-request-id-containing-{API_KEY}",
                "output": {"task_id": TASK_ID, "task_status": "PENDING"},
            },
        )

    created = provider_with_handler(handler).create_video(
        prompt="prompt",
        image_url="https://example.com/frame.png",
        duration_seconds=5,
    )

    assert created.request_id is None
    assert API_KEY not in repr(created)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://attacker.example.com/api/v1",
        "https://maas.aliyuncs.com/api/v1",
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v2",
    ],
)
def test_provider_rejects_non_aliyun_api_endpoint_before_using_key(base_url: str) -> None:
    with pytest.raises(ValueError, match="Aliyun base URL"):
        AliyunWanVideoProvider(base_url=base_url, api_key=API_KEY)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://dashscope.aliyuncs.com/api/v1",
        "https://dashscope-intl.aliyuncs.com/api/v1",
        "https://dashscope-us.aliyuncs.com/api/v1",
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    ],
)
def test_provider_accepts_documented_aliyun_native_api_endpoints(base_url: str) -> None:
    provider = AliyunWanVideoProvider(base_url=base_url, api_key=API_KEY)
    assert API_KEY not in repr(provider)


def test_get_result_preserves_terminal_failure_without_exposing_provider_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "output": {
                    "task_id": TASK_ID,
                    "task_status": "FAILED",
                    "code": "InternalError",
                    "message": f"raw failure containing {API_KEY}",
                }
            },
        )

    result = provider_with_handler(handler).get_result(TASK_ID)

    assert result.status == VideoTaskStatus.FAILED
    assert result.video_url is None
    assert result.ready is False
    assert API_KEY not in repr(result)


@pytest.mark.parametrize(
    ("status_code", "code", "retryable"),
    [
        (400, "invalid_request", False),
        (401, "authentication_failed", False),
        (403, "permission_denied", False),
        (429, "rate_limited", True),
        (500, "temporary_provider_failure", True),
        (502, "temporary_provider_failure", True),
        (503, "temporary_provider_failure", True),
    ],
)
def test_http_errors_have_safe_retry_classification(
    status_code: int, code: str, retryable: bool
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            status_code,
            json={"code": "unsafe-upstream-code", "message": f"contains {API_KEY}"},
        )

    with pytest.raises(VideoProviderError) as failure:
        provider_with_handler(handler).get_status(TASK_ID)

    assert failure.value.code == code
    assert failure.value.retryable is retryable
    assert failure.value.status_code == status_code
    assert API_KEY not in str(failure.value)
    assert API_KEY not in repr(failure.value)


def test_timeout_and_network_failures_are_retryable_without_secret_leak() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout with {API_KEY}", request=request)

    with pytest.raises(VideoProviderError) as timeout:
        provider_with_handler(timeout_handler).get_status(TASK_ID)
    assert timeout.value.code == "timeout"
    assert timeout.value.retryable is True
    assert timeout.value.__cause__ is None
    assert API_KEY not in repr(timeout.value)

    def network_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"network with {API_KEY}", request=request)

    with pytest.raises(VideoProviderError) as network:
        provider_with_handler(network_handler).get_status(TASK_ID)
    assert network.value.code == "network_failure"
    assert network.value.retryable is True
    assert network.value.__cause__ is None
    assert API_KEY not in repr(network.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"output": {"task_status": "SUCCEEDED"}}),
        httpx.Response(
            200,
            json={
                "output": {
                    "task_id": "different-task-id",
                    "task_status": "SUCCEEDED",
                    "video_url": "https://example.com/video.mp4",
                }
            },
        ),
        httpx.Response(
            200,
            json={
                "output": {
                    "task_id": TASK_ID,
                    "task_status": "SUCCEEDED",
                    "video_url": "http://insecure.example.com/video.mp4",
                }
            },
        ),
    ],
)
def test_malformed_result_responses_fail_closed(response: httpx.Response) -> None:
    with pytest.raises(VideoProviderError) as failure:
        provider_with_handler(lambda request: response).get_result(TASK_ID)

    assert failure.value.code == "invalid_response"
    assert failure.value.retryable is False
