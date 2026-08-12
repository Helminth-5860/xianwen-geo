from dataclasses import dataclass
from typing import BinaryIO, Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .parse_exceptions import DocumentOcrUnavailable


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine_version: str
    warning_codes: tuple[str, ...] = ()


class OcrProvider(Protocol):
    key: str

    def is_available(self) -> bool: ...

    def recognize(self, stream: BinaryIO) -> OcrResult: ...


class MockOcrProvider:
    key = "mock"

    def is_available(self) -> bool:
        return True

    def recognize(self, stream: BinaryIO) -> OcrResult:
        stream.read(1)
        return OcrResult("\u672c\u5730 OCR \u6d4b\u8bd5\u6587\u672c", "mock-v1")


class UnavailableOcrProvider:
    key = "unavailable"

    def is_available(self) -> bool:
        return False

    def recognize(self, stream: BinaryIO) -> OcrResult:
        raise DocumentOcrUnavailable


def get_ocr_provider() -> OcrProvider:
    provider = settings.DOCUMENT_OCR_PROVIDER
    if provider == "mock":
        return MockOcrProvider()
    if provider == "unavailable":
        return UnavailableOcrProvider()
    raise ImproperlyConfigured("Unsupported OCR provider.")
