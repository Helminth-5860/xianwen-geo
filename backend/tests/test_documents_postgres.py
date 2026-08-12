import base64
import json
import urllib.error
import urllib.request
import uuid

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django_redis import get_redis_connection

from apps.documents.models import DocumentVersion, FileStorageAllocation, FileUploadIntent
from apps.documents.storage import S3CompatibleStorageProvider
from apps.documents.validators import declared_kind

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_real_services(settings):
    if connection.vendor != "postgresql":
        pytest.skip("run with scripts/test-files.* against PostgreSQL, Redis and MinIO")
    assert get_redis_connection("default").ping()
    provider = S3CompatibleStorageProvider()
    provider.client.head_bucket(Bucket=provider.bucket)
    call_command("sync_plan_catalog", "--apply", verbosity=0)


def test_minio_presigned_post_policy_is_size_bound_and_opaque(settings):
    provider = S3CompatibleStorageProvider()
    opaque = f"staging/{uuid.uuid4().hex}"
    request = provider.create_upload_request(key=opaque, content_type="text/plain", max_bytes=17)
    assert request.url.startswith(("http://", "https://"))
    assert request.fields["key"] == opaque
    assert "phone" not in str(request.fields).lower()
    assert "filename" not in str(request.fields).lower()
    policy = json.loads(base64.b64decode(request.fields["policy"]))
    assert ["content-length-range", 1, 17] in policy["conditions"]
    with pytest.raises(urllib.error.HTTPError) as denied:
        urllib.request.urlopen(f"{settings.S3_ENDPOINT_URL}/{settings.S3_BUCKET}?list-type=2")
    assert denied.value.code in {401, 403}


def test_file_evidence_database_guards_are_installed():
    expected = {
        "documents_upload_intent_guard",
        "documents_document_guard",
        "documents_version_guard",
        "documents_allocation_guard",
        "documents_subject_version_reference_guard",
        "documents_document_complete",
        "documents_version_complete",
        "documents_storage_ledger_guard",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(%s)",
            [list(expected)],
        )
        actual = {row[0] for row in cursor.fetchall()}
    assert actual == expected


def test_storage_ledger_guard_is_installed_and_capacity_mode_is_static():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname='documents_storage_ledger_guard'"
        )
        assert cursor.fetchone()[0] == 1
    from apps.quotas.catalog import quota_definition

    assert quota_definition("storage_bytes").accounting_mode == "capacity_absolute"


def test_document_migration_does_not_fabricate_file_facts():
    assert FileUploadIntent.objects.count() == 0
    assert DocumentVersion.objects.count() == 0
    assert FileStorageAllocation.objects.count() == 0


def test_supported_file_declarations_are_bounded():
    assert declared_kind("safe.pdf", "application/pdf") == "pdf"
    assert declared_kind("safe.webp", "image/webp") == "webp"


def test_database_transaction_failure_leaves_no_partial_file_facts():
    before = (
        FileUploadIntent.objects.count(),
        DocumentVersion.objects.count(),
        FileStorageAllocation.objects.count(),
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1/0")
    assert before == (
        FileUploadIntent.objects.count(),
        DocumentVersion.objects.count(),
        FileStorageAllocation.objects.count(),
    )
