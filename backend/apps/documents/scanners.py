import socket
import struct
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


class ClamAVFileScanner:
    """Minimal clamd INSTREAM client with bounded I/O and fail-closed parsing."""

    def scan(self, stream: BinaryIO) -> ScanResult:
        try:
            with socket.create_connection(
                (settings.CLAMAV_HOST, settings.CLAMAV_PORT),
                timeout=settings.CLAMAV_TIMEOUT_SECONDS,
            ) as connection:
                connection.settimeout(settings.CLAMAV_TIMEOUT_SECONDS)
                connection.sendall(b"zINSTREAM\0")
                total = 0
                while chunk := stream.read(64 * 1024):
                    total += len(chunk)
                    if total > settings.FILE_UPLOAD_MAX_BYTES:
                        return ScanResult("rejected", "clamav", "FILE_TOO_LARGE")
                    connection.sendall(struct.pack("!I", len(chunk)))
                    connection.sendall(chunk)
                connection.sendall(struct.pack("!I", 0))
                response = connection.recv(4096).decode("utf-8", errors="replace").strip("\0\r\n")
        except (OSError, TimeoutError):
            return ScanResult("temporarily_unavailable", "clamav", "SCANNER_UNAVAILABLE")
        if response.endswith(" OK"):
            return ScanResult("clean", "clamav")
        if response.endswith(" FOUND"):
            return ScanResult("rejected", "clamav", "MALWARE_DETECTED")
        return ScanResult("temporarily_unavailable", "clamav", "SCANNER_INVALID_RESPONSE")


def file_scanner() -> FileScanner:
    if settings.FILE_SCANNER_PROVIDER == "mock" and settings.APP_ENV in {"local", "test"}:
        return MockFileScanner()
    if settings.FILE_SCANNER_PROVIDER == "clamav" and settings.CLAMAV_HOST:
        return ClamAVFileScanner()
    return UnavailableFileScanner()
