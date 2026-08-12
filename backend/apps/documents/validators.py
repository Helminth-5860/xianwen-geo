import hashlib
import io
import re
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, cast

from django.conf import settings
from PIL import Image, UnidentifiedImageError

from .exceptions import FileContentInvalid, FileSizeInvalid, FileTypeNotAllowed


@dataclass(frozen=True)
class FileKindDefinition:
    extensions: tuple[str, ...]
    declared_mimes: tuple[str, ...]
    detected_mime: str


FILE_KINDS = {
    "pdf": FileKindDefinition(
        (".pdf",), ("application/pdf", "application/octet-stream"), "application/pdf"
    ),
    "docx": FileKindDefinition(
        (".docx",),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
        ),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "xlsx": FileKindDefinition(
        (".xlsx",),
        (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
        ),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "txt": FileKindDefinition((".txt",), ("text/plain", "application/octet-stream"), "text/plain"),
    "markdown": FileKindDefinition(
        (".md", ".markdown"),
        ("text/markdown", "text/plain", "application/octet-stream"),
        "text/markdown",
    ),
    "jpeg": FileKindDefinition(
        (".jpg", ".jpeg"), ("image/jpeg", "application/octet-stream"), "image/jpeg"
    ),
    "png": FileKindDefinition((".png",), ("image/png", "application/octet-stream"), "image/png"),
    "webp": FileKindDefinition(
        (".webp",), ("image/webp", "application/octet-stream"), "image/webp"
    ),
}


@dataclass
class ValidatedFile:
    stream: BinaryIO
    size: int
    sha256: str
    kind: str
    mime: str


def safe_filename(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 255:
        raise FileTypeNotAllowed
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise FileTypeNotAllowed
    name = value.replace("\\", "/").split("/")[-1].strip()
    if not name or name in {".", ".."}:
        raise FileTypeNotAllowed
    return name


def content_disposition_filename(value: str) -> str:
    name = safe_filename(value)
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    return cleaned[:180] or "download"


def declared_kind(filename: str, content_type: str) -> str:
    extension = Path(safe_filename(filename)).suffix.casefold()
    mime = (content_type or "").split(";", 1)[0].strip().casefold()
    for kind, definition in FILE_KINDS.items():
        if extension in definition.extensions:
            if mime not in definition.declared_mimes:
                raise FileTypeNotAllowed
            return kind
    raise FileTypeNotAllowed


def _copy_bounded(stream: BinaryIO, maximum: int) -> tuple[BinaryIO, int, str]:
    output = SpooledTemporaryFile(max_size=min(maximum, 8 * 1024 * 1024), mode="w+b")
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = stream.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            output.close()
            raise FileSizeInvalid
        digest.update(chunk)
        output.write(chunk)
    if total <= 0:
        output.close()
        raise FileSizeInvalid
    output.seek(0)
    return cast(BinaryIO, output), total, digest.hexdigest()


def _validate_pdf(stream: BinaryIO) -> None:
    head = stream.read(8)
    stream.seek(0, io.SEEK_END)
    size = stream.tell()
    stream.seek(max(0, size - 2048))
    tail = stream.read()
    stream.seek(0)
    if not head.startswith(b"%PDF-") or b"%%EOF" not in tail:
        raise FileContentInvalid


def _safe_zip_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return not path.is_absolute() and ".." not in path.parts and not normalized.startswith("/")


def _validate_office(stream: BinaryIO, kind: str) -> None:
    try:
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > settings.FILE_VALIDATION_MAX_ARCHIVE_ENTRIES:
                raise FileContentInvalid
            total = 0
            names = set()
            for item in entries:
                if not _safe_zip_name(item.filename) or (item.flag_bits & 0x1):
                    raise FileContentInvalid
                if item.file_size > settings.FILE_VALIDATION_MAX_ARCHIVE_ENTRY_BYTES:
                    raise FileContentInvalid
                total += item.file_size
                if total > settings.FILE_VALIDATION_MAX_UNCOMPRESSED_BYTES:
                    raise FileContentInvalid
                ratio = item.file_size / max(item.compress_size, 1)
                if ratio > settings.FILE_VALIDATION_MAX_COMPRESSION_RATIO:
                    raise FileContentInvalid
                lowered = item.filename.casefold()
                if "vbaproject.bin" in lowered or "macrosheets" in lowered:
                    raise FileContentInvalid
                names.add(item.filename)
            required = (
                {"[Content_Types].xml", "word/document.xml"}
                if kind == "docx"
                else {"[Content_Types].xml", "xl/workbook.xml"}
            )
            if not required <= names:
                raise FileContentInvalid
            content_types = archive.read("[Content_Types].xml").lower()
            if b"macroenabled" in content_types or b"vba" in content_types:
                raise FileContentInvalid
    except (zipfile.BadZipFile, KeyError, RuntimeError, OSError) as exc:
        raise FileContentInvalid from exc
    finally:
        stream.seek(0)


def _validate_text(stream: BinaryIO) -> None:
    data = stream.read()
    stream.seek(0)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileContentInvalid from exc
    if "\x00" in text:
        raise FileContentInvalid


def _validate_image(stream: BinaryIO, kind: str) -> None:
    expected = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}[kind]
    old_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = settings.FILE_IMAGE_MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(stream)
            if image.format != expected:
                raise FileContentInvalid
            width, height = image.size
            if width > settings.FILE_IMAGE_MAX_WIDTH or height > settings.FILE_IMAGE_MAX_HEIGHT:
                raise FileContentInvalid
            if width * height > settings.FILE_IMAGE_MAX_PIXELS:
                raise FileContentInvalid
            image.verify()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise FileContentInvalid from exc
    finally:
        Image.MAX_IMAGE_PIXELS = old_limit
        stream.seek(0)


def validate_stream(stream: BinaryIO, *, expected_kind: str, maximum: int) -> ValidatedFile:
    output, size, digest = _copy_bounded(stream, maximum)
    try:
        if expected_kind == "pdf":
            _validate_pdf(output)
        elif expected_kind in {"docx", "xlsx"}:
            _validate_office(output, expected_kind)
        elif expected_kind in {"txt", "markdown"}:
            _validate_text(output)
        elif expected_kind in {"jpeg", "png", "webp"}:
            _validate_image(output, expected_kind)
        else:
            raise FileTypeNotAllowed
    except Exception:
        output.close()
        raise
    return ValidatedFile(
        output, size, digest, expected_kind, FILE_KINDS[expected_kind].detected_mime
    )
