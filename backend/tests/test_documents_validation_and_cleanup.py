import io
import zipfile
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from PIL import Image

from apps.documents.exceptions import FileContentInvalid, FileTypeNotAllowed
from apps.documents.storage import StoredObject
from apps.documents.validators import content_disposition_filename, validate_stream


def _zip(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    output.seek(0)
    return output


@pytest.mark.parametrize(
    ("kind", "stream"),
    [
        ("pdf", io.BytesIO(b"%PDF-1.7\n1 0 obj\nendobj\n%%EOF")),
        ("txt", io.BytesIO(b"plain UTF-8 text")),
        ("markdown", io.BytesIO(b"# Markdown")),
        (
            "docx",
            _zip({"[Content_Types].xml": b"safe", "word/document.xml": b"safe"}),
        ),
        (
            "xlsx",
            _zip({"[Content_Types].xml": b"safe", "xl/workbook.xml": b"safe"}),
        ),
    ],
)
def test_structural_validator_accepts_frozen_safe_matrix(kind, stream):
    result = validate_stream(stream, expected_kind=kind, maximum=1024 * 1024)
    assert result.kind == kind
    assert result.size > 0
    assert len(result.sha256) == 64
    result.stream.close()


@pytest.mark.parametrize(
    ("kind", "format_name"), [("jpeg", "JPEG"), ("png", "PNG"), ("webp", "WEBP")]
)
def test_image_validator_performs_real_decode(kind, format_name):
    output = io.BytesIO()
    Image.new("RGB", (4, 4), color="white").save(output, format=format_name)
    output.seek(0)
    result = validate_stream(output, expected_kind=kind, maximum=1024 * 1024)
    assert result.kind == kind
    result.stream.close()


@override_settings(FILE_VALIDATION_MAX_COMPRESSION_RATIO=2)
def test_office_validator_rejects_compression_bomb_ratio():
    stream = _zip(
        {
            "[Content_Types].xml": b"safe",
            "word/document.xml": b"A" * 20_000,
        }
    )
    with pytest.raises(FileContentInvalid):
        validate_stream(stream, expected_kind="docx", maximum=1024 * 1024)


@override_settings(FILE_IMAGE_MAX_WIDTH=2, FILE_IMAGE_MAX_HEIGHT=2, FILE_IMAGE_MAX_PIXELS=4)
def test_image_validator_rejects_dimension_limit():
    output = io.BytesIO()
    Image.new("RGB", (3, 3), color="white").save(output, format="PNG")
    output.seek(0)
    with pytest.raises(FileContentInvalid):
        validate_stream(output, expected_kind="png", maximum=1024 * 1024)


def test_content_disposition_filename_removes_header_and_path_material():
    assert content_disposition_filename("folder/报告 2026.pdf") == "__ 2026.pdf"
    with pytest.raises(FileTypeNotAllowed):
        content_disposition_filename("bad\r\nContent-Type: text/html")


class _CleanupProvider:
    def __init__(self):
        old = timezone.now() - timedelta(hours=2)
        self.objects = [
            StoredObject("staging/" + "a" * 32, old),
            StoredObject("objects/" + "b" * 32 + "/" + "c" * 32, old),
        ]
        self.deleted = []

    def list_system_objects(self, *, prefix, limit):
        return [item for item in self.objects if item.key.startswith(prefix)][:limit]

    def delete_temporary_object(self, key):
        self.deleted.append(key)


@pytest.mark.django_db
def test_orphan_reconciliation_is_bounded_dry_run_then_apply_without_key_logging(capsys):
    provider = _CleanupProvider()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "apps.documents.management.commands.reconcile_file_objects.storage_provider",
            lambda: provider,
        )
        call_command("reconcile_file_objects", "--dry-run", "--batch-size=2", verbosity=0)
        assert provider.deleted == []
        dry_output = capsys.readouterr().out
        assert "orphan_candidates=2" in dry_output
        assert "staging/" not in dry_output and "objects/" not in dry_output

        call_command("reconcile_file_objects", "--apply", "--batch-size=2", verbosity=0)
    assert len(provider.deleted) == 2
