import base64
import json
import time
import urllib.error
import urllib.request
import uuid

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import override_settings
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


def _multipart_post(url, fields, content, *, origin=None):
    boundary = f"xianwen-{uuid.uuid4().hex}"
    chunks = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="opaque.txt"\r\n',
            b"Content-Type: text/plain\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if origin:
        headers["Origin"] = origin
    return urllib.request.urlopen(
        urllib.request.Request(url, data=b"".join(chunks), headers=headers)
    )


@override_settings(FILE_UPLOAD_URL_TTL=1, FILE_DOWNLOAD_URL_TTL=1)
def test_real_minio_presigned_post_enforces_size_expiry_download_expiry_and_cors(settings):
    provider = S3CompatibleStorageProvider()
    normal_key = f"staging/{uuid.uuid4().hex}"
    normal = provider.create_upload_request(key=normal_key, content_type="text/plain", max_bytes=5)
    with _multipart_post(
        normal.url, normal.fields, b"safe", origin="http://localhost:3000"
    ) as uploaded:
        assert uploaded.status in {200, 204}
        assert uploaded.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
    assert provider.head_object(normal_key).size == 4

    oversized = provider.create_upload_request(
        key=f"staging/{uuid.uuid4().hex}", content_type="text/plain", max_bytes=5
    )
    with pytest.raises(urllib.error.HTTPError) as denied_size:
        _multipart_post(oversized.url, oversized.fields, b"123456")
    assert denied_size.value.code == 400

    expired_upload = provider.create_upload_request(
        key=f"staging/{uuid.uuid4().hex}", content_type="text/plain", max_bytes=5
    )
    download_url = provider.create_download_url(
        key=normal_key, filename="safe.txt", content_type="text/plain"
    )
    time.sleep(2.1)
    with pytest.raises(urllib.error.HTTPError) as denied_upload_expiry:
        _multipart_post(expired_upload.url, expired_upload.fields, b"safe")
    assert denied_upload_expiry.value.code in {400, 403}
    with pytest.raises(urllib.error.HTTPError) as denied_download_expiry:
        urllib.request.urlopen(download_url)
    assert denied_download_expiry.value.code == 403

    preflight = urllib.request.Request(
        f"{settings.S3_ENDPOINT_URL}/{settings.S3_BUCKET}/{normal_key}",
        method="OPTIONS",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    with urllib.request.urlopen(preflight) as allowed:
        assert allowed.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
        assert "POST" in allowed.headers.get("Access-Control-Allow-Methods", "")
        assert "content-type" in allowed.headers.get("Access-Control-Allow-Headers", "").lower()
        assert allowed.headers.get("Access-Control-Allow-Origin") != "*"
    denied_preflight = urllib.request.Request(
        f"{settings.S3_ENDPOINT_URL}/{settings.S3_BUCKET}/{normal_key}",
        method="OPTIONS",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    try:
        response = urllib.request.urlopen(denied_preflight)
    except urllib.error.HTTPError as exc:
        response = exc
    assert response.headers.get("Access-Control-Allow-Origin") != "https://evil.example"


def test_staging_key_is_opaque_and_contains_no_business_identifiers():
    declared = ("customer-report.txt", "13800138000", "subject-name", "customer@example.com")
    key = f"staging/{uuid.uuid4().hex}"
    assert len(key) == len("staging/") + 32
    assert all(value.casefold() not in key.casefold() for value in declared)
