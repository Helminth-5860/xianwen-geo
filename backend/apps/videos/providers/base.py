from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class VideoTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class VideoCreateResult:
    task_id: str
    status: VideoTaskStatus
    request_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class VideoResult:
    task_id: str
    status: VideoTaskStatus
    video_url: str | None
    request_id: str | None = field(default=None, repr=False)

    @property
    def ready(self) -> bool:
        return self.status == VideoTaskStatus.SUCCEEDED and self.video_url is not None


class VideoProviderError(Exception):
    """A normalized provider failure that never retains raw upstream data."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        super().__init__("Video provider request failed.")

    def __repr__(self) -> str:
        return (
            f"VideoProviderError(code={self.code!r}, retryable={self.retryable!r}, "
            f"status_code={self.status_code!r})"
        )


@runtime_checkable
class VideoProvider(Protocol):
    def create_video(
        self,
        *,
        prompt: str,
        image_url: str,
        duration_seconds: int,
    ) -> VideoCreateResult: ...

    def get_status(self, task_id: str) -> VideoTaskStatus: ...

    def get_result(self, task_id: str) -> VideoResult: ...
