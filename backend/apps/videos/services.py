from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, BinaryIO, cast

import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.ai.errors import AIAdapterError
from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.models import DocumentVersion
from apps.documents.storage import storage_provider
from apps.images.exceptions import ImageBusinessError
from apps.images.models import ImageAsset, ImageGenerationJob
from apps.images.services import generate_internal_video_first_frame
from apps.plans.subscription_services import current_subscription
from apps.quotas.models import QuotaAccount
from apps.quotas.services import consume_hold, freeze_quota, release_hold
from apps.subjects.models import Subject
from apps.web_sources.exceptions import WebSourceError
from apps.web_sources.url_security import canonicalize_url, resolve_and_validate

from .exceptions import (
    VideoBusinessError,
    VideoInputInvalid,
    VideoServiceUnavailable,
    VideoVersionConflict,
)
from .models import VideoAsset, VideoGenerationJob
from .providers import (
    AliyunWanVideoProvider,
    VideoProviderError,
    VideoTaskStatus,
)

VIDEO_ASSET_NAMESPACE = uuid.UUID("dc6c7c75-63ee-42d2-bcf9-07ca8fca3a9e")
FIRST_FRAME_NAMESPACE = uuid.UUID("af734776-bdb5-4b8e-8074-d13f388ebc14")
FIRST_FRAME_DIMENSIONS = {"9:16": (720, 1280), "16:9": (1280, 720)}
SOURCE_IMAGE_MAX_BYTES = 20 * 1024 * 1024
SOURCE_IMAGE_MIMES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
ALIYUN_VIDEO_RESULT_HOST = re.compile(
    r"^dashscope-result-[a-z0-9-]+\.oss-[a-z0-9-]+\.aliyuncs\.com$"
)
SAFE_FAILURE_MESSAGES = {
    "VIDEO_PROVIDER_CONFIG_UNAVAILABLE": "视频生成服务暂未启用。",
    "VIDEO_FIRST_FRAME_FAILED": "首帧图片准备失败，请稍后重试。",
    "VIDEO_SUBMISSION_UNCERTAIN": "视频任务提交状态无法确认，请重新生成。",
    "VIDEO_PROVIDER_TEMPORARY_FAILURE": "视频任务提交失败，请稍后重试。",
    "VIDEO_PROVIDER_RATE_LIMIT": "当前使用人数较多，请稍后再生成。",
    "VIDEO_PROVIDER_TIMEOUT": "视频生成等待超时，请重新生成。",
    "VIDEO_PROVIDER_AUTHENTICATION_FAILED": "视频生成服务暂时不可用，请联系管理员。",
    "VIDEO_CONTENT_REJECTED": "本次内容未通过安全检查，请调整后重试。",
    "VIDEO_DOWNLOAD_FAILED": "视频保存失败，请稍后重试。",
    "VIDEO_STORAGE_FAILED": "视频存储暂时不可用，请稍后重试。",
    "VIDEO_QUEUE_UNAVAILABLE": "当前生成服务较忙，请稍后重新生成。",
    "VIDEO_INTERNAL_FAILURE": "视频生成暂时不可用，请稍后重试。",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredVideo:
    id: uuid.UUID
    object_key: str
    size_bytes: int
    sha256: str


def _digest_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _idempotency_digest(*, user_id, subject_id, raw_key: str) -> str:
    key = raw_key.strip()
    if not key or len(key) > 200 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise VideoInputInvalid(
            "VIDEO_IDEMPOTENCY_KEY_REQUIRED",
            "请求已失效，请刷新页面后重试。",
        )
    derived = hmac.new(
        settings.VIDEO_IDEMPOTENCY_HMAC_KEY.encode(),
        f"video:create:{subject_id}:v1".encode(),
        hashlib.sha256,
    ).digest()
    return hmac.new(derived, f"{user_id}:{key}".encode(), hashlib.sha256).hexdigest()


def _subject(user, subject_id, *, lock: bool = False) -> Subject:
    query = Subject.objects.filter(user=user, user__tenant_id=user.tenant_id)
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        subject = query.get(pk=subject_id)
    except Subject.DoesNotExist as exc:
        raise Http404 from exc
    if subject.status != Subject.Status.ACTIVE:
        raise VideoInputInvalid("VIDEO_SUBJECT_NOT_READY", "当前主体暂不可用于视频生成。")
    return subject


def _source_document(user, subject, version_id) -> DocumentVersion | None:
    if version_id is None:
        return None
    try:
        return DocumentVersion.objects.select_related("document").get(
            pk=version_id,
            document__user=user,
            document__user__tenant_id=user.tenant_id,
            document__subject=subject,
            detected_file_kind__in=("jpeg", "png", "webp"),
        )
    except DocumentVersion.DoesNotExist as exc:
        raise Http404 from exc


def _video_account(subscription) -> QuotaAccount:
    try:
        return QuotaAccount.objects.get(
            subscription=subscription,
            quota_type="video_credits",
            batch_type=QuotaAccount.BatchType.PRIMARY,
            cycle_started_at__isnull=True,
            subject__isnull=True,
        )
    except QuotaAccount.DoesNotExist as exc:
        raise VideoBusinessError(
            "VIDEO_QUOTA_ACCOUNT_UNAVAILABLE",
            "当前套餐尚未开通视频生成额度。",
            status=409,
        ) from exc


def video_provider():
    if settings.VIDEO_PROVIDER != "aliyun":
        raise VideoServiceUnavailable(
            "VIDEO_PROVIDER_CONFIG_UNAVAILABLE",
            SAFE_FAILURE_MESSAGES["VIDEO_PROVIDER_CONFIG_UNAVAILABLE"],
        )
    if not settings.ALIYUN_VIDEO_API_BASE_URL or not settings.ALIYUN_VIDEO_API_KEY:
        raise VideoServiceUnavailable(
            "VIDEO_PROVIDER_CONFIG_UNAVAILABLE",
            SAFE_FAILURE_MESSAGES["VIDEO_PROVIDER_CONFIG_UNAVAILABLE"],
        )
    try:
        return AliyunWanVideoProvider(
            base_url=settings.ALIYUN_VIDEO_API_BASE_URL,
            api_key=settings.ALIYUN_VIDEO_API_KEY,
            timeout_seconds=settings.VIDEO_PROVIDER_TIMEOUT_SECONDS,
        )
    except ValueError as exc:
        raise VideoServiceUnavailable(
            "VIDEO_PROVIDER_CONFIG_UNAVAILABLE",
            SAFE_FAILURE_MESSAGES["VIDEO_PROVIDER_CONFIG_UNAVAILABLE"],
        ) from exc


@transaction.atomic
def create_video_job(
    *,
    user,
    subject_id,
    generation_mode,
    prompt,
    source_document_version_id,
    aspect_ratio,
    duration_seconds,
    idempotency_key,
    request_id,
) -> tuple[VideoGenerationJob, bool]:
    subject = _subject(user, subject_id, lock=True)
    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise VideoInputInvalid("VIDEO_PROMPT_REQUIRED", "请输入视频内容描述。")
    if len(clean_prompt) > settings.VIDEO_PROMPT_MAX_LENGTH:
        raise VideoInputInvalid("VIDEO_PROMPT_TOO_LONG", "视频内容描述最多可填写 1500 个字。")
    if generation_mode not in VideoGenerationJob.GenerationMode.values:
        raise VideoInputInvalid()
    if aspect_ratio not in settings.VIDEO_ALLOWED_ASPECT_RATIOS:
        raise VideoInputInvalid("VIDEO_ASPECT_RATIO_INVALID", "请选择有效的画面比例。")
    if duration_seconds not in settings.VIDEO_ALLOWED_DURATIONS:
        raise VideoInputInvalid("VIDEO_DURATION_INVALID", "请选择有效的视频时长。")
    if generation_mode == VideoGenerationJob.GenerationMode.TEXT and source_document_version_id:
        raise VideoInputInvalid("VIDEO_SOURCE_IMAGE_INVALID", "文字生成视频时不需要选择图片。")
    if (
        generation_mode == VideoGenerationJob.GenerationMode.IMAGE
        and not source_document_version_id
    ):
        raise VideoInputInvalid("VIDEO_SOURCE_IMAGE_REQUIRED", "请选择一张图片。")
    source_document = _source_document(user, subject, source_document_version_id)
    if source_document and source_document.size_bytes > getattr(
        settings, "VIDEO_SOURCE_IMAGE_MAX_BYTES", SOURCE_IMAGE_MAX_BYTES
    ):
        raise VideoInputInvalid("VIDEO_SOURCE_IMAGE_TOO_LARGE", "参考图片不能超过 20 MB。")
    video_provider()
    if settings.FILE_STORAGE_PROVIDER == "unavailable":
        raise VideoServiceUnavailable(
            "VIDEO_STORAGE_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_STORAGE_FAILED"]
        )

    idem = _idempotency_digest(
        user_id=user.pk,
        subject_id=subject.pk,
        raw_key=idempotency_key,
    )
    request_snapshot = {
        "subject_id": str(subject.pk),
        "generation_mode": generation_mode,
        "prompt_digest": hashlib.sha256(clean_prompt.encode()).hexdigest(),
        "source_document_version_id": str(source_document.pk) if source_document else None,
        "source_sha256": source_document.sha256 if source_document else None,
        "aspect_ratio": aspect_ratio,
        "duration_seconds": duration_seconds,
        "resolution": settings.VIDEO_RESOLUTION,
        "provider_model": settings.VIDEO_MODEL,
    }
    request_digest = _digest_json(request_snapshot)
    existing = VideoGenerationJob.objects.filter(idempotency_key_digest=idem).first()
    if existing is not None:
        if existing.user_id != user.pk or existing.request_digest != request_digest:
            raise VideoBusinessError(
                "VIDEO_IDEMPOTENCY_CONFLICT",
                "请求内容已发生变化，请刷新页面后重试。",
            )
        return existing, False

    subscription = current_subscription(user)
    if subscription is None:
        raise VideoBusinessError("VIDEO_PLAN_REQUIRED", "当前操作需要有效套餐。", status=409)
    job_id = uuid.uuid4()
    hold = freeze_quota(
        account_id=_video_account(subscription).pk,
        amount=duration_seconds,
        business_type="video_generation",
        business_id=job_id,
        idempotency_key=f"video-freeze-{job_id}",
        request_id=request_id,
    )
    job = VideoGenerationJob.objects.create(
        id=job_id,
        user=user,
        tenant_id=user.tenant_id,
        subject=subject,
        generation_mode=generation_mode,
        prompt=clean_prompt,
        prompt_digest=hashlib.sha256(clean_prompt.encode()).hexdigest(),
        source_document_version=source_document,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        resolution=settings.VIDEO_RESOLUTION,
        provider_key=settings.VIDEO_PROVIDER,
        provider_model_id=settings.VIDEO_MODEL,
        subscription=subscription,
        quota_hold=hold,
        idempotency_key_digest=idem,
        request_digest=request_digest,
        request_id=request_id,
    )
    return job, True


def _read_object(key: str, max_bytes: int) -> bytes:
    try:
        with storage_provider().open_object(key) as source:
            data = source.read(max_bytes + 1)
    except FileStorageUnavailable as exc:
        raise VideoServiceUnavailable(
            "VIDEO_STORAGE_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_STORAGE_FAILED"]
        ) from exc
    if len(data) > max_bytes:
        raise VideoInputInvalid("VIDEO_SOURCE_IMAGE_TOO_LARGE", "参考图片不能超过 20 MB。")
    return data


def _fit_first_frame(data: bytes, aspect_ratio: str) -> bytes:
    width, height = FIRST_FRAME_DIMENSIONS[aspect_ratio]
    try:
        maximum = getattr(settings, "VIDEO_SOURCE_IMAGE_MAX_BYTES", SOURCE_IMAGE_MAX_BYTES)
        if not data or len(data) > maximum:
            raise VideoInputInvalid("VIDEO_SOURCE_IMAGE_TOO_LARGE", "参考图片不能超过 20 MB。")
        with Image.open(io.BytesIO(data)) as checked:
            checked.verify()
        with Image.open(io.BytesIO(data)) as opened:
            if getattr(opened, "n_frames", 1) != 1:
                raise VideoInputInvalid("VIDEO_SOURCE_IMAGE_INVALID", "所选图片无法用于视频生成。")
            image_format = opened.format or ""
            if (
                image_format not in SOURCE_IMAGE_MIMES
                or opened.width < 1
                or opened.height < 1
                or opened.width * opened.height > settings.IMAGE_MAX_PIXELS
            ):
                raise VideoInputInvalid("VIDEO_SOURCE_IMAGE_INVALID", "所选图片无法用于视频生成。")
            frame = ImageOps.fit(
                opened.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS
            )
            output = io.BytesIO()
            frame.save(output, format="JPEG", quality=90, optimize=True)
            return output.getvalue()
    except VideoBusinessError:
        raise
    except (
        ImageBusinessError,
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ) as exc:
        raise VideoInputInvalid("VIDEO_SOURCE_IMAGE_INVALID", "所选图片无法用于视频生成。") from exc


def _generate_first_frame_bytes(job: VideoGenerationJob) -> tuple[bytes, str, str]:
    if job.generation_mode == VideoGenerationJob.GenerationMode.IMAGE:
        assert job.source_document_version is not None
        data = _read_object(
            job.source_document_version.object_key,
            getattr(settings, "VIDEO_SOURCE_IMAGE_MAX_BYTES", SOURCE_IMAGE_MAX_BYTES),
        )
        return _fit_first_frame(data, job.aspect_ratio), "", ""

    try:
        raw, provider_key, provider_model_id = generate_internal_video_first_frame(
            prompt=job.prompt,
            aspect_ratio=job.aspect_ratio,
            request_id=job.request_id,
            correlation_id=job.pk,
        )
        return _fit_first_frame(raw, job.aspect_ratio), provider_key, provider_model_id
    except (AIAdapterError, ImageBusinessError, IndexError, ValueError) as exc:
        raise VideoServiceUnavailable(
            "VIDEO_FIRST_FRAME_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_FIRST_FRAME_FAILED"]
        ) from exc


def ensure_first_frame(job_id) -> ImageAsset:
    frame_id = uuid.uuid5(FIRST_FRAME_NAMESPACE, str(job_id))
    existing = ImageAsset.objects.filter(pk=frame_id).first()
    if existing is not None:
        return existing
    job = VideoGenerationJob.objects.select_related("source_document_version").get(pk=job_id)
    data, provider_key, provider_model = _generate_first_frame_bytes(job)
    digest = hashlib.sha256(data).hexdigest()
    width, height = FIRST_FRAME_DIMENSIONS[job.aspect_ratio]
    object_key = (
        f"users/{job.user_id}/subjects/{job.subject_id}/videos/{job.pk.hex}/first-frame.jpg"
    )
    provider = storage_provider()
    try:
        provider.put_system_object(key=object_key, data=data, content_type="image/jpeg")
        metadata = provider.head_object(object_key)
    except FileStorageUnavailable as exc:
        raise VideoServiceUnavailable(
            "VIDEO_STORAGE_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_STORAGE_FAILED"]
        ) from exc
    if (
        metadata.size != len(data)
        or metadata.content_type != "image/jpeg"
        or metadata.metadata.get("sha256") != digest
    ):
        raise VideoServiceUnavailable(
            "VIDEO_STORAGE_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_STORAGE_FAILED"]
        )
    asset, _ = ImageAsset.objects.get_or_create(
        id=frame_id,
        defaults={
            "user_id": job.user_id,
            "subject_id": job.subject_id,
            "source_type": ImageAsset.SourceType.GENERATED,
            "role": ImageGenerationJob.Role.ILLUSTRATION,
            "object_key": object_key,
            "width": width,
            "height": height,
            "mime_type": "image/jpeg",
            "size_bytes": len(data),
            "sha256": digest,
            "provider_key": provider_key,
            "provider_model_id": provider_model,
            "generation_capability": "video_first_frame",
            "adapter_version": "geo-video-first-frame-v1",
            "prompt_digest": job.prompt_digest,
            "source_provenance": {
                "mode": job.generation_mode,
                "source_document_version_id": (
                    str(job.source_document_version_id) if job.source_document_version_id else None
                ),
            },
            "moderation_status": ImageAsset.ModerationStatus.APPROVED,
            "is_subject_library": False,
            "generated_at": timezone.now(),
            "available_at": timezone.now(),
        },
    )
    return asset


def _settle(job: VideoGenerationJob, action: str) -> None:
    operation = consume_hold if action == "consume" else release_hold
    operation(
        hold_id=job.quota_hold_id,
        amount=job.duration_seconds,
        idempotency_key=f"video-{action}-{job.pk}",
        request_id=job.request_id,
    )


@transaction.atomic
def terminal_failure(job_id, code: str, message: str | None = None) -> dict[str, Any]:
    job = VideoGenerationJob.objects.select_for_update().get(pk=job_id)
    if job.status in {VideoGenerationJob.Status.SUCCEEDED, VideoGenerationJob.Status.FAILED}:
        return {"status": job.status}
    logger.warning(
        "video generation moved to terminal failure",
        extra={"job_id": str(job.pk), "stage": job.stage, "safe_code": code[:100]},
    )
    _settle(job, "release")
    job.status = VideoGenerationJob.Status.FAILED
    job.safe_error_code = code[:100]
    job.safe_error_message = (
        message
        or SAFE_FAILURE_MESSAGES.get(code)
        or SAFE_FAILURE_MESSAGES["VIDEO_INTERNAL_FAILURE"]
    )[:200]
    job.next_attempt_at = None
    job.lease_generation = None
    job.lease_expires_at = None
    job.finished_at = timezone.now()
    job.version += 1
    job.save(
        update_fields=(
            "status",
            "safe_error_code",
            "safe_error_message",
            "next_attempt_at",
            "lease_generation",
            "lease_expires_at",
            "finished_at",
            "version",
            "updated_at",
        )
    )
    return {"status": VideoGenerationJob.Status.FAILED}


def _claim_job(job_id) -> tuple[VideoGenerationJob | None, str, int]:
    now = timezone.now()
    ambiguous = False
    with transaction.atomic():
        job = VideoGenerationJob.objects.select_for_update().get(pk=job_id)
        if job.status in {VideoGenerationJob.Status.SUCCEEDED, VideoGenerationJob.Status.FAILED}:
            return None, job.status, 0
        if job.next_attempt_at and job.next_attempt_at > now:
            delay = max(1, int((job.next_attempt_at - now).total_seconds()))
            return None, "waiting", delay
        if job.lease_expires_at and job.lease_expires_at > now:
            return None, "busy", 5
        if job.stage == VideoGenerationJob.Stage.SUBMITTING and not job.provider_job_id:
            ambiguous = True
        else:
            generation = uuid.uuid4()
            job.lease_generation = generation
            job.lease_expires_at = now + timedelta(seconds=settings.VIDEO_JOB_LEASE_SECONDS)
            job.status = VideoGenerationJob.Status.PROCESSING
            job.started_at = job.started_at or now
            job.next_attempt_at = None
            job.safe_error_code = ""
            job.safe_error_message = ""
            job.save(
                update_fields=(
                    "lease_generation",
                    "lease_expires_at",
                    "status",
                    "started_at",
                    "next_attempt_at",
                    "safe_error_code",
                    "safe_error_message",
                    "updated_at",
                )
            )
            job._claimed_generation = generation  # type: ignore[attr-defined]
            return job, "claimed", 0
    if ambiguous:
        terminal_failure(job_id, "VIDEO_SUBMISSION_UNCERTAIN")
    return None, "failed", 0


@transaction.atomic
def _advance(job_id, generation, **changes) -> bool:
    job = VideoGenerationJob.objects.select_for_update().get(pk=job_id)
    if job.lease_generation != generation or job.status != VideoGenerationJob.Status.PROCESSING:
        return False
    for key, value in changes.items():
        setattr(job, key, value)
    job.lease_generation = None
    job.lease_expires_at = None
    job.version += 1
    update_fields = tuple(changes) + (
        "lease_generation",
        "lease_expires_at",
        "version",
        "updated_at",
    )
    job.save(update_fields=update_fields)
    return True


@transaction.atomic
def _mark_submitting(job_id, generation) -> bool:
    """Persist the one-way provider submission boundary while retaining the lease."""

    job = VideoGenerationJob.objects.select_for_update().get(pk=job_id)
    if job.lease_generation != generation or job.status != VideoGenerationJob.Status.PROCESSING:
        return False
    job.stage = VideoGenerationJob.Stage.SUBMITTING
    job.version += 1
    job.save(update_fields=("stage", "version", "updated_at"))
    return True


def _schedule_retry(job_id, generation, *, stage: str, code: str, message: str, delay: int):
    with transaction.atomic():
        job = VideoGenerationJob.objects.select_for_update().get(pk=job_id)
        if job.lease_generation != generation or job.status != VideoGenerationJob.Status.PROCESSING:
            return {"status": job.status}
        job.attempt_count += 1
        if job.attempt_count > 3:
            transaction.set_rollback(True)
        else:
            job.stage = stage
            job.safe_error_code = code[:100]
            job.safe_error_message = message[:200]
            job.next_attempt_at = timezone.now() + timedelta(seconds=delay)
            job.lease_generation = None
            job.lease_expires_at = None
            job.version += 1
            job.save(
                update_fields=(
                    "attempt_count",
                    "stage",
                    "safe_error_code",
                    "safe_error_message",
                    "next_attempt_at",
                    "lease_generation",
                    "lease_expires_at",
                    "version",
                    "updated_at",
                )
            )
            return {"status": "waiting", "retry_after": delay}
    return terminal_failure(job_id, code, message)


def _first_frame_data_url(job: VideoGenerationJob) -> str:
    if job.first_frame_id is None:
        raise VideoServiceUnavailable(
            "VIDEO_FIRST_FRAME_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_FIRST_FRAME_FAILED"]
        )
    data = _read_object(
        job.first_frame.object_key,
        getattr(settings, "VIDEO_SOURCE_IMAGE_MAX_BYTES", SOURCE_IMAGE_MAX_BYTES),
    )
    if job.first_frame.mime_type != "image/jpeg" or not data:
        raise VideoServiceUnavailable(
            "VIDEO_FIRST_FRAME_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_FIRST_FRAME_FAILED"]
        )
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode('ascii')}"


def _provider_failure_code(exc: VideoProviderError) -> str:
    if exc.code == "rate_limited":
        return "VIDEO_PROVIDER_RATE_LIMIT"
    if exc.code == "timeout":
        return "VIDEO_PROVIDER_TIMEOUT"
    if exc.code in {"authentication_failed", "permission_denied"}:
        return "VIDEO_PROVIDER_AUTHENTICATION_FAILED"
    if exc.code in {"invalid_request", "request_rejected"}:
        return "VIDEO_CONTENT_REJECTED"
    return "VIDEO_PROVIDER_TEMPORARY_FAILURE"


def _download_video(url: str) -> tuple[BinaryIO, int, str]:
    try:
        target = canonicalize_url(url)
        if target.scheme != "https":
            raise ValueError
        # The provider contract returns a short-lived DashScope OSS URL. Restricting
        # the hostname prevents a compromised/malformed response from becoming a
        # general-purpose server-side request primitive.
        if ALIYUN_VIDEO_RESULT_HOST.fullmatch(target.host) is None:
            raise ValueError
        resolve_and_validate(target.host, target.port)
    except (WebSourceError, ValueError, TypeError):
        raise VideoServiceUnavailable(
            "VIDEO_DOWNLOAD_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_DOWNLOAD_FAILED"]
        ) from None
    url = target.value
    maximum = settings.VIDEO_MAX_BYTES
    spool = tempfile.SpooledTemporaryFile(max_size=min(maximum, 16 * 1024 * 1024))
    digest = hashlib.sha256()
    total = 0
    try:
        timeout = httpx.Timeout(float(settings.VIDEO_DOWNLOAD_TIMEOUT_SECONDS))
        with httpx.Client(follow_redirects=False, trust_env=False, timeout=timeout) as client:
            with client.stream("GET", url, headers={"Accept": "video/mp4"}) as response:
                response.raise_for_status()
                declared = response.headers.get("content-length")
                if declared and int(declared) > maximum:
                    raise VideoServiceUnavailable(
                        "VIDEO_DOWNLOAD_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_DOWNLOAD_FAILED"]
                    )
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    total += len(chunk)
                    if total > maximum:
                        raise VideoServiceUnavailable(
                            "VIDEO_DOWNLOAD_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_DOWNLOAD_FAILED"]
                        )
                    digest.update(chunk)
                    spool.write(chunk)
        if total < 12:
            raise VideoServiceUnavailable(
                "VIDEO_DOWNLOAD_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_DOWNLOAD_FAILED"]
            )
        spool.seek(0)
        if spool.read(12)[4:8] != b"ftyp":
            raise VideoServiceUnavailable(
                "VIDEO_DOWNLOAD_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_DOWNLOAD_FAILED"]
            )
        spool.seek(0)
        return cast(BinaryIO, spool), total, digest.hexdigest()
    except VideoBusinessError:
        spool.close()
        raise
    except (httpx.HTTPError, OSError, ValueError) as exc:
        spool.close()
        raise VideoServiceUnavailable(
            "VIDEO_DOWNLOAD_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_DOWNLOAD_FAILED"]
        ) from exc


def _store_video(job: VideoGenerationJob, video_url: str) -> StoredVideo:
    existing = VideoAsset.objects.filter(generation_job=job).first()
    if existing is not None:
        return StoredVideo(
            id=existing.pk,
            object_key=existing.object_key,
            size_bytes=existing.size_bytes,
            sha256=existing.sha256,
        )
    stream, size, digest = _download_video(video_url)
    asset_id = uuid.uuid5(VIDEO_ASSET_NAMESPACE, str(job.pk))
    object_key = f"users/{job.user_id}/subjects/{job.subject_id}/videos/{asset_id.hex}/original.mp4"
    provider = storage_provider()
    try:
        provider.put_system_stream(
            key=object_key,
            stream=stream,
            content_type="video/mp4",
            size=size,
            sha256=digest,
        )
        metadata = provider.head_object(object_key)
    except FileStorageUnavailable as exc:
        raise VideoServiceUnavailable(
            "VIDEO_STORAGE_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_STORAGE_FAILED"]
        ) from exc
    finally:
        stream.close()
    if (
        metadata.size != size
        or metadata.content_type != "video/mp4"
        or metadata.metadata.get("sha256") != digest
    ):
        raise VideoServiceUnavailable(
            "VIDEO_STORAGE_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_STORAGE_FAILED"]
        )
    return StoredVideo(
        id=asset_id,
        object_key=object_key,
        size_bytes=size,
        sha256=digest,
    )


@transaction.atomic
def _finish_success(job_id, generation, stored: StoredVideo) -> dict[str, Any]:
    job = VideoGenerationJob.objects.select_for_update().get(pk=job_id)
    if job.status == VideoGenerationJob.Status.SUCCEEDED:
        return {"status": job.status, "video_id": str(stored.id)}
    if job.lease_generation != generation or job.status != VideoGenerationJob.Status.PROCESSING:
        return {"status": job.status}
    asset, created = VideoAsset.objects.get_or_create(
        id=stored.id,
        defaults={
            "user_id": job.user_id,
            "tenant_id": job.tenant_id,
            "subject_id": job.subject_id,
            "generation_job_id": job.pk,
            "object_key": stored.object_key,
            "duration_seconds": job.duration_seconds,
            "aspect_ratio": job.aspect_ratio,
            "resolution": job.resolution,
            "mime_type": "video/mp4",
            "size_bytes": stored.size_bytes,
            "sha256": stored.sha256,
            "available_at": timezone.now(),
        },
    )
    if not created and (
        asset.generation_job_id != job.pk
        or asset.user_id != job.user_id
        or asset.tenant_id != job.tenant_id
        or asset.subject_id != job.subject_id
        or asset.object_key != stored.object_key
        or asset.size_bytes != stored.size_bytes
        or asset.sha256 != stored.sha256
    ):
        raise VideoServiceUnavailable(
            "VIDEO_STORAGE_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_STORAGE_FAILED"]
        )
    _settle(job, "consume")
    job.status = VideoGenerationJob.Status.SUCCEEDED
    job.stage = VideoGenerationJob.Stage.COMPLETE
    job.safe_error_code = ""
    job.safe_error_message = ""
    job.next_attempt_at = None
    job.lease_generation = None
    job.lease_expires_at = None
    job.finished_at = timezone.now()
    job.version += 1
    job.save(
        update_fields=(
            "status",
            "stage",
            "safe_error_code",
            "safe_error_message",
            "next_attempt_at",
            "lease_generation",
            "lease_expires_at",
            "finished_at",
            "version",
            "updated_at",
        )
    )
    return {"status": job.status, "video_id": str(asset.pk)}


def execute_video_job(*, job_id) -> dict[str, Any]:
    claimed, state, retry_after = _claim_job(job_id)
    if claimed is None:
        result: dict[str, Any] = {"status": state}
        if retry_after:
            result["retry_after"] = retry_after
        return result
    generation = claimed._claimed_generation  # type: ignore[attr-defined]
    stage = claimed.stage
    try:
        if stage == VideoGenerationJob.Stage.FIRST_FRAME:
            frame = ensure_first_frame(claimed.pk)
            _advance(
                claimed.pk,
                generation,
                first_frame_id=frame.pk,
                stage=VideoGenerationJob.Stage.SUBMIT,
            )
            return {"status": "continue", "retry_after": 0}

        if stage == VideoGenerationJob.Stage.SUBMIT:
            if not _mark_submitting(claimed.pk, generation):
                return {"status": "busy", "retry_after": 5}
            submitting = VideoGenerationJob.objects.select_related("first_frame").get(pk=claimed.pk)
            try:
                created = video_provider().create_video(
                    prompt=submitting.prompt,
                    image_url=_first_frame_data_url(submitting),
                    duration_seconds=submitting.duration_seconds,
                )
            except VideoProviderError as exc:
                code = _provider_failure_code(exc)
                logger.warning(
                    "video provider submission failed",
                    extra={
                        "job_id": str(submitting.pk),
                        "stage": "submit",
                        "safe_code": code,
                    },
                )
                if exc.retryable and exc.code == "rate_limited":
                    # A 429 response is a definite rejection, so resubmission cannot
                    # duplicate a provider task. Timeouts/5xx are intentionally not
                    # retried because the upstream acceptance state is unknowable.
                    return _schedule_retry(
                        submitting.pk,
                        generation,
                        stage=VideoGenerationJob.Stage.SUBMIT,
                        code=code,
                        message="当前使用人数较多，系统正在自动重试。",
                        delay=min(60, 5 * (2**submitting.attempt_count)),
                    )
                if exc.retryable:
                    return terminal_failure(submitting.pk, "VIDEO_SUBMISSION_UNCERTAIN")
                return terminal_failure(submitting.pk, code)
            except (VideoBusinessError, ValueError) as exc:
                code = getattr(exc, "code", "VIDEO_PROVIDER_TEMPORARY_FAILURE")
                logger.warning(
                    "video provider submission rejected",
                    extra={
                        "job_id": str(submitting.pk),
                        "stage": "submit",
                        "safe_code": code,
                    },
                )
                return terminal_failure(submitting.pk, code)
            with transaction.atomic():
                locked = VideoGenerationJob.objects.select_for_update().get(pk=submitting.pk)
                if (
                    locked.status != VideoGenerationJob.Status.PROCESSING
                    or locked.lease_generation != generation
                    or locked.stage != VideoGenerationJob.Stage.SUBMITTING
                ):
                    return {"status": locked.status}
                locked.provider_job_id = created.task_id
                locked.provider_request_id = created.request_id or ""
                locked.stage = VideoGenerationJob.Stage.POLL
                locked.next_attempt_at = timezone.now() + timedelta(
                    seconds=settings.VIDEO_POLL_SECONDS
                )
                locked.lease_generation = None
                locked.lease_expires_at = None
                locked.version += 1
                locked.save(
                    update_fields=(
                        "provider_job_id",
                        "provider_request_id",
                        "stage",
                        "next_attempt_at",
                        "lease_generation",
                        "lease_expires_at",
                        "version",
                        "updated_at",
                    )
                )
            return {"status": "waiting", "retry_after": settings.VIDEO_POLL_SECONDS}

        if stage == VideoGenerationJob.Stage.POLL:
            if not claimed.provider_job_id:
                return terminal_failure(claimed.pk, "VIDEO_SUBMISSION_UNCERTAIN")
            provider = video_provider()
            provider_status = provider.get_status(claimed.provider_job_id)
            if provider_status in {
                VideoTaskStatus.PENDING,
                VideoTaskStatus.RUNNING,
                VideoTaskStatus.UNKNOWN,
            }:
                if claimed.poll_count + 1 >= settings.VIDEO_MAX_POLLS:
                    return terminal_failure(claimed.pk, "VIDEO_PROVIDER_TIMEOUT")
                _advance(
                    claimed.pk,
                    generation,
                    poll_count=claimed.poll_count + 1,
                    next_attempt_at=timezone.now() + timedelta(seconds=settings.VIDEO_POLL_SECONDS),
                )
                return {"status": "waiting", "retry_after": settings.VIDEO_POLL_SECONDS}
            if provider_status in {VideoTaskStatus.FAILED, VideoTaskStatus.CANCELED}:
                return terminal_failure(claimed.pk, "VIDEO_CONTENT_REJECTED")
            _advance(claimed.pk, generation, stage=VideoGenerationJob.Stage.TRANSFER)
            return {"status": "continue", "retry_after": 0}

        if stage == VideoGenerationJob.Stage.TRANSFER:
            if not claimed.provider_job_id:
                return terminal_failure(claimed.pk, "VIDEO_SUBMISSION_UNCERTAIN")
            provider_result = video_provider().get_result(claimed.provider_job_id)
            if provider_result.status in {VideoTaskStatus.PENDING, VideoTaskStatus.RUNNING}:
                _advance(
                    claimed.pk,
                    generation,
                    stage=VideoGenerationJob.Stage.POLL,
                    next_attempt_at=timezone.now() + timedelta(seconds=settings.VIDEO_POLL_SECONDS),
                )
                return {"status": "waiting", "retry_after": settings.VIDEO_POLL_SECONDS}
            if not provider_result.ready or provider_result.video_url is None:
                return terminal_failure(claimed.pk, "VIDEO_CONTENT_REJECTED")
            stored = _store_video(claimed, provider_result.video_url)
            return _finish_success(claimed.pk, generation, stored)

        return terminal_failure(claimed.pk, "VIDEO_INTERNAL_FAILURE")
    except VideoProviderError as exc:
        safe_code = _provider_failure_code(exc)
        logger.warning(
            "video provider operation failed",
            extra={"job_id": str(claimed.pk), "stage": stage, "safe_code": safe_code},
        )
        if exc.retryable and stage != VideoGenerationJob.Stage.SUBMIT:
            return _schedule_retry(
                claimed.pk,
                generation,
                stage=stage,
                code=safe_code,
                message="视频生成暂时中断，系统正在自动重试。",
                delay=min(60, 5 * (2**claimed.attempt_count)),
            )
        return terminal_failure(claimed.pk, safe_code)
    except VideoBusinessError as exc:
        logger.warning(
            "video business operation failed",
            extra={"job_id": str(claimed.pk), "stage": stage, "safe_code": exc.code},
        )
        if stage == VideoGenerationJob.Stage.TRANSFER:
            return _schedule_retry(
                claimed.pk,
                generation,
                stage=stage,
                code=exc.code,
                message=exc.message,
                delay=min(60, 5 * (2**claimed.attempt_count)),
            )
        return terminal_failure(claimed.pk, exc.code, exc.message)
    except Exception as exc:
        logger.error(
            "video generation failed",
            extra={
                "job_id": str(claimed.pk),
                "stage": stage,
                "safe_code": "VIDEO_INTERNAL_FAILURE",
                "exception_type": type(exc).__name__,
            },
        )
        return terminal_failure(claimed.pk, "VIDEO_INTERNAL_FAILURE")


def video_job_for_user(*, user, job_id) -> VideoGenerationJob:
    try:
        return VideoGenerationJob.objects.select_related(
            "result_asset", "quota_hold", "subject", "first_frame"
        ).get(pk=job_id, user=user, tenant_id=user.tenant_id, subject__user=user)
    except VideoGenerationJob.DoesNotExist as exc:
        raise Http404 from exc


def video_asset_for_user(*, user, video_id, subject_id=None) -> VideoAsset:
    query = VideoAsset.objects.select_related("generation_job").filter(
        pk=video_id,
        user=user,
        tenant_id=user.tenant_id,
        subject__user=user,
        generation_job__user=user,
        generation_job__tenant_id=user.tenant_id,
        generation_job__status=VideoGenerationJob.Status.SUCCEEDED,
    )
    if subject_id is not None:
        query = query.filter(subject_id=subject_id)
    try:
        return query.get()
    except VideoAsset.DoesNotExist as exc:
        raise Http404 from exc


def _video_content_url(video: VideoAsset) -> str:
    return f"/api/v1/subjects/{video.subject_id}/videos/{video.pk}/content"


def video_payload(video: VideoAsset) -> dict[str, Any]:
    return {
        "id": str(video.pk),
        "subject_id": str(video.subject_id),
        "job_id": str(video.generation_job_id),
        "duration_seconds": video.duration_seconds,
        "aspect_ratio": video.aspect_ratio,
        "resolution": video.resolution.lower(),
        "mime_type": video.mime_type,
        "size_bytes": video.size_bytes,
        "is_subject_library": video.is_subject_library,
        "url": _video_content_url(video),
        "url_expires_in": None,
        "version": video.version,
        "created_at": video.created_at,
    }


def job_payload(job: VideoGenerationJob) -> dict[str, Any]:
    video = (
        getattr(job, "result_asset", None)
        if job.status == VideoGenerationJob.Status.SUCCEEDED
        else None
    )
    return {
        "id": str(job.pk),
        "subject_id": str(job.subject_id),
        "generation_mode": job.generation_mode,
        "prompt": job.prompt,
        "source_document_version_id": (
            str(job.source_document_version_id) if job.source_document_version_id else None
        ),
        "aspect_ratio": job.aspect_ratio,
        "duration_seconds": job.duration_seconds,
        "resolution": job.resolution.lower(),
        "status": job.status,
        "stage": job.stage,
        "safe_error_code": job.safe_error_code,
        "safe_error_message": job.safe_error_message,
        "quota_status": job.quota_hold.status,
        "video": video_payload(video) if video else None,
        "version": job.version,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.finished_at,
        "finished_at": job.finished_at,
    }


def quota_summary(user) -> dict[str, int | bool]:
    if user.is_test_account:
        return {"available": 0, "frozen": 0, "consumed": 0, "unlimited": True}
    subscription = current_subscription(user)
    if subscription is None:
        return {"available": 0, "frozen": 0, "consumed": 0, "unlimited": False}
    totals = QuotaAccount.objects.filter(
        subscription=subscription,
        quota_type="video_credits",
        cycle_started_at__isnull=True,
    ).aggregate(
        available=Sum("available"),
        frozen=Sum("frozen"),
        entitlement=Sum("entitlement_amount"),
    )
    available = int(totals["available"] or 0)
    frozen = int(totals["frozen"] or 0)
    entitlement = int(totals["entitlement"] or 0)
    return {
        "available": available,
        "frozen": frozen,
        "consumed": max(0, entitlement - available - frozen),
        "unlimited": False,
    }


@transaction.atomic
def save_to_library(*, user, job_id, expected_version) -> VideoAsset:
    job = video_job_for_user(user=user, job_id=job_id)
    if job.status != VideoGenerationJob.Status.SUCCEEDED:
        raise VideoBusinessError("VIDEO_NOT_READY", "视频尚未生成完成，请稍后重试。", status=409)
    try:
        video = VideoAsset.objects.select_for_update().get(generation_job=job)
    except VideoAsset.DoesNotExist as exc:
        raise VideoBusinessError(
            "VIDEO_NOT_READY", "视频尚未生成完成，请稍后重试。", status=409
        ) from exc
    if video.version != expected_version:
        raise VideoVersionConflict
    if not video.is_subject_library:
        video.is_subject_library = True
        video.version += 1
        video.save(update_fields=("is_subject_library", "version", "updated_at"))
    return video


def create_download_intent(*, user, job_id) -> dict[str, Any]:
    job = video_job_for_user(user=user, job_id=job_id)
    if job.status != VideoGenerationJob.Status.SUCCEEDED:
        raise VideoBusinessError("VIDEO_NOT_READY", "视频尚未生成完成，请稍后重试。", status=409)
    try:
        video = VideoAsset.objects.get(generation_job=job)
    except VideoAsset.DoesNotExist as exc:
        raise VideoBusinessError(
            "VIDEO_NOT_READY", "视频尚未生成完成，请稍后重试。", status=409
        ) from exc
    try:
        url = storage_provider().create_download_url(
            key=video.object_key,
            filename=f"video-{video.pk}.mp4",
            content_type=video.mime_type,
        )
    except FileStorageUnavailable as exc:
        raise VideoServiceUnavailable(
            "VIDEO_STORAGE_FAILED", SAFE_FAILURE_MESSAGES["VIDEO_STORAGE_FAILED"]
        ) from exc
    return {"url": url, "expires_in": settings.FILE_DOWNLOAD_URL_TTL}


def regenerate_video_job(*, user, job_id, idempotency_key, request_id):
    old = video_job_for_user(user=user, job_id=job_id)
    return create_video_job(
        user=user,
        subject_id=old.subject_id,
        generation_mode=old.generation_mode,
        prompt=old.prompt,
        source_document_version_id=old.source_document_version_id,
        aspect_ratio=old.aspect_ratio,
        duration_seconds=old.duration_seconds,
        idempotency_key=idempotency_key,
        request_id=request_id,
    )
