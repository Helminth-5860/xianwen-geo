from dataclasses import dataclass
from typing import BinaryIO, Protocol

from django.conf import settings


@dataclass(frozen=True)
class ScanResult:
    status: str
    engine_version: str
    reason_code: str = ""


class FileScanner(Protocol):
    def scan(self, stream: BinaryIO) -> ScanResult: ...


class MockFileScanner:
    def scan(self, stream: BinaryIO) -> ScanResult:
        position = stream.tell()
        prefix = stream.read(64)
        stream.seek(position)
        if prefix.startswith(b"XW-MALWARE-TEST"):
            return ScanResult("rejected", "mock-v1", "MALWARE_DETECTED")
        if prefix.startswith(b"XW-SCANNER-UNAVAILABLE"):
            return ScanResult("temporarily_unavailable", "mock-v1", "SCANNER_UNAVAILABLE")
        return ScanResult("clean", "mock-v1")


class UnavailableFileScanner:
    def scan(self, stream: BinaryIO) -> ScanResult:
        return ScanResult("temporarily_unavailable", "unavailable", "SCANNER_UNAVAILABLE")


def file_scanner() -> FileScanner:
    if settings.FILE_SCANNER_PROVIDER == "mock" and settings.APP_ENV in {"local", "test"}:
        return MockFileScanner()
    return UnavailableFileScanner()
