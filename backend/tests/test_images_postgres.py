from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.db import DatabaseError, close_old_connections, connection

from apps.images.models import (
    ImageGenerationJob,
    ImageGenerationResult,
    ImageSizePreset,
)
from apps.images.services import create_image_job, execute_image_job
from apps.quotas.models import QuotaAccount
from apps.users.models import User
from tests import test_images as image_tests
from tests.test_images import StubImageAdapter

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def postgres_image_facts(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-only image guard test")
    return image_tests.image_facts.__wrapped__(monkeypatch)


def _thread_create(user_id, subject_id, request_id, size_id, style_id):
    close_old_connections()
    try:
        user = User.objects.get(pk=user_id)
        return create_image_job(
            user=user,
            subject_id=subject_id,
            article_id=None,
            role="cover",
            prompt="并发幂等图片请求",
            size_preset_id=size_id,
            style_preset_id=style_id,
            reference_asset_id=None,
            reference_document_version_id=None,
            reference_url="",
            idempotency_key="postgres-image-concurrency-idempotency-0001",
            request_id=request_id,
        )[0].pk
    finally:
        close_old_connections()


def test_postgresql_concurrent_duplicate_creates_one_job_and_one_hold(postgres_image_facts):
    import uuid

    user, subject, subscription, _, _, _ = postgres_image_facts
    size_id = ImageSizePreset.objects.first().pk
    from apps.images.models import ImageStylePreset

    style_id = ImageStylePreset.objects.first().pk
    request_ids = [uuid.uuid4(), uuid.uuid4()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _thread_create,
                user.pk,
                subject.pk,
                request_ids[index],
                size_id,
                style_id,
            )
            for index in range(2)
        ]
        job_ids = [future.result(timeout=20) for future in futures]
    assert job_ids[0] == job_ids[1]
    assert ImageGenerationJob.objects.filter(pk=job_ids[0]).count() == 1
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="image_credits")
    assert account.frozen == 1


def test_postgresql_image_provenance_and_evidence_guards(postgres_image_facts):
    from tests.test_images import _create_job

    user, subject, _, _, _, _ = postgres_image_facts
    adapter = StubImageAdapter()
    with patch("apps.images.services.model_registry.resolve", return_value=adapter):
        job, _ = _create_job(user, subject)
        assert execute_image_job(job_id=job.pk)["status"] == "succeeded"
    result = ImageGenerationResult.objects.get(job=job)

    with pytest.raises(DatabaseError):
        ImageGenerationResult._base_manager.filter(pk=result.pk).update(
            safe_metadata={"tampered": True}
        )
    with pytest.raises(DatabaseError):
        ImageGenerationJob.objects.filter(pk=job.pk).update(provider_model_id="tampered")
    with pytest.raises(DatabaseError):
        ImageGenerationJob.objects.filter(pk=job.pk).update(status="running")
    preset = ImageSizePreset.objects.first()
    with pytest.raises(DatabaseError):
        ImageSizePreset.objects.filter(pk=preset.pk).update(name="tampered")
