from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import uuid
import zipfile
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.ai.contracts import AIAdapterRequest, AIModelCapability
from apps.ai.credentials import capability_credential_snapshot
from apps.ai.errors import AIAdapterError
from apps.ai.exceptions import AICredentialCryptoFailure, AICredentialStateConflict
from apps.ai.image_generation import ImageGenerationPayload
from apps.ai.models import AICapabilityRuntimeConfig
from apps.ai.registry import model_registry
from apps.ai.runtime import get_capability_runtime_snapshot
from apps.articles.models import Article
from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.models import DocumentVersion
from apps.documents.storage import storage_provider
from apps.plans.subscription_services import current_subscription
from apps.quotas.models import QuotaAccount
from apps.quotas.services import (
    consume_hold,
    freeze_quota,
    quota_account_for_subscription,
    release_hold,
)
from apps.subjects.models import Subject
from apps.web_sources.exceptions import WebSourceError
from apps.web_sources.http_transport import fetch_binary_url
from apps.web_sources.url_security import canonicalize_url, resolve_and_validate

from .exceptions import (
    ImageBusinessError,
    ImageCredentialUnavailable,
    ImageInputInvalid,
    ImageRuntimeUnavailable,
    ImageStorageUnavailable,
)
from .models import (
    ImageAsset,
    ImageBatchDownload,
    ImageDerivative,
    ImageGenerationJob,
    ImageGenerationResult,
    ImageModerationReview,
    ImageReferenceLink,
    ImageSizePreset,
    ImageStylePreset,
)

ALLOWED_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
MIME_BY_FORMAT = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
EXTENSION_BY_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
IMAGE_SCHEMA_VERSION = "geo-image-v1"
SECURITY_PATTERNS = (
    "system prompt",
    "developer message",
    "ignore previous",
    "api key",
    "api_key",
    "secret key",
    "credential",
    "provider json",
    "系统提示词",
    "开发者消息",
    "忽略之前",
    "密钥",
    "凭据",
    "供应商原始",
)
SENSITIVE_FAILURES = {
    "IMAGE_INPUT_TEXT_SENSITIVE": "input_text",
    "IMAGE_INPUT_REFERENCE_SENSITIVE": "input_image",
    "IMAGE_OUTPUT_SENSITIVE": "output_image",
}


def digest_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _idempotency(*, user_id, namespace: str, raw_key: str) -> str:
    key = raw_key.strip()
    if not key or len(key) > 200 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise ImageInputInvalid("IMAGE_IDEMPOTENCY_KEY_REQUIRED")
    derived = hmac.new(
        settings.IMAGE_IDEMPOTENCY_HMAC_KEY.encode(),
        f"image:{namespace}:v1".encode(),
        hashlib.sha256,
    ).digest()
    return hmac.new(derived, f"{user_id}:{key}".encode(), hashlib.sha256).hexdigest()


def _subject(user, subject_id, *, lock=False) -> Subject:
    query = Subject.objects.filter(user=user)
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        subject = query.get(pk=subject_id)
    except Subject.DoesNotExist as exc:
        raise Http404 from exc
    if subject.status != Subject.Status.ACTIVE:
        raise ImageInputInvalid("IMAGE_SUBJECT_NOT_READY")
    return subject


def _article(user, article_id, subject, *, lock=False) -> Article | None:
    if article_id is None:
        return None
    query = Article.objects.filter(user=user, subject=subject)
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get(pk=article_id)
    except Article.DoesNotExist as exc:
        raise Http404 from exc


def _image_account(subscription) -> QuotaAccount:
    try:
        return quota_account_for_subscription(
            subscription=subscription,
            quota_type="image_generations",
            legacy_quota_type="image_credits",
        )
    except Exception as exc:
        raise ImageBusinessError("IMAGE_QUOTA_ACCOUNT_UNAVAILABLE") from exc


def _runtime_and_binding():
    try:
        runtime = get_capability_runtime_snapshot(
            provider_key="doubao", capability=AIModelCapability.IMAGE_GENERATION
        )
    except AIAdapterError as exc:
        raise ImageRuntimeUnavailable(exc.stable_code) from exc
    try:
        binding = capability_credential_snapshot(
            provider_key="doubao", capability=AIModelCapability.IMAGE_GENERATION
        )
    except (AICredentialStateConflict, AICredentialCryptoFailure) as exc:
        raise ImageCredentialUnavailable from exc
    return runtime, binding


def _validate_reference_url(raw_url: str) -> str:
    try:
        canonical = canonicalize_url(raw_url)
        resolve_and_validate(canonical.host, canonical.port)
    except WebSourceError as exc:
        raise ImageInputInvalid("IMAGE_REFERENCE_URL_UNSAFE") from exc
    return canonical.value


def _reference(
    *, user, subject, asset_id=None, document_version_id=None, reference_url=""
) -> tuple[ImageAsset | None, DocumentVersion | None, str, dict[str, Any]]:
    selected = sum(bool(value) for value in (asset_id, document_version_id, reference_url))
    if selected > 1:
        raise ImageInputInvalid("IMAGE_REFERENCE_EXCLUSIVE")
    if asset_id:
        try:
            asset = ImageAsset.objects.get(
                pk=asset_id,
                user=user,
                subject=subject,
                lifecycle_status=ImageAsset.LifecycleStatus.ACTIVE,
            )
        except ImageAsset.DoesNotExist as exc:
            raise Http404 from exc
        if asset.moderation_status != ImageAsset.ModerationStatus.APPROVED:
            raise ImageInputInvalid("IMAGE_REFERENCE_NOT_APPROVED")
        return (
            asset,
            None,
            "",
            {
                "type": "asset",
                "id": str(asset.pk),
                "sha256": asset.sha256,
                "object_key_digest": hashlib.sha256(asset.object_key.encode()).hexdigest(),
            },
        )
    if document_version_id:
        try:
            version = DocumentVersion.objects.select_related("document").get(
                pk=document_version_id,
                document__user=user,
                document__subject=subject,
                detected_file_kind__in=("jpeg", "png", "webp"),
            )
        except DocumentVersion.DoesNotExist as exc:
            raise Http404 from exc
        return (
            None,
            version,
            "",
            {
                "type": "temporary_upload",
                "id": str(version.pk),
                "sha256": version.sha256,
                "mime_type": version.detected_mime,
            },
        )
    if reference_url:
        normalized = _validate_reference_url(reference_url)
        return (
            None,
            None,
            normalized,
            {
                "type": "external_url",
                "url_digest": hashlib.sha256(normalized.encode()).hexdigest(),
            },
        )
    return None, None, "", {"type": "none"}


@transaction.atomic
def create_image_job(
    *,
    user,
    subject_id,
    article_id,
    role,
    prompt,
    size_preset_id,
    style_preset_id,
    reference_asset_id,
    reference_document_version_id,
    reference_url,
    idempotency_key,
    request_id,
) -> tuple[ImageGenerationJob, bool]:
    subject = _subject(user, subject_id, lock=True)
    article = _article(user, article_id, subject, lock=True)
    clean_prompt = prompt.strip()
    if not clean_prompt or len(clean_prompt) > settings.IMAGE_PROMPT_MAX_LENGTH:
        raise ImageInputInvalid("IMAGE_PROMPT_INVALID")
    if any(value in clean_prompt.casefold() for value in SECURITY_PATTERNS):
        raise ImageBusinessError("IMAGE_SECURITY_REFUSED", status=403)
    if role not in ImageGenerationJob.Role.values:
        raise ImageInputInvalid("IMAGE_ROLE_INVALID")
    try:
        size = ImageSizePreset.objects.get(pk=size_preset_id, status="active")
        style = ImageStylePreset.objects.get(pk=style_preset_id, status="active")
    except (ImageSizePreset.DoesNotExist, ImageStylePreset.DoesNotExist) as exc:
        raise ImageInputInvalid("IMAGE_PRESET_INVALID") from exc
    if size.applicable_roles and role not in size.applicable_roles:
        raise ImageInputInvalid("IMAGE_SIZE_ROLE_INVALID")
    if style.applicable_roles and role not in style.applicable_roles:
        raise ImageInputInvalid("IMAGE_STYLE_ROLE_INVALID")
    reference_asset, reference_document, normalized_url, reference_snapshot = _reference(
        user=user,
        subject=subject,
        asset_id=reference_asset_id,
        document_version_id=reference_document_version_id,
        reference_url=reference_url,
    )
    runtime, binding = _runtime_and_binding()
    if settings.FILE_STORAGE_PROVIDER == "unavailable":
        raise ImageStorageUnavailable
    generation_type = (
        ImageGenerationJob.GenerationType.EDIT
        if reference_snapshot["type"] != "none"
        else ImageGenerationJob.GenerationType.GENERATE
    )
    request_snapshot = {
        "subject_id": str(subject.pk),
        "article_id": str(article.pk) if article else None,
        "role": role,
        "generation_type": generation_type,
        "prompt_digest": hashlib.sha256(clean_prompt.encode()).hexdigest(),
        "size": {"id": str(size.pk), "version": size.version},
        "style": {"id": str(style.pk), "version": style.version},
        "reference": reference_snapshot,
        "runtime_id": runtime.runtime_id,
        "runtime_version": runtime.version,
        "provider_model_id": runtime.provider_model_id,
    }
    idem = _idempotency(
        user_id=user.pk,
        namespace=f"generate:{subject.pk}",
        raw_key=idempotency_key,
    )
    request_digest = digest_json(request_snapshot)
    existing = ImageGenerationJob.objects.filter(idempotency_key_digest=idem).first()
    if existing is not None:
        if existing.user_id != user.pk or existing.request_digest != request_digest:
            raise ImageBusinessError("IMAGE_IDEMPOTENCY_CONFLICT")
        return existing, False
    subscription = current_subscription(user)
    if subscription is None:
        raise ImageBusinessError("IMAGE_PLAN_REQUIRED")
    job_id = uuid.uuid4()
    hold = freeze_quota(
        account_id=_image_account(subscription).pk,
        amount=1,
        business_type="image_generation",
        business_id=job_id,
        idempotency_key=f"image-freeze-{job_id}",
        request_id=request_id,
    )
    runtime_row = AICapabilityRuntimeConfig.objects.get(pk=runtime.runtime_id)
    size_snapshot = {
        "key": size.key,
        "name": size.name,
        "aspect_ratio": size.aspect_ratio,
        "width": size.width,
        "height": size.height,
        "provider_params": size.provider_params,
        "version": size.version,
    }
    style_snapshot = {
        "key": style.key,
        "name": style.name,
        "prompt_template": style.prompt_template,
        "version": style.version,
    }
    try:
        job = ImageGenerationJob.objects.create(
            id=job_id,
            user=user,
            subject=subject,
            article=article,
            generation_type=generation_type,
            role=role,
            prompt=clean_prompt,
            prompt_digest=hashlib.sha256(clean_prompt.encode()).hexdigest(),
            size_preset=size,
            size_snapshot=size_snapshot,
            style_preset=style,
            style_snapshot=style_snapshot,
            reference_asset=reference_asset,
            reference_document_version=reference_document,
            reference_url=normalized_url,
            reference_snapshot=reference_snapshot,
            runtime_config=runtime_row,
            runtime_version=runtime.version,
            provider_key=runtime.provider_key,
            provider_model_id=runtime.provider_model_id,
            api_version=runtime.api_version,
            adapter_version="doubao-image-generations-v1",
            prompt_version="geo-image-generation-v1",
            credential_binding_id=binding.binding_id,
            credential_binding_version=binding.binding_version,
            credential_id=binding.credential_id,
            credential_version=binding.credential_version,
            timeout_seconds=runtime.timeout_seconds,
            retry_base_seconds=runtime.retry_base_seconds,
            subscription=subscription,
            quota_hold=hold,
            max_retries=runtime.max_retries,
            idempotency_key_digest=idem,
            request_digest=request_digest,
            request_id=request_id,
        )
    except IntegrityError:
        replay = ImageGenerationJob.objects.filter(idempotency_key_digest=idem).first()
        if replay is None or replay.request_digest != request_digest:
            raise
        return replay, False
    if reference_asset is not None:
        ImageReferenceLink.objects.create(
            job=job,
            image=reference_asset,
            snapshot_digest=digest_json(reference_snapshot),
        )
    return job, True


def _validated_image(data: bytes, claimed_mime: str | None = None) -> tuple[int, int, str]:
    if not data or len(data) > settings.IMAGE_MAX_BYTES:
        raise ImageInputInvalid("IMAGE_MEDIA_SIZE_INVALID")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.verify()
        with Image.open(io.BytesIO(data)) as opened:
            if getattr(opened, "n_frames", 1) != 1:
                raise ImageInputInvalid("IMAGE_MEDIA_ANIMATION_UNSUPPORTED")
            width, height = opened.size
            image_format = opened.format
            opened.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageInputInvalid("IMAGE_MEDIA_INVALID") from exc
    mime = MIME_BY_FORMAT.get(image_format or "")
    if (
        mime not in ALLOWED_IMAGE_MIMES
        or width < 1
        or height < 1
        or width * height > settings.IMAGE_MAX_PIXELS
        or (claimed_mime and claimed_mime.split(";", 1)[0].lower() != mime)
    ):
        raise ImageInputInvalid("IMAGE_MEDIA_INVALID")
    return width, height, mime


def _object_bytes(key: str) -> bytes:
    try:
        with storage_provider().open_object(key) as source:
            data = source.read(settings.IMAGE_MAX_BYTES + 1)
    except FileStorageUnavailable as exc:
        raise ImageStorageUnavailable from exc
    if len(data) > settings.IMAGE_MAX_BYTES:
        raise ImageInputInvalid("IMAGE_REFERENCE_TOO_LARGE")
    return data


def _reference_data_url(job: ImageGenerationJob) -> str | None:
    if job.reference_asset_id:
        assert job.reference_asset is not None
        data = _object_bytes(job.reference_asset.object_key)
        _, _, mime = _validated_image(data, job.reference_asset.mime_type)
    elif job.reference_document_version_id:
        assert job.reference_document_version is not None
        data = _object_bytes(job.reference_document_version.object_key)
        _, _, mime = _validated_image(data, job.reference_document_version.detected_mime)
    elif job.reference_url:
        try:
            fetched = fetch_binary_url(
                job.reference_url,
                allowed_media_types=ALLOWED_IMAGE_MIMES,
                max_response_bytes=settings.IMAGE_MAX_BYTES,
            )
        except WebSourceError as exc:
            raise ImageInputInvalid("IMAGE_REFERENCE_FETCH_FAILED") from exc
        data = fetched.body
        _, _, mime = _validated_image(data, fetched.content_type)
    else:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _styled_prompt(job: ImageGenerationJob) -> str:
    template = str(job.style_snapshot.get("prompt_template", "{prompt}"))
    value = (
        template.replace("{prompt}", job.prompt)
        if "{prompt}" in template
        else f"{template}\n{job.prompt}"
    )
    return value[: settings.IMAGE_PROMPT_MAX_LENGTH]


def _provider_image(job: ImageGenerationJob):
    try:
        binding = capability_credential_snapshot(
            provider_key=job.provider_key,
            capability=AIModelCapability.IMAGE_GENERATION,
        )
    except (AICredentialStateConflict, AICredentialCryptoFailure) as exc:
        raise ImageCredentialUnavailable from exc
    if (
        binding.binding_id != str(job.credential_binding_id)
        or binding.binding_version != job.credential_binding_version
        or binding.credential_id != str(job.credential_id)
        or binding.credential_version != job.credential_version
    ):
        raise ImageCredentialUnavailable("IMAGE_CREDENTIAL_PROVENANCE_CHANGED")
    adapter = model_registry.resolve(
        provider_key=job.provider_key,
        model_key="doubao",
        capability=AIModelCapability.IMAGE_GENERATION,
    )
    size = job.size_snapshot.get("provider_params", {}).get("size")
    if size is not None and (not isinstance(size, str) or len(size) > 64):
        raise ImageInputInvalid("IMAGE_PROVIDER_SIZE_INVALID")
    return adapter.invoke(
        AIAdapterRequest(
            request_id=str(job.request_id),
            correlation_id=str(job.pk),
            identity=adapter.descriptor.identity,
            capability=AIModelCapability.IMAGE_GENERATION,
            adapter_version=job.adapter_version,
            prompt_version=job.prompt_version,
            timeout_seconds=job.timeout_seconds,
            payload=ImageGenerationPayload(
                provider_model_id=job.provider_model_id,
                prompt=_styled_prompt(job),
                reference_image=_reference_data_url(job),
                size=size,
                output_format="png",
            ),
        )
    )


def _artifact_bytes(artifact) -> tuple[bytes, str | None]:
    if artifact.b64_json is not None:
        if len(artifact.b64_json) > settings.IMAGE_MAX_BYTES * 2:
            raise ImageInputInvalid("IMAGE_PROVIDER_RESPONSE_INVALID")
        try:
            return base64.b64decode(artifact.b64_json, validate=True), None
        except (ValueError, TypeError) as exc:
            raise ImageInputInvalid("IMAGE_PROVIDER_RESPONSE_INVALID") from exc
    try:
        fetched = fetch_binary_url(
            artifact.url,
            allowed_media_types=ALLOWED_IMAGE_MIMES,
            max_response_bytes=settings.IMAGE_MAX_BYTES,
        )
    except WebSourceError as exc:
        raise ImageStorageUnavailable("IMAGE_PROVIDER_DOWNLOAD_FAILED") from exc
    return fetched.body, fetched.content_type


def generate_internal_video_first_frame(
    *,
    prompt: str,
    aspect_ratio: str,
    request_id,
    correlation_id,
) -> tuple[bytes, str, str]:
    """Generate an internal video first frame without creating or charging an image job."""

    if aspect_ratio not in {"9:16", "16:9"}:
        raise ImageInputInvalid("IMAGE_VIDEO_ASPECT_INVALID")
    clean_prompt = prompt.strip()
    if not clean_prompt or len(clean_prompt) > 1500:
        raise ImageInputInvalid("IMAGE_VIDEO_PROMPT_INVALID")
    runtime, _binding = _runtime_and_binding()
    adapter = model_registry.resolve(
        provider_key=runtime.provider_key,
        model_key=runtime.model_key,
        capability=AIModelCapability.IMAGE_GENERATION,
    )
    response = adapter.invoke(
        AIAdapterRequest(
            request_id=str(request_id),
            correlation_id=str(correlation_id),
            identity=adapter.descriptor.identity,
            capability=AIModelCapability.IMAGE_GENERATION,
            adapter_version=adapter.descriptor.adapter_version,
            prompt_version="geo-video-first-frame-v1",
            timeout_seconds=runtime.timeout_seconds,
            payload=ImageGenerationPayload(
                provider_model_id=runtime.provider_model_id,
                prompt=(
                    "为以下短视频生成一张无文字、构图清晰、适合动画延展的首帧图片：\n"
                    f"{clean_prompt}"
                ),
                size="1440x2560" if aspect_ratio == "9:16" else "2560x1440",
                output_format="jpeg",
            ),
        )
    )
    raw, _claimed_mime = _artifact_bytes(response.output.artifacts[0])
    return raw, runtime.provider_key, runtime.provider_model_id


def _settle(job: ImageGenerationJob, action: str) -> None:
    operation = consume_hold if action == "consume" else release_hold
    operation(
        hold_id=job.quota_hold_id,
        amount=1,
        idempotency_key=f"image-{action}-{job.pk}",
        request_id=job.request_id,
    )


def _discard_uncommitted_object(object_key: str | None) -> None:
    if not object_key:
        return
    try:
        storage_provider().delete_temporary_object(object_key)
    except (FileStorageUnavailable, AttributeError):
        pass


@transaction.atomic
def _terminal_failure(job_id, code: str) -> dict[str, str]:
    job = ImageGenerationJob.objects.select_for_update().get(pk=job_id)
    if job.status in {ImageGenerationJob.Status.SUCCEEDED, ImageGenerationJob.Status.FAILED}:
        return {"status": job.status}
    _settle(job, "release")
    job.status = ImageGenerationJob.Status.FAILED
    job.safe_error_code = code[:100]
    job.finished_at = timezone.now()
    job.next_attempt_at = None
    job.save(
        update_fields=(
            "status",
            "safe_error_code",
            "finished_at",
            "next_attempt_at",
            "updated_at",
        )
    )
    if code in SENSITIVE_FAILURES:
        ImageModerationReview.objects.create(
            job=job,
            source=ImageModerationReview.Source.PROVIDER,
            decision=ImageModerationReview.Decision.REJECTED,
            risk_categories=[SENSITIVE_FAILURES[code]],
            responsibility="provider_policy",
            quota_released=True,
        )
    return {"status": "failed"}


@transaction.atomic
def _retry_wait(job_id, code: str) -> dict[str, Any]:
    job = ImageGenerationJob.objects.select_for_update().get(pk=job_id)
    if job.status != ImageGenerationJob.Status.RUNNING:
        return {"status": job.status}
    if job.attempt_count > job.max_retries:
        transaction.set_rollback(True)
        return {"status": "retry_exhausted", "code": code}
    delay = min(3600, job.retry_base_seconds * (2 ** (job.attempt_count - 1)))
    job.status = ImageGenerationJob.Status.RETRY_WAIT
    job.safe_error_code = code[:100]
    job.next_attempt_at = timezone.now() + timedelta(seconds=delay)
    job.save(update_fields=("status", "safe_error_code", "next_attempt_at", "updated_at"))
    return {"status": "retry_wait", "retry_after": delay}


def execute_image_job(*, job_id) -> dict[str, Any]:
    with transaction.atomic():
        job = (
            ImageGenerationJob.objects.select_for_update(of=("self",))
            .select_related(
                "runtime_config",
                "reference_asset",
                "reference_document_version",
                "subject",
                "article",
            )
            .get(pk=job_id)
        )
        if job.status in {"succeeded", "failed", "running"}:
            return {"status": job.status}
        if (
            job.status == "retry_wait"
            and job.next_attempt_at
            and job.next_attempt_at > timezone.now()
        ):
            return {"status": "retry_wait"}
        job.status = ImageGenerationJob.Status.RUNNING
        job.attempt_count += 1
        job.started_at = job.started_at or timezone.now()
        job.safe_error_code = ""
        job.next_attempt_at = None
        job.save(
            update_fields=(
                "status",
                "attempt_count",
                "started_at",
                "safe_error_code",
                "next_attempt_at",
                "updated_at",
            )
        )
    object_key: str | None = None
    try:
        response = _provider_image(job)
        artifact = response.output.artifacts[0]
        data, claimed_mime = _artifact_bytes(artifact)
        width, height, mime = _validated_image(data, claimed_mime)
        digest = hashlib.sha256(data).hexdigest()
        extension = EXTENSION_BY_MIME[mime]
        image_id = uuid.uuid4()
        object_key = (
            f"users/{job.user_id}/subjects/{job.subject_id}/images/"
            f"{image_id.hex}/original.{extension}"
        )
        provider = storage_provider()
        provider.put_system_object(key=object_key, data=data, content_type=mime)
        metadata = provider.head_object(object_key)
        if (
            metadata.size != len(data)
            or metadata.content_type != mime
            or metadata.metadata.get("sha256") != digest
        ):
            raise ImageStorageUnavailable("IMAGE_STORAGE_VERIFICATION_FAILED")
        with transaction.atomic():
            locked = ImageGenerationJob.objects.select_for_update().get(pk=job.pk)
            if locked.status != ImageGenerationJob.Status.RUNNING:
                _discard_uncommitted_object(object_key)
                return {"status": locked.status}
            asset = ImageAsset.objects.create(
                id=image_id,
                user=locked.user,
                subject=locked.subject,
                article=locked.article,
                generation_job=locked,
                source_image_id=locked.reference_asset_id,
                source_type=(
                    ImageAsset.SourceType.DERIVATIVE
                    if locked.reference_asset_id
                    else ImageAsset.SourceType.GENERATED
                ),
                role=locked.role,
                object_key=object_key,
                width=width,
                height=height,
                mime_type=mime,
                size_bytes=len(data),
                sha256=digest,
                provider_key=locked.provider_key,
                provider_model_id=locked.provider_model_id,
                generation_capability=AIModelCapability.IMAGE_GENERATION.value,
                adapter_version=locked.adapter_version,
                prompt_digest=locked.prompt_digest,
                source_provenance=locked.reference_snapshot,
                moderation_status=ImageAsset.ModerationStatus.APPROVED,
                generated_at=timezone.now(),
                available_at=timezone.now(),
            )
            output_digest = digest_json(
                {
                    "image_id": str(asset.pk),
                    "sha256": digest,
                    "width": width,
                    "height": height,
                    "mime_type": mime,
                    "provider_model_id": response.output.provider_model_id,
                }
            )
            ImageGenerationResult.objects.create(
                job=locked,
                image=asset,
                provider_model_id=response.output.provider_model_id,
                provider_created=response.output.created,
                provider_size=artifact.size or "",
                output_digest=output_digest,
                safe_metadata={
                    "schema_version": IMAGE_SCHEMA_VERSION,
                    "image_count": response.output.image_count,
                    "latency_ms": response.timing.latency_ms,
                },
            )
            ImageModerationReview.objects.create(
                job=locked,
                image=asset,
                source=ImageModerationReview.Source.PROVIDER,
                decision=ImageModerationReview.Decision.APPROVED,
                responsibility="provider_policy",
                quota_released=False,
            )
            if locked.reference_asset_id:
                ImageDerivative.objects.create(
                    source_image_id=locked.reference_asset_id,
                    user=locked.user,
                    kind=ImageDerivative.Kind.AI_EDIT,
                    object_key=object_key,
                    width=width,
                    height=height,
                    mime_type=mime,
                    size_bytes=len(data),
                    sha256=digest,
                    ai_used=True,
                    parameters={
                        "generation_job_id": str(locked.pk),
                        "prompt_digest": locked.prompt_digest,
                        "size_preset_id": str(locked.size_preset_id),
                        "style_preset_id": str(locked.style_preset_id),
                        "quota_units": 1,
                    },
                )
            _settle(locked, "consume")
            locked.status = ImageGenerationJob.Status.SUCCEEDED
            locked.provider_request_id = response.provider_request_id or ""
            locked.normalized_usage = {
                "request_count": response.usage.request_count,
                "image_count": response.output.image_count,
                "provider_usage": dict(response.output.provider_usage),
            }
            locked.finished_at = timezone.now()
            locked.save(
                update_fields=(
                    "status",
                    "provider_request_id",
                    "normalized_usage",
                    "finished_at",
                    "updated_at",
                )
            )
        return {"status": "succeeded", "image_id": str(asset.pk)}
    except AIAdapterError as exc:
        _discard_uncommitted_object(object_key)
        if exc.retryable:
            retry = _retry_wait(job.pk, exc.stable_code)
            if retry["status"] == "retry_wait":
                return retry
        return _terminal_failure(job.pk, exc.stable_code)
    except ImageBusinessError as exc:
        _discard_uncommitted_object(object_key)
        return _terminal_failure(job.pk, exc.code)
    except Exception:
        _discard_uncommitted_object(object_key)
        return _terminal_failure(job.pk, "IMAGE_INTERNAL_FAILURE")


def image_job_for_user(*, user, job_id) -> ImageGenerationJob:
    try:
        return ImageGenerationJob.objects.select_related("result_asset", "quota_hold").get(
            pk=job_id, user=user
        )
    except ImageGenerationJob.DoesNotExist as exc:
        raise Http404 from exc


def image_for_user(*, user, image_id, include_trashed=False, lock=False) -> ImageAsset:
    query = ImageAsset.objects.filter(user=user)
    if not include_trashed:
        query = query.filter(lifecycle_status="active")
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.select_related("subject", "article").get(pk=image_id)
    except ImageAsset.DoesNotExist as exc:
        raise Http404 from exc


def _content_url(image: ImageAsset) -> str:
    """Return an authenticated same-origin URL, never an internal S3 endpoint."""

    return f"/api/v1/subjects/{image.subject_id}/images/{image.pk}/content"


def image_payload(image: ImageAsset, *, include_url=True) -> dict[str, Any]:
    return {
        "id": str(image.pk),
        "subject_id": str(image.subject_id),
        "article_id": str(image.article_id) if image.article_id else None,
        "job_id": str(image.generation_job_id) if image.generation_job_id else None,
        "role": image.role,
        "source_type": image.source_type,
        "width": image.width,
        "height": image.height,
        "mime_type": image.mime_type,
        "size_bytes": image.size_bytes,
        "sha256": image.sha256,
        "provider": image.provider_key,
        "provider_model": image.provider_model_id,
        "generation_capability": image.generation_capability,
        "adapter_version": image.adapter_version,
        "version": image.version,
        "moderation_status": image.moderation_status,
        "is_subject_library": image.is_subject_library,
        "lifecycle_status": image.lifecycle_status,
        "url": _content_url(image) if include_url and image.lifecycle_status == "active" else None,
        "url_expires_in": None,
        "generated_at": image.generated_at,
        "available_at": image.available_at,
        "created_at": image.created_at,
    }


def job_payload(job: ImageGenerationJob) -> dict[str, Any]:
    asset = getattr(job, "result_asset", None)
    return {
        "id": str(job.pk),
        "subject_id": str(job.subject_id),
        "article_id": str(job.article_id) if job.article_id else None,
        "generation_type": job.generation_type,
        "role": job.role,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "max_retries": job.max_retries,
        "safe_error_code": job.safe_error_code,
        "provider": job.provider_key,
        "provider_model": job.provider_model_id,
        "runtime_version": job.runtime_version,
        "adapter_version": job.adapter_version,
        "prompt_version": job.prompt_version,
        "quota_status": job.quota_hold.status,
        "image": image_payload(asset) if asset else None,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


@transaction.atomic
def save_to_library(*, user, image_id, expected_version):
    image = image_for_user(user=user, image_id=image_id, lock=True)
    if image.version != expected_version:
        raise ImageBusinessError("IMAGE_VERSION_CONFLICT")
    if image.moderation_status != "approved":
        raise ImageBusinessError("IMAGE_MODERATION_BLOCKED")
    image.is_subject_library = True
    image.version += 1
    image.save(update_fields=("is_subject_library", "version", "updated_at"))
    return image


@transaction.atomic
def attach_to_article(*, user, image_id, article_id, expected_version):
    image = image_for_user(user=user, image_id=image_id, lock=True)
    article = _article(user, article_id, image.subject, lock=True)
    if image.version != expected_version:
        raise ImageBusinessError("IMAGE_VERSION_CONFLICT")
    if image.moderation_status != "approved":
        raise ImageBusinessError("IMAGE_MODERATION_BLOCKED")
    image.article = article
    image.version += 1
    image.save(update_fields=("article", "version", "updated_at"))
    return image


@transaction.atomic
def trash_image(*, user, image_id, expected_version):
    image = image_for_user(user=user, image_id=image_id, lock=True)
    if image.version != expected_version:
        raise ImageBusinessError("IMAGE_VERSION_CONFLICT")
    image.lifecycle_status = ImageAsset.LifecycleStatus.TRASHED
    image.deleted_at = timezone.now()
    image.version += 1
    image.save(update_fields=("lifecycle_status", "deleted_at", "version", "updated_at"))
    return image


@transaction.atomic
def restore_image(*, user, image_id, expected_version):
    image = image_for_user(user=user, image_id=image_id, include_trashed=True, lock=True)
    if image.version != expected_version or image.lifecycle_status != "trashed":
        raise ImageBusinessError("IMAGE_VERSION_CONFLICT")
    image.lifecycle_status = ImageAsset.LifecycleStatus.ACTIVE
    image.deleted_at = None
    image.version += 1
    image.save(update_fields=("lifecycle_status", "deleted_at", "version", "updated_at"))
    return image


@transaction.atomic
def request_moderation_appeal(*, user, image_id, note):
    image = image_for_user(user=user, image_id=image_id, lock=True)
    if image.generation_job is None:
        raise ImageBusinessError("IMAGE_MODERATION_APPEAL_UNAVAILABLE")
    if ImageModerationReview.objects.filter(image=image, appeal_no=1).exists():
        raise ImageBusinessError("IMAGE_MODERATION_APPEAL_ALREADY_USED")
    review = ImageModerationReview.objects.create(
        job=image.generation_job,
        image=image,
        source=ImageModerationReview.Source.MANUAL,
        decision=ImageModerationReview.Decision.APPEAL_REQUESTED,
        responsibility="pending_manual_review",
        quota_released=False,
        appeal_no=1,
        actor=user,
        note=note.strip()[:1000],
    )
    image.moderation_status = ImageAsset.ModerationStatus.SUSPECTED
    image.version += 1
    image.save(update_fields=("moderation_status", "version", "updated_at"))
    return review


def _render_derivative(image: ImageAsset, *, width, height, output_format, kind):
    if not 1 <= width <= 8192 or not 1 <= height <= 8192:
        raise ImageInputInvalid("IMAGE_DERIVATIVE_SIZE_INVALID")
    data = _object_bytes(image.object_key)
    try:
        with Image.open(io.BytesIO(data)) as opened:
            converted = ImageOps.fit(opened.convert("RGB"), (width, height))
            output = io.BytesIO()
            format_name = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[output_format]
            save_args = {"quality": 88, "optimize": True} if format_name != "PNG" else {}
            converted.save(output, format=format_name, **save_args)
    except (UnidentifiedImageError, OSError, KeyError) as exc:
        raise ImageInputInvalid("IMAGE_DERIVATIVE_INVALID") from exc
    result = output.getvalue()
    _, _, mime = _validated_image(result)
    return result, mime


def create_ai_derivative_job(
    *,
    user,
    image_id,
    prompt,
    size_preset_id,
    style_preset_id,
    idempotency_key,
    request_id,
):
    image = image_for_user(user=user, image_id=image_id)
    if image.moderation_status != ImageAsset.ModerationStatus.APPROVED:
        raise ImageBusinessError("IMAGE_MODERATION_BLOCKED")
    return create_image_job(
        user=user,
        subject_id=image.subject_id,
        article_id=image.article_id,
        role=ImageGenerationJob.Role.CHANNEL,
        prompt=prompt,
        size_preset_id=size_preset_id,
        style_preset_id=style_preset_id,
        reference_asset_id=image.pk,
        reference_document_version_id=None,
        reference_url="",
        idempotency_key=idempotency_key,
        request_id=request_id,
    )


def create_derivative(*, user, image_id, kind, width, height, output_format):
    image = image_for_user(user=user, image_id=image_id)
    if image.moderation_status != "approved":
        raise ImageBusinessError("IMAGE_MODERATION_BLOCKED")
    if kind not in ImageDerivative.Kind.values or output_format not in {"png", "jpeg", "webp"}:
        raise ImageInputInvalid("IMAGE_DERIVATIVE_INVALID")
    data, mime = _render_derivative(
        image, width=width, height=height, output_format=output_format, kind=kind
    )
    derivative_id = uuid.uuid4()
    extension = EXTENSION_BY_MIME[mime]
    key = (
        f"users/{image.user_id}/subjects/{image.subject_id}/images/"
        f"{image.pk.hex}/derivatives/{derivative_id.hex}.{extension}"
    )
    try:
        provider = storage_provider()
        provider.put_system_object(key=key, data=data, content_type=mime)
        metadata = provider.head_object(key)
        if (
            metadata.size != len(data)
            or metadata.content_type != mime
            or metadata.metadata.get("sha256") != hashlib.sha256(data).hexdigest()
        ):
            raise ImageStorageUnavailable("IMAGE_STORAGE_VERIFICATION_FAILED")
    except FileStorageUnavailable as exc:
        _discard_uncommitted_object(key)
        raise ImageStorageUnavailable from exc
    except ImageStorageUnavailable:
        _discard_uncommitted_object(key)
        raise
    try:
        return ImageDerivative.objects.create(
            id=derivative_id,
            source_image=image,
            user=user,
            kind=kind,
            object_key=key,
            width=width,
            height=height,
            mime_type=mime,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            ai_used=False,
            parameters={"width": width, "height": height, "output_format": output_format},
        )
    except Exception:
        _discard_uncommitted_object(key)
        raise


def derivative_payload(row: ImageDerivative) -> dict[str, Any]:
    try:
        url = storage_provider().create_download_url(
            key=row.object_key,
            filename=f"image-{row.pk}.{EXTENSION_BY_MIME[row.mime_type]}",
            content_type=row.mime_type,
        )
    except FileStorageUnavailable:
        url = None
    return {
        "id": str(row.pk),
        "source_image_id": str(row.source_image_id),
        "kind": row.kind,
        "width": row.width,
        "height": row.height,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "ai_used": row.ai_used,
        "url": url,
        "url_expires_in": settings.FILE_DOWNLOAD_URL_TTL,
        "created_at": row.created_at,
    }


def create_batch_download(*, user, subject_id, image_ids):
    subject = _subject(user, subject_id)
    rows = list(
        ImageAsset.objects.filter(
            pk__in=image_ids,
            user=user,
            subject=subject,
            lifecycle_status="active",
            moderation_status="approved",
        ).order_by("id")
    )
    if not rows or len(rows) != len(set(image_ids)) or len(rows) > 100:
        raise ImageInputInvalid("IMAGE_BATCH_SELECTION_INVALID")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for image in rows:
            archive.writestr(
                f"original/{image.pk}.{EXTENSION_BY_MIME[image.mime_type]}",
                _object_bytes(image.object_key),
            )
            for derivative in image.derivatives.filter(ai_used=False).order_by("created_at", "id"):
                archive.writestr(
                    (
                        f"derivatives/{image.pk}/{derivative.kind}-{derivative.pk}."
                        f"{EXTENSION_BY_MIME[derivative.mime_type]}"
                    ),
                    _object_bytes(derivative.object_key),
                )
    data = output.getvalue()
    batch_id = uuid.uuid4()
    key = f"users/{user.pk}/subjects/{subject.pk}/images/downloads/{batch_id.hex}.zip"
    try:
        provider = storage_provider()
        provider.put_system_object(key=key, data=data, content_type="application/zip")
        url = provider.create_download_url(
            key=key, filename=f"images-{batch_id}.zip", content_type="application/zip"
        )
    except FileStorageUnavailable as exc:
        raise ImageStorageUnavailable from exc
    record = ImageBatchDownload.objects.create(
        id=batch_id,
        user=user,
        subject=subject,
        object_key=key,
        image_count=len(rows),
        content_digest=hashlib.sha256(data).hexdigest(),
        expires_at=timezone.now() + timedelta(seconds=settings.IMAGE_BATCH_RETENTION_SECONDS),
    )
    return record, url


def recommendations(*, user, article_id):
    try:
        article = Article.objects.select_related("subject").get(pk=article_id, user=user)
    except Article.DoesNotExist as exc:
        raise Http404 from exc
    sizes = list(ImageSizePreset.objects.filter(status="active").order_by("sort_order", "key"))
    styles = list(ImageStylePreset.objects.filter(status="active").order_by("sort_order", "key"))
    if not sizes or not styles:
        raise ImageRuntimeUnavailable("IMAGE_PRESETS_UNAVAILABLE")
    topic = article.title.strip() or article.content[:100].strip() or "主体内容"
    return {
        "article_id": str(article.pk),
        "recommendations": [
            {
                "position": "cover",
                "role": "cover",
                "purpose": "文章封面",
                "prompt": f"为《{topic[:120]}》生成专业、清晰、与主体一致的文章封面",
                "size_preset_id": str(sizes[0].pk),
                "style_preset_id": str(styles[0].pk),
                "requires_confirmation": True,
            },
            {
                "position": "body_after_intro",
                "role": "illustration",
                "purpose": "正文插图",
                "prompt": f"围绕《{topic[:120]}》生成信息准确、不过度承诺的正文插图",
                "size_preset_id": str(sizes[min(1, len(sizes) - 1)].pk),
                "style_preset_id": str(styles[0].pk),
                "requires_confirmation": True,
            },
        ],
    }


def quota_summary(user) -> dict[str, int | bool]:
    if user.is_test_account:
        return {"available": 0, "frozen": 0, "consumed": 0, "unlimited": True}
    subscription = current_subscription(user)
    if subscription is None:
        return {"available": 0, "frozen": 0, "consumed": 0, "unlimited": False}
    account = QuotaAccount.objects.filter(
        subscription=subscription,
        quota_type__in=("image_generations", "image_credits"),
        batch_type=QuotaAccount.BatchType.PRIMARY,
        cycle_started_at__isnull=True,
    ).first()
    if account is None:
        return {"available": 0, "frozen": 0, "consumed": 0, "unlimited": False}
    return {
        "available": account.available,
        "frozen": account.frozen,
        "consumed": max(0, account.entitlement_amount - account.available - account.frozen),
        "unlimited": False,
    }
