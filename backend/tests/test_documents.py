import io
import zipfile

import pytest
from django.test import override_settings

from apps.documents.exceptions import FileContentInvalid, FileStorageUnavailable, FileTypeNotAllowed
from apps.documents.storage import MockStorageProvider, storage_provider
from apps.documents.validators import declared_kind, safe_filename, validate_stream


def test_file_kind_matrix_accepts_only_frozen_v1_types():
    assert declared_kind("资料.PDF", "application/pdf") == "pdf"
    assert declared_kind("notes.md", "text/plain") == "markdown"
    assert declared_kind("photo.jpeg", "image/jpeg") == "jpeg"
    with pytest.raises(FileTypeNotAllowed):
        declared_kind("archive.zip", "application/zip")
    with pytest.raises(FileTypeNotAllowed):
        declared_kind("macro.docm", "application/octet-stream")
    with pytest.raises(FileTypeNotAllowed):
        safe_filename("bad\r\nname.pdf")


def _office_zip(*names: str) -> io.BytesIO:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name in names:
            archive.writestr(name, b"safe")
    output.seek(0)
    return output


def test_office_validator_rejects_traversal_and_macro_parts():
    with pytest.raises(FileContentInvalid):
        validate_stream(
            _office_zip("[Content_Types].xml", "word/document.xml", "../secret"),
            expected_kind="docx",
            maximum=1024 * 1024,
        )
    with pytest.raises(FileContentInvalid):
        validate_stream(
            _office_zip("[Content_Types].xml", "word/document.xml", "word/vbaProject.bin"),
            expected_kind="docx",
            maximum=1024 * 1024,
        )


def test_mock_upload_credential_is_size_bound_and_contains_no_filename():
    request = MockStorageProvider().create_upload_request(
        key="staging/" + "a" * 32,
        content_type="application/pdf",
        max_bytes=1234,
    )
    assert request.fields["x-max-bytes"] == "1234"
    assert "customer" not in str(request.fields).lower()


@override_settings(APP_ENV="production", FILE_STORAGE_PROVIDER="mock")
def test_production_cannot_construct_mock_provider():
    with pytest.raises(FileStorageUnavailable):
        storage_provider().head_object("opaque")


@override_settings(APP_ENV="production", FILE_STORAGE_PROVIDER="unavailable")
def test_unavailable_provider_fails_closed():
    with pytest.raises(FileStorageUnavailable):
        storage_provider().create_upload_request(
            key="staging/opaque", content_type="application/pdf", max_bytes=10
        )
