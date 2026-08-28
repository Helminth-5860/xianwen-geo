from __future__ import annotations

import hashlib
import io
import uuid
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.models import DocumentVersion, FileUploadIntent, UserDocument
from apps.documents.storage import MockStorageProvider, S3CompatibleStorageProvider
from apps.quotas.models import QuotaAccount
from apps.users.models import User
from apps.videos.exceptions import VideoServiceUnavailable
from apps.videos.models import VideoAsset, VideoGenerationJob
from apps.videos.providers import (
    VideoCreateResult,
    VideoProviderError,
    VideoResult,
    VideoTaskStatus,
)
from apps.videos.services import (
    _claim_job,
    _download_video,
    create_video_job,
    ensure_first_frame,
    execute_video_job,
)
from apps.videos.tasks import dispatch_due_video_jobs_task, execute_video_job_task
from tests import test_keyword_generation as keyword_tests

pytestmark = pytest.mark.django_db


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 60), (42, 98, 180)).save(output, format="PNG")
    return output.getvalue()


def _mp4_bytes() -> bytes:
    return b"\x00\x00\x00\x18ftypmp42" + b"safe-video-content" * 10


@pytest.fixture
def video_facts(monkeypatch, settings):
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    original_limits = keyword_tests._limits

    def video_limits(*args, **kwargs):
        values = original_limits(*args, **kwargs)
        values["video_credits"] = 30
        return values

    monkeypatch.setattr(keyword_tests, "_limits", video_limits)
    user, subject, _, subscription = keyword_tests._facts()
    subject.status = subject.Status.ACTIVE
    subject.version += 1
    subject.save(update_fields=("status", "version", "updated_at"))
    data = _png_bytes()
    object_key = f"users/{user.pk}/video-source.png"
    MockStorageProvider.clear()
    MockStorageProvider.put_for_test(object_key, data, "image/png")
    document = UserDocument.objects.create(
        user=user,
        subject=subject,
        purpose=FileUploadIntent.Purpose.SUBJECT_LIBRARY,
        display_name="视频首帧.png",
    )
    version = DocumentVersion.objects.create(
        document=document,
        version_no=1,
        object_key=object_key,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        detected_file_kind="png",
        detected_mime="image/png",
        scanner_engine_version="test-safe-scanner",
    )
    document.current_version = version
    document.version += 1
    document.save(update_fields=("current_version", "version"))
    settings.APP_ENV = "test"
    settings.FILE_STORAGE_PROVIDER = "mock"
    settings.VIDEO_PROVIDER = "aliyun"
    settings.ALIYUN_VIDEO_API_BASE_URL = "https://video.example.com/api/v1"
    settings.ALIYUN_VIDEO_API_KEY = "test-video-key"
    settings.VIDEO_POLL_SECONDS = 1
    settings.VIDEO_MAX_POLLS = 5
    return user, subject, subscription, version


class StubVideoProvider:
    def __init__(self, *, submission_error: VideoProviderError | None = None):
        self.submission_error = submission_error
        self.create_count = 0
        self.status = VideoTaskStatus.SUCCEEDED

    def create_video(self, *, prompt, image_url, duration_seconds):
        self.create_count += 1
        if self.submission_error:
            raise self.submission_error
        assert prompt and image_url.startswith("data:image/jpeg;base64,")
        assert duration_seconds in {5, 10}
        return VideoCreateResult("provider-task-safe", VideoTaskStatus.PENDING, "safe-request")

    def get_status(self, task_id):
        assert task_id == "provider-task-safe"
        return self.status

    def get_result(self, task_id):
        assert task_id == "provider-task-safe"
        return VideoResult(
            task_id,
            self.status,
            "https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/result.mp4"
            if self.status == VideoTaskStatus.SUCCEEDED
            else None,
            "safe-request",
        )


def _create(user, subject, source, *, key="video-idempotent-0001", duration=5):
    return create_video_job(
        user=user,
        subject_id=subject.pk,
        generation_mode="image",
        prompt="让画面自然缓慢推进，保持企业品牌的专业感",
        source_document_version_id=source.pk,
        aspect_ratio="9:16",
        duration_seconds=duration,
        idempotency_key=key,
        request_id=uuid.uuid4(),
    )


def _run_success(job, provider):
    assert execute_video_job(job_id=job.pk)["status"] == "continue"
    assert execute_video_job(job_id=job.pk)["status"] == "waiting"
    VideoGenerationJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
    assert execute_video_job(job_id=job.pk)["status"] == "continue"
    mp4 = _mp4_bytes()
    with patch(
        "apps.videos.services._download_video",
        return_value=(io.BytesIO(mp4), len(mp4), hashlib.sha256(mp4).hexdigest()),
    ):
        assert execute_video_job(job_id=job.pk)["status"] == "succeeded"
    assert provider.create_count == 1


def test_video_job_is_idempotent_and_settles_seconds_once(video_facts):
    user, subject, subscription, source = video_facts
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="video_credits")
    initial = account.available
    provider = StubVideoProvider()
    with patch("apps.videos.services.video_provider", return_value=provider):
        job, created = _create(user, subject, source)
        replay, replay_created = _create(user, subject, source)
        assert created is True and replay_created is False and replay.pk == job.pk
        _run_success(job, provider)
        assert execute_video_job(job_id=job.pk)["status"] == "succeeded"

    job.refresh_from_db()
    account.refresh_from_db()
    asset = VideoAsset.objects.get(generation_job=job)
    assert job.quota_hold.consumed_amount == 5 and job.quota_hold.released_amount == 0
    assert account.available == initial - 5 and account.frozen == 0
    assert asset.aspect_ratio == "9:16" and asset.resolution == "720P"
    assert asset.object_key.startswith(f"users/{user.pk}/subjects/{subject.pk}/videos/")
    assert provider.create_count == 1


def test_settlement_failure_rolls_back_asset_and_releases_hold(video_facts):
    user, subject, subscription, source = video_facts
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="video_credits")
    initial = account.available
    provider = StubVideoProvider()
    with patch("apps.videos.services.video_provider", return_value=provider):
        job, _ = _create(user, subject, source, key="video-settlement-failure-0001")
        assert execute_video_job(job_id=job.pk)["status"] == "continue"
        assert execute_video_job(job_id=job.pk)["status"] == "waiting"
        VideoGenerationJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
        assert execute_video_job(job_id=job.pk)["status"] == "continue"
        mp4 = _mp4_bytes()
        with (
            patch(
                "apps.videos.services._download_video",
                return_value=(io.BytesIO(mp4), len(mp4), hashlib.sha256(mp4).hexdigest()),
            ),
            patch(
                "apps.videos.services.consume_hold", side_effect=RuntimeError("settlement failed")
            ),
        ):
            assert execute_video_job(job_id=job.pk)["status"] == "failed"

    job.refresh_from_db()
    account.refresh_from_db()
    assert job.status == VideoGenerationJob.Status.FAILED
    assert not VideoAsset.objects.filter(generation_job=job).exists()
    assert job.quota_hold.consumed_amount == 0 and job.quota_hold.released_amount == 5
    assert account.available == initial and account.frozen == 0


def test_submission_failure_releases_hold_and_is_not_resent(video_facts):
    user, subject, subscription, source = video_facts
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="video_credits")
    initial = account.available
    provider = StubVideoProvider(
        submission_error=VideoProviderError("network_failure", retryable=True)
    )
    with patch("apps.videos.services.video_provider", return_value=provider):
        job, _ = _create(user, subject, source, key="video-submit-failure-0001")
        assert execute_video_job(job_id=job.pk)["status"] == "continue"
        assert execute_video_job(job_id=job.pk)["status"] == "failed"
        assert execute_video_job(job_id=job.pk)["status"] == "failed"
    job.refresh_from_db()
    account.refresh_from_db()
    assert provider.create_count == 1
    assert job.quota_hold.released_amount == 5 and job.quota_hold.consumed_amount == 0
    assert account.available == initial and account.frozen == 0
    assert job.safe_error_message == "视频任务提交状态无法确认，请重新生成。"


def test_rate_limit_retries_without_settling_or_duplicate_charge(video_facts):
    user, subject, subscription, source = video_facts
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="video_credits")
    initial = account.available
    provider = StubVideoProvider(
        submission_error=VideoProviderError("rate_limited", retryable=True, status_code=429)
    )
    with patch("apps.videos.services.video_provider", return_value=provider):
        job, _ = _create(user, subject, source, key="video-submit-rate-limit-0001")
        assert execute_video_job(job_id=job.pk)["status"] == "continue"
        result = execute_video_job(job_id=job.pk)
    job.refresh_from_db()
    account.refresh_from_db()
    assert result["status"] == "waiting"
    assert provider.create_count == 1
    assert job.stage == VideoGenerationJob.Stage.SUBMIT
    assert job.quota_hold.consumed_amount == 0 and job.quota_hold.released_amount == 0
    assert account.available == initial - 5 and account.frozen == 5


def test_text_first_frame_uses_image_adapter_boundary_without_image_quota(video_facts):
    user, subject, subscription, _source = video_facts
    image_account = QuotaAccount.objects.get(subscription=subscription, quota_type="image_credits")
    before_available = image_account.available
    before_frozen = image_account.frozen
    with patch("apps.videos.services.video_provider", return_value=StubVideoProvider()):
        job, _ = create_video_job(
            user=user,
            subject_id=subject.pk,
            generation_mode="text",
            prompt="品牌服务场景自然推进",
            source_document_version_id=None,
            aspect_ratio="16:9",
            duration_seconds=5,
            idempotency_key="video-text-first-frame-0001",
            request_id=uuid.uuid4(),
        )
    with patch(
        "apps.videos.services.generate_internal_video_first_frame",
        return_value=(_png_bytes(), "doubao", "seedream"),
    ) as generate:
        frame = ensure_first_frame(job.pk)
    image_account.refresh_from_db()
    assert generate.call_count == 1
    assert frame.width == 1280 and frame.height == 720
    assert image_account.available == before_available
    assert image_account.frozen == before_frozen


def test_video_api_is_same_origin_paginated_and_owner_scoped(video_facts):
    user, subject, _subscription, source = video_facts
    provider = StubVideoProvider()
    with patch("apps.videos.services.video_provider", return_value=provider):
        job, _ = _create(user, subject, source, key="video-api-success-0001")
        _run_success(job, provider)
    asset = VideoAsset.objects.get(generation_job=job)

    client = APIClient()
    client.force_authenticate(user=user)
    listing = client.get(f"/api/v1/subjects/{subject.pk}/video-jobs?page=1&page_size=20")
    assert listing.status_code == 200
    payload = listing.json()["data"]
    assert payload["pagination"] == {"page": 1, "page_size": 20, "count": 1, "total_pages": 1}
    assert payload["items"][0]["video"]["url"] == (
        f"/api/v1/subjects/{subject.pk}/videos/{asset.pk}/content"
    )
    assert payload["items"][0]["resolution"] == "720p"

    saved = client.post(
        f"/api/v1/video-jobs/{job.pk}/save-to-library",
        {"expected_version": asset.version},
        format="json",
    )
    assert saved.status_code == 200 and saved.json()["data"]["is_subject_library"] is True
    library = client.get(f"/api/v1/subjects/{subject.pk}/videos?library=true")
    assert library.status_code == 200 and library.json()["data"]["pagination"]["count"] == 1

    other = User.objects.create_user(
        phone=f"138{uuid.uuid4().int % 100000000:08d}",
        nickname="隔离测试用户",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
    )
    denied = APIClient()
    denied.force_authenticate(user=other)
    assert denied.get(f"/api/v1/video-jobs/{job.pk}").status_code == 404
    assert denied.get(f"/api/v1/subjects/{subject.pk}/videos/{asset.pk}/content").status_code == 404


def test_video_api_requires_login_and_rejects_unsupported_options(video_facts):
    user, subject, _subscription, _source = video_facts
    url = f"/api/v1/subjects/{subject.pk}/video-jobs"
    assert APIClient().get(url).status_code in {401, 403}

    client = APIClient()
    client.force_authenticate(user=user)
    base = {
        "generation_mode": "text",
        "prompt": "自然展示企业服务场景",
        "source_document_version_id": None,
        "aspect_ratio": "9:16",
        "duration_seconds": 5,
    }
    invalid_payloads = (
        {**base, "duration_seconds": 6},
        {**base, "aspect_ratio": "1:1"},
        {**base, "generation_mode": "image"},
        {**base, "resolution": "1080P"},
    )
    for index, payload in enumerate(invalid_payloads):
        response = client.post(
            url,
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"video-invalid-{index}-0001",
        )
        assert response.status_code == 422
    assert VideoGenerationJob.objects.count() == 0


def test_video_task_has_bounded_worker_time():
    assert execute_video_job_task.name == "videos.execute_generation"
    assert execute_video_job_task.soft_time_limit == 300
    assert execute_video_job_task.time_limit == 330
    assert dispatch_due_video_jobs_task.name == "videos.dispatch_due_jobs"


def test_video_job_lease_outlives_worker_hard_limit(video_facts):
    user, subject, _subscription, source = video_facts
    with patch("apps.videos.services.video_provider", return_value=StubVideoProvider()):
        job, _ = _create(user, subject, source, key="video-lease-window-0001")
    claimed, state, _retry_after = _claim_job(job.pk)
    assert state == "claimed" and claimed is not None
    assert claimed.lease_expires_at is not None
    assert (claimed.lease_expires_at - timezone.now()).total_seconds() > (
        execute_video_job_task.time_limit
    )


def test_dispatcher_uses_existing_worker_queue(video_facts):
    user, subject, _subscription, source = video_facts
    with patch("apps.videos.services.video_provider", return_value=StubVideoProvider()):
        job, _ = _create(user, subject, source, key="video-dispatch-queue-0001")
    with patch("apps.videos.tasks.execute_video_job_task.apply_async") as enqueue:
        assert dispatch_due_video_jobs_task.run() == 1
    enqueue.assert_called_once_with(args=[str(job.pk)], queue="image_generation")


def test_provider_output_download_is_streamed_without_redirects(settings):
    settings.VIDEO_MAX_BYTES = 1024 * 1024
    settings.VIDEO_DOWNLOAD_TIMEOUT_SECONDS = 10
    body = _mp4_bytes()

    class StreamResponse:
        headers = {"content-length": str(len(body))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self, *, chunk_size):
            assert chunk_size == 1024 * 1024
            yield body[:20]
            yield body[20:]

    class StreamClient:
        def __init__(self, *, follow_redirects, trust_env, timeout):
            assert follow_redirects is False
            assert trust_env is False
            assert timeout is not None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, method, url, *, headers):
            assert method == "GET"
            assert url == ("https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/result.mp4")
            assert headers == {"Accept": "video/mp4"}
            return StreamResponse()

    with (
        patch("apps.videos.services.resolve_and_validate", return_value=("203.0.113.10",)),
        patch("apps.videos.services.httpx.Client", StreamClient),
    ):
        stream, size, digest = _download_video(
            "https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/result.mp4"
        )
    try:
        assert stream.read() == body
        assert size == len(body)
        assert digest == hashlib.sha256(body).hexdigest()
    finally:
        stream.close()

    with pytest.raises(VideoServiceUnavailable):
        _download_video("http://169.254.169.254/result.mp4")

    with pytest.raises(VideoServiceUnavailable):
        _download_video("https://attacker.example.com/result.mp4")


def test_system_stream_head_errors_fail_closed():
    class HeadFailure(Exception):
        response = {
            "Error": {"Code": "AccessDenied"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        }

    class Client:
        def head_object(self, **_kwargs):
            raise HeadFailure

        def upload_fileobj(self, *_args, **_kwargs):
            raise AssertionError("上传不应在存储状态未知时发生")

    provider = object.__new__(S3CompatibleStorageProvider)
    provider.bucket = "private-video-bucket"
    provider.client = Client()
    with pytest.raises(FileStorageUnavailable):
        provider.put_system_stream(
            key="users/1/subjects/1/videos/result.mp4",
            stream=io.BytesIO(_mp4_bytes()),
            content_type="video/mp4",
            size=len(_mp4_bytes()),
            sha256=hashlib.sha256(_mp4_bytes()).hexdigest(),
        )
