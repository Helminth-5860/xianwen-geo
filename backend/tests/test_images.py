from __future__ import annotations

import base64
import io
import uuid
import zipfile
from dataclasses import dataclass
from unittest.mock import patch

import httpx
import pytest
from django.core.management import call_command
from django.http import Http404
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.ai.adapters.doubao_image import (
    DOUBAO_IMAGE_ADAPTER_VERSION,
    DOUBAO_IMAGE_DESCRIPTOR,
    DOUBAO_IMAGE_PROMPT_VERSION,
    DoubaoImageGenerationAdapter,
)
from apps.ai.contracts import (
    AdapterCredential,
    AIAdapterRequest,
    AIAdapterResponse,
    AIAdapterTiming,
    AIFinishReason,
    AIModelCapability,
    AIUsage,
)
from apps.ai.credential_crypto import encrypt_secret, mask_secret
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.image_generation import (
    ImageGenerationArtifact,
    ImageGenerationOutput,
    ImageGenerationPayload,
)
from apps.ai.models import (
    AICapabilityRuntimeConfig,
    AIProvider,
    APICredential,
    APICredentialCapabilityBinding,
)
from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.storage import MockStorageProvider
from apps.images.exceptions import ImageCredentialUnavailable, ImageRuntimeUnavailable
from apps.images.models import (
    ImageAsset,
    ImageDerivative,
    ImageGenerationJob,
    ImageGenerationResult,
    ImageSizePreset,
    ImageStylePreset,
)
from apps.images.services import (
    create_ai_derivative_job,
    create_batch_download,
    create_derivative,
    create_image_job,
    execute_image_job,
    image_for_user,
)
from apps.quotas.models import QuotaAccount
from apps.users.models import User
from apps.web_sources.http_transport import FetchResult
from tests import test_keyword_generation as keyword_tests

pytestmark = pytest.mark.django_db


def _png_bytes(color=(42, 98, 180)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def image_facts(monkeypatch):
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)
    original_limits = keyword_tests._limits

    def image_limits(*args, **kwargs):
        values = original_limits(*args, **kwargs)
        values["image_generations"] = 5
        return values

    monkeypatch.setattr(keyword_tests, "_limits", image_limits)
    user, subject, _, subscription = keyword_tests._facts()
    subject.status = subject.Status.ACTIVE
    subject.version += 1
    subject.save(update_fields=("status", "version", "updated_at"))
    provider = AIProvider.objects.get(provider_key="doubao")
    model = provider.models.get(model_key="doubao")
    runtime, _ = AICapabilityRuntimeConfig.objects.get_or_create(
        model=model, capability=AIModelCapability.IMAGE_GENERATION.value
    )
    runtime.provider_model_id = "doubao-seedream-5-0-260128"
    runtime.api_version = "2024-01-01"
    runtime.enabled = True
    runtime.max_retries = 1
    runtime.retry_base_seconds = 1
    runtime.version += 1
    runtime.save()
    credential = APICredential.objects.create(
        provider=provider,
        environment="staging",
        secret_reference=encrypt_secret("stage-image-api-key"),
        secret_mask=mask_secret("stage-image-api-key"),
        version_no=1,
        status=APICredential.Status.ACTIVE,
        created_by=user,
    )
    binding = APICredentialCapabilityBinding.objects.create(
        provider=provider,
        capability=AIModelCapability.IMAGE_GENERATION.value,
        environment="staging",
        enabled=True,
        updated_by=user,
    )
    ImageSizePreset.objects.get_or_create(
        key="square_1_1",
        defaults={
            "name": "方图 1:1",
            "aspect_ratio": "1:1",
            "width": 2048,
            "height": 2048,
            "provider_params": {"size": "2048x2048"},
        },
    )
    ImageStylePreset.objects.get_or_create(
        key="natural",
        defaults={
            "name": "自然专业",
            "description": "测试使用的数据库版本化图片风格。",
            "prompt_template": "自然、专业、真实的商业视觉。{prompt}",
        },
    )
    MockStorageProvider.clear()
    return user, subject, subscription, runtime, credential, binding


class StubImageAdapter:
    descriptor = DOUBAO_IMAGE_DESCRIPTOR

    def __init__(self, *, artifact=None, error: AIAdapterError | None = None):
        self.artifact = artifact or ImageGenerationArtifact(
            None, base64.b64encode(_png_bytes()).decode(), "32x24"
        )
        self.error = error
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return AIAdapterResponse(
            request_id=request.request_id,
            identity=self.descriptor.identity,
            provider_request_id="provider-request-safe",
            output=ImageGenerationOutput(
                request.payload.provider_model_id, 1_750_000_000, (self.artifact,), 1
            ),
            usage=AIUsage(request_count=1),
            timing=AIAdapterTiming(latency_ms=12),
            finish_reason=AIFinishReason.STOP,
        )


def _create_job(user, subject, *, key=None, reference_asset_id=None):
    return create_image_job(
        user=user,
        subject_id=subject.pk,
        article_id=None,
        role="cover",
        prompt="专业品牌文章封面，构图清晰",
        size_preset_id=ImageSizePreset.objects.first().pk,
        style_preset_id=ImageStylePreset.objects.first().pk,
        reference_asset_id=reference_asset_id,
        reference_document_version_id=None,
        reference_url="",
        idempotency_key=key or f"image-{uuid.uuid4()}",
        request_id=uuid.uuid4(),
    )


def test_text_to_image_persists_private_asset_then_consumes_once(image_facts):
    user, subject, subscription, runtime, credential, binding = image_facts
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="image_generations")
    initial = account.available
    adapter = StubImageAdapter()
    with patch("apps.images.services.model_registry.resolve", return_value=adapter):
        job, created = _create_job(user, subject, key="image-idempotent-success-0001")
        replay, replay_created = _create_job(user, subject, key="image-idempotent-success-0001")
        assert execute_image_job(job_id=job.pk)["status"] == "succeeded"
        assert execute_image_job(job_id=job.pk)["status"] == "succeeded"

    assert created is True and replay_created is False and replay.pk == job.pk
    assert len(adapter.requests) == 1
    job.refresh_from_db()
    account.refresh_from_db()
    asset = ImageAsset.objects.get(generation_job=job)
    assert job.provider_model_id == runtime.provider_model_id
    assert job.credential_id == credential.pk
    assert job.credential_binding_id == binding.pk
    assert job.status == "succeeded" and job.quota_hold.consumed_amount == 1
    assert account.available == initial - 1 and account.frozen == 0
    assert asset.object_key.startswith(f"users/{user.pk}/subjects/{subject.pk}/images/")
    assert asset.object_key.endswith("/original.png")
    assert asset.width == 32 and asset.height == 24 and asset.mime_type == "image/png"
    assert asset.sha256 and asset.provider_model_id == runtime.provider_model_id
    assert asset.prompt_digest == job.prompt_digest
    assert ImageGenerationResult.objects.filter(job=job, image=asset).count() == 1
    assert "stage-image-api-key" not in repr(job.__dict__)


def test_image_content_is_same_origin_and_subject_owner_scoped(image_facts):
    user, subject, _, _, _, _ = image_facts
    with patch("apps.images.services.model_registry.resolve", return_value=StubImageAdapter()):
        job, _ = _create_job(user, subject)
        assert execute_image_job(job_id=job.pk)["status"] == "succeeded"
    asset = ImageAsset.objects.get(generation_job=job)

    client = APIClient()
    client.force_authenticate(user=user)
    listing = client.get(f"/api/v1/subjects/{subject.pk}/images")
    assert listing.status_code == 200
    payload = listing.json()["data"]
    assert payload["quota"]["unlimited"] is False
    assert payload["results"][0]["url"] == (
        f"/api/v1/subjects/{subject.pk}/images/{asset.pk}/content"
    )
    assert payload["results"][0]["url_expires_in"] is None

    content = client.get(payload["results"][0]["url"])
    assert content.status_code == 200
    assert content["Content-Type"] == "image/png"
    assert content["Cache-Control"] == "private, no-store"
    assert content["X-Content-Type-Options"] == "nosniff"
    assert b"".join(content.streaming_content) == _png_bytes()

    assert (
        client.get(f"/api/v1/subjects/{uuid.uuid4()}/images/{asset.pk}/content").status_code == 404
    )
    other = User.objects.create_user(
        phone=f"136{uuid.uuid4().int % 100000000:08d}",
        nickname="other image content user",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
    )
    denied = APIClient()
    denied.force_authenticate(user=other)
    assert denied.get(f"/api/v1/subjects/{subject.pk}/images/{asset.pk}/content").status_code == 404


def test_test_account_image_quota_is_serialized_as_unlimited(image_facts):
    user, subject, _, _, _, _ = image_facts
    user.is_test_account = True
    user.save(update_fields=("is_test_account", "updated_at"))

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get(f"/api/v1/subjects/{subject.pk}/images")

    assert response.status_code == 200
    assert response.json()["data"]["quota"] == {
        "available": 0,
        "frozen": 0,
        "consumed": 0,
        "unlimited": True,
    }


def test_reference_image_uses_private_bytes_as_data_uri(image_facts):
    user, subject, _, _, _, _ = image_facts
    first_adapter = StubImageAdapter()
    with patch("apps.images.services.model_registry.resolve", return_value=first_adapter):
        first, _ = _create_job(user, subject)
        execute_image_job(job_id=first.pk)
    asset = ImageAsset.objects.get(generation_job=first)
    edit_adapter = StubImageAdapter()
    with patch("apps.images.services.model_registry.resolve", return_value=edit_adapter):
        edit, _ = _create_job(user, subject, reference_asset_id=asset.pk)
        assert execute_image_job(job_id=edit.pk)["status"] == "succeeded"
    payload = edit_adapter.requests[0].payload
    assert edit.generation_type == "edit"
    assert payload.reference_image.startswith("data:image/png;base64,")
    assert asset.object_key not in payload.reference_image


@pytest.mark.parametrize(
    ("category", "code"),
    [
        (AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE, "IMAGE_INPUT_TEXT_SENSITIVE"),
        (AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE, "IMAGE_OUTPUT_SENSITIVE"),
        (AIAdapterErrorCategory.TIMEOUT, "IMAGE_PROVIDER_TIMEOUT"),
    ],
)
def test_terminal_provider_and_moderation_failure_release_quota(image_facts, category, code):
    user, subject, subscription, _, _, _ = image_facts
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="image_generations")
    initial = account.available
    adapter = StubImageAdapter(error=AIAdapterError(category, stable_code=code, retryable=False))
    with patch("apps.images.services.model_registry.resolve", return_value=adapter):
        job, _ = _create_job(user, subject)
        assert execute_image_job(job_id=job.pk)["status"] == "failed"
    job.refresh_from_db()
    account.refresh_from_db()
    assert job.safe_error_code == code
    assert job.quota_hold.released_amount == 1
    assert account.available == initial and account.frozen == 0
    assert not ImageGenerationResult.objects.filter(job=job).exists()


def test_provider_429_is_bounded_and_releases_after_retry_exhaustion(image_facts):
    user, subject, subscription, _, _, _ = image_facts
    adapter = StubImageAdapter(
        error=AIAdapterError(
            AIAdapterErrorCategory.RATE_LIMIT,
            stable_code="IMAGE_PROVIDER_RATE_LIMIT",
            retryable=True,
        )
    )
    with patch("apps.images.services.model_registry.resolve", return_value=adapter):
        job, _ = _create_job(user, subject)
        assert execute_image_job(job_id=job.pk)["status"] == "retry_wait"
        ImageGenerationJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
        assert execute_image_job(job_id=job.pk)["status"] == "failed"
    job.refresh_from_db()
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="image_generations")
    assert len(adapter.requests) == 2
    assert job.attempt_count == 2 and job.quota_hold.released_amount == 1
    assert account.frozen == 0


def test_storage_failure_releases_and_creates_no_available_asset(image_facts):
    user, subject, subscription, _, _, _ = image_facts
    adapter = StubImageAdapter()

    class BrokenStorage:
        def put_system_object(self, **kwargs):
            raise FileStorageUnavailable

    with (
        patch("apps.images.services.model_registry.resolve", return_value=adapter),
        patch("apps.images.services.storage_provider", return_value=BrokenStorage()),
    ):
        job, _ = _create_job(user, subject)
        assert execute_image_job(job_id=job.pk)["status"] == "failed"
    job.refresh_from_db()
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="image_generations")
    assert job.quota_hold.released_amount == 1 and account.frozen == 0
    assert not ImageAsset.objects.filter(generation_job=job).exists()


def test_runtime_and_credential_missing_fail_closed_before_hold(image_facts):
    user, subject, subscription, runtime, _, binding = image_facts
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="image_generations")
    initial = account.available
    runtime.enabled = False
    runtime.version += 1
    runtime.save()
    with pytest.raises(ImageRuntimeUnavailable):
        _create_job(user, subject)
    runtime.enabled = True
    runtime.version += 1
    runtime.save()
    binding.enabled = False
    binding.version += 1
    binding.save()
    with pytest.raises(ImageCredentialUnavailable):
        _create_job(user, subject)
    account.refresh_from_db()
    assert account.available == initial and account.frozen == 0


def test_ownership_free_derivative_and_private_zip(image_facts):
    user, subject, _, _, _, _ = image_facts
    adapter = StubImageAdapter()
    with patch("apps.images.services.model_registry.resolve", return_value=adapter):
        job, _ = _create_job(user, subject)
        execute_image_job(job_id=job.pk)
    asset = ImageAsset.objects.get(generation_job=job)
    other = User.objects.create_user(
        phone=f"137{uuid.uuid4().int % 100000000:08d}",
        nickname="other image user",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
    )
    with pytest.raises(Http404):
        image_for_user(user=other, image_id=asset.pk)
    derivative = create_derivative(
        user=user,
        image_id=asset.pk,
        kind="channel",
        width=1200,
        height=630,
        output_format="jpeg",
    )
    assert derivative.ai_used is False and derivative.mime_type == "image/jpeg"
    batch, url = create_batch_download(user=user, subject_id=subject.pk, image_ids=[asset.pk])
    assert batch.image_count == 1 and url.startswith("mock://download/")
    with MockStorageProvider().open_object(batch.object_key) as stored:
        with zipfile.ZipFile(stored) as archive:
            names = archive.namelist()
    assert any(name.startswith("original/") for name in names)
    assert any("derivatives/" in name and "channel-" in name for name in names)


def test_ai_reference_processing_uses_generation_job_and_bills_only_on_delivery(image_facts):
    user, subject, subscription, _, _, _ = image_facts
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="image_generations")
    initial = account.available
    adapter = StubImageAdapter()
    with patch("apps.images.services.model_registry.resolve", return_value=adapter):
        source_job, _ = _create_job(user, subject)
        assert execute_image_job(job_id=source_job.pk)["status"] == "succeeded"
        source = ImageAsset.objects.get(generation_job=source_job)
        size = ImageSizePreset.objects.first()
        style = ImageStylePreset.objects.first()
        job, created = create_ai_derivative_job(
            user=user,
            image_id=source.pk,
            prompt="基于参考图重构为横版渠道视觉，保持品牌主体一致",
            size_preset_id=size.pk,
            style_preset_id=style.pk,
            idempotency_key="ai-image-derivative-idempotency-0001",
            request_id=uuid.uuid4(),
        )
        assert created is True and job.generation_type == "edit"
        account.refresh_from_db()
        assert account.frozen == 1
        assert execute_image_job(job_id=job.pk)["status"] == "succeeded"

    result = ImageAsset.objects.get(generation_job=job)
    evidence = ImageDerivative.objects.get(object_key=result.object_key)
    account.refresh_from_db()
    assert result.source_image_id == source.pk and result.source_type == "derivative"
    assert evidence.source_image_id == source.pk and evidence.ai_used is True
    assert evidence.kind == ImageDerivative.Kind.AI_EDIT
    assert evidence.parameters["quota_units"] == 1
    assert account.frozen == 0 and account.available == initial - 2


@dataclass
class StaticCredentialResolver:
    value: str = "unit-test-key"

    def resolve(self, provider_key: str):
        assert provider_key == "doubao"
        return AdapterCredential(self.value)


def _adapter_request(provider_model_id="doubao-seedream-5-0-260128"):
    return AIAdapterRequest(
        request_id=str(uuid.uuid4()),
        correlation_id=None,
        identity=DOUBAO_IMAGE_DESCRIPTOR.identity,
        capability=AIModelCapability.IMAGE_GENERATION,
        adapter_version=DOUBAO_IMAGE_ADAPTER_VERSION,
        prompt_version=DOUBAO_IMAGE_PROMPT_VERSION,
        timeout_seconds=5,
        payload=ImageGenerationPayload(provider_model_id=provider_model_id, prompt="专业文章封面"),
    )


def test_doubao_adapter_normalizes_success_without_raw_provider_json():
    encoded = base64.b64encode(_png_bytes()).decode()

    def handler(request: httpx.Request):
        assert request.url.path == "/api/v3/images/generations"
        assert request.headers["Authorization"] == "Bearer unit-test-key"
        body = request.content.decode()
        assert '"stream":false' in body and '"watermark":true' in body
        return httpx.Response(
            200,
            headers={"x-request-id": "ark-safe-id"},
            json={
                "model": "doubao-seedream-5-0-260128",
                "created": 1_750_000_000,
                "data": [{"b64_json": encoded, "size": "32x24"}],
                "usage": {"generated_images": 1},
            },
        )

    adapter = DoubaoImageGenerationAdapter(
        credential_resolver=StaticCredentialResolver(), transport=httpx.MockTransport(handler)
    )
    result = adapter.invoke(_adapter_request())
    assert result.provider_request_id == "ark-safe-id"
    assert result.output.artifacts[0].b64_json == encoded
    assert result.sanitized_provider_metadata == {
        "api_version": "2024-01-01",
        "image_count": 1,
    }
    assert result.output.provider_usage == (("generated_images", 1),)
    assert 'usage": {' not in repr(result)


def test_doubao_adapter_accepts_documented_lite_response_model_alias():
    def handler(request: httpx.Request):
        assert '"model":"doubao-seedream-5-0-lite-260128"' in request.content.decode()
        return httpx.Response(
            200,
            json={
                "model": "doubao-seedream-5-0-260128",
                "created": 1_750_000_000,
                "data": [{"url": "https://provider.example/image.png", "size": "2048x2048"}],
                "usage": {"generated_images": 1},
            },
        )

    adapter = DoubaoImageGenerationAdapter(
        credential_resolver=StaticCredentialResolver(), transport=httpx.MockTransport(handler)
    )
    result = adapter.invoke(_adapter_request("doubao-seedream-5-0-lite-260128"))

    assert result.output.provider_model_id == "doubao-seedream-5-0-260128"


def test_doubao_adapter_rejects_unknown_response_model_alias():
    adapter = DoubaoImageGenerationAdapter(
        credential_resolver=StaticCredentialResolver(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "doubao-seedream-unknown",
                    "created": 1_750_000_000,
                    "data": [
                        {
                            "url": "https://provider.example/image.png",
                            "size": "2048x2048",
                        }
                    ],
                },
            )
        ),
    )

    with pytest.raises(AIAdapterError) as invalid:
        adapter.invoke(_adapter_request("doubao-seedream-5-0-lite-260128"))
    assert invalid.value.stable_code == "IMAGE_PROVIDER_RESPONSE_INVALID"


@pytest.mark.parametrize(
    ("status", "body", "code", "retryable"),
    [
        (
            400,
            {"error": {"code": "InputTextSensitiveContentDetected"}},
            "IMAGE_INPUT_TEXT_SENSITIVE",
            False,
        ),
        (
            400,
            {"error": {"code": "OutputImageSensitiveContentDetected"}},
            "IMAGE_OUTPUT_SENSITIVE",
            False,
        ),
        (429, {"error": {"code": "QuotaExceeded"}}, "IMAGE_PROVIDER_QUOTA_EXCEEDED", True),
        (429, {"error": {"code": "RateLimitExceeded"}}, "IMAGE_PROVIDER_RATE_LIMIT", True),
    ],
)
def test_doubao_adapter_maps_provider_errors(status, body, code, retryable):
    adapter = DoubaoImageGenerationAdapter(
        credential_resolver=StaticCredentialResolver(),
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body)),
    )
    with pytest.raises(AIAdapterError) as captured:
        adapter.invoke(_adapter_request())
    assert captured.value.stable_code == code
    assert captured.value.retryable is retryable


def test_doubao_adapter_rejects_timeout_and_malformed_response():
    timeout_adapter = DoubaoImageGenerationAdapter(
        credential_resolver=StaticCredentialResolver(),
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout"))
        ),
    )
    with pytest.raises(AIAdapterError, match="timed out") as timeout:
        timeout_adapter.invoke(_adapter_request())
    assert timeout.value.stable_code == "IMAGE_PROVIDER_TIMEOUT"

    malformed = DoubaoImageGenerationAdapter(
        credential_resolver=StaticCredentialResolver(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"model": "wrong", "data": []})
        ),
    )
    with pytest.raises(AIAdapterError) as invalid:
        malformed.invoke(_adapter_request())
    assert invalid.value.stable_code == "IMAGE_PROVIDER_RESPONSE_INVALID"


def test_provider_temporary_url_is_downloaded_then_private_persisted(image_facts):
    user, subject, _, _, _, _ = image_facts
    adapter = StubImageAdapter(
        artifact=ImageGenerationArtifact("https://provider.example/temporary.png", None, "32x24")
    )
    fetched = FetchResult(
        request_url="https://provider.example/temporary.png",
        final_url="https://provider.example/temporary.png",
        status=200,
        content_type="image/png",
        body=_png_bytes(),
        response_sha256="a" * 64,
        redirect_count=0,
        peer_ip="192.0.2.1",
    )
    with (
        patch("apps.images.services.model_registry.resolve", return_value=adapter),
        patch("apps.images.services.fetch_binary_url", return_value=fetched) as download,
    ):
        job, _ = _create_job(user, subject)
        assert execute_image_job(job_id=job.pk)["status"] == "succeeded"
    asset = ImageAsset.objects.get(generation_job=job)
    download.assert_called_once()
    assert "provider.example" not in asset.object_key
    assert MockStorageProvider().head_object(asset.object_key).size == len(_png_bytes())


def test_image_api_requires_owner_and_rejects_unsafe_reference_url(image_facts):
    user, subject, subscription, _, _, _ = image_facts
    from apps.images.models import ImageSizePreset, ImageStylePreset

    client = APIClient()
    client.force_authenticate(user=user)
    payload = {
        "article_id": None,
        "role": "cover",
        "prompt": "安全的文章封面",
        "size_preset_id": str(ImageSizePreset.objects.first().pk),
        "style_preset_id": str(ImageStylePreset.objects.first().pk),
        "reference_url": "http://127.0.0.1/private.png",
    }
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="image_generations")
    initial = account.available
    with override_settings(WEB_IMPORT_TEST_ALLOWED_CIDRS=()):
        rejected = client.post(
            f"/api/v1/subjects/{subject.pk}/images/generate",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="unsafe-reference-idempotency-0001",
        )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["details"]["image_code"] == "IMAGE_REFERENCE_URL_UNSAFE"
    account.refresh_from_db()
    assert account.available == initial and account.frozen == 0

    payload["reference_url"] = ""
    with patch("apps.images.views._enqueue"):
        created = client.post(
            f"/api/v1/subjects/{subject.pk}/images/generate",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="safe-image-api-idempotency-0001",
        )
    assert created.status_code == 202, created.content
    assert created.json()["data"]["job"]["status"] == "queued"
    assert ImageGenerationJob.objects.filter(pk=created.json()["data"]["job"]["id"]).exists()

    other = User.objects.create_user(
        phone=f"136{uuid.uuid4().int % 100000000:08d}",
        nickname="other image API user",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
    )
    denied = APIClient()
    denied.force_authenticate(user=other)
    assert (
        denied.get(f"/api/v1/image-jobs/{created.json()['data']['job']['id']}").status_code == 404
    )
