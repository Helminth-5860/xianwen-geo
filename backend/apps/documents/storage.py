from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import BinaryIO, Protocol

from django.conf import settings

from .exceptions import FileStorageUnavailable


@dataclass(frozen=True)
class UploadRequest:
    url: str
    fields: dict[str, str]
    expires_in: int


@dataclass(frozen=True)
class ObjectMetadata:
    size: int
    etag: str
    content_type: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class StoredObject:
    key: str
    last_modified: datetime


class StorageProvider(Protocol):
    def create_upload_request(
        self, *, key: str, content_type: str, max_bytes: int
    ) -> UploadRequest: ...
    def head_object(self, key: str) -> ObjectMetadata: ...
    def open_object(self, key: str) -> BinaryIO: ...
    def copy_verified_object(
        self,
        *,
        source_key: str,
        final_key: str,
        source_etag: str,
        size: int,
        sha256: str,
        content_type: str,
    ) -> None: ...
    def delete_temporary_object(self, key: str) -> None: ...
    def create_download_url(self, *, key: str, filename: str, content_type: str) -> str: ...
    def list_system_objects(self, *, prefix: str, limit: int) -> list[StoredObject]: ...
    def put_system_object(self, *, key: str, data: bytes, content_type: str) -> None: ...
    def put_system_stream(
        self,
        *,
        key: str,
        stream: BinaryIO,
        content_type: str,
        size: int,
        sha256: str,
    ) -> None: ...


class S3CompatibleStorageProvider:
    def __init__(self) -> None:
        import boto3  # type: ignore[import-untyped]
        from botocore.config import Config  # type: ignore[import-untyped]

        if not all(
            (
                settings.S3_ENDPOINT_URL,
                settings.S3_BUCKET,
                settings.S3_ACCESS_KEY,
                settings.S3_SECRET_KEY,
            )
        ):
            raise FileStorageUnavailable
        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def create_upload_request(
        self, *, key: str, content_type: str, max_bytes: int
    ) -> UploadRequest:
        try:
            value = self.client.generate_presigned_post(
                Bucket=self.bucket,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", 1, max_bytes],
                ],
                ExpiresIn=settings.FILE_UPLOAD_URL_TTL,
            )
        except Exception as exc:
            raise FileStorageUnavailable from exc
        return UploadRequest(value["url"], value["fields"], settings.FILE_UPLOAD_URL_TTL)

    def head_object(self, key: str) -> ObjectMetadata:
        try:
            value = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise FileStorageUnavailable from exc
        return ObjectMetadata(
            int(value["ContentLength"]),
            str(value.get("ETag", "")).strip('"'),
            value.get("ContentType", "application/octet-stream"),
            {str(k): str(v) for k, v in value.get("Metadata", {}).items()},
        )

    def open_object(self, key: str) -> BinaryIO:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except Exception as exc:
            raise FileStorageUnavailable from exc

    def copy_verified_object(
        self,
        *,
        source_key: str,
        final_key: str,
        source_etag: str,
        size: int,
        sha256: str,
        content_type: str,
    ) -> None:
        try:
            existing = self.client.head_object(Bucket=self.bucket, Key=final_key)
        except Exception:
            existing = None
        if existing is not None:
            metadata = existing.get("Metadata", {})
            if (
                int(existing["ContentLength"]) == size
                and metadata.get("sha256") == sha256
                and existing.get("ContentType") == content_type
            ):
                return
            raise FileStorageUnavailable
        try:
            self.client.copy_object(
                Bucket=self.bucket,
                Key=final_key,
                CopySource={"Bucket": self.bucket, "Key": source_key},
                CopySourceIfMatch=source_etag,
                ContentType=content_type,
                Metadata={"sha256": sha256},
                MetadataDirective="REPLACE",
            )
        except Exception as exc:
            raise FileStorageUnavailable from exc

    def delete_temporary_object(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise FileStorageUnavailable from exc

    def create_download_url(self, *, key: str, filename: str, content_type: str) -> str:
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ResponseContentType": content_type,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"',
                    "ResponseCacheControl": "no-store",
                },
                ExpiresIn=settings.FILE_DOWNLOAD_URL_TTL,
            )
        except Exception as exc:
            raise FileStorageUnavailable from exc

    def list_system_objects(self, *, prefix: str, limit: int) -> list[StoredObject]:
        try:
            value = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=limit)
        except Exception as exc:
            raise FileStorageUnavailable from exc
        return [
            StoredObject(item["Key"], item["LastModified"])
            for item in value.get("Contents", [])
            if isinstance(item.get("Key"), str)
        ]

    def put_system_object(self, *, key: str, data: bytes, content_type: str) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={"sha256": hashlib_sha256(data)},
            )
        except Exception as exc:
            raise FileStorageUnavailable from exc

    def put_system_stream(
        self,
        *,
        key: str,
        stream: BinaryIO,
        content_type: str,
        size: int,
        sha256: str,
    ) -> None:
        """Upload a verified stream without materialising it in application memory."""

        try:
            existing = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            response = getattr(exc, "response", {})
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            metadata = response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}
            code = str(error.get("Code", "")) if isinstance(error, dict) else ""
            status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                existing = None
            else:
                raise FileStorageUnavailable from exc
        if existing is not None:
            metadata = existing.get("Metadata", {})
            if (
                int(existing["ContentLength"]) == size
                and metadata.get("sha256") == sha256
                and existing.get("ContentType") == content_type
            ):
                return
            raise FileStorageUnavailable
        try:
            stream.seek(0)
            self.client.upload_fileobj(
                stream,
                self.bucket,
                key,
                ExtraArgs={
                    "ContentType": content_type,
                    "Metadata": {"sha256": sha256},
                },
            )
        except Exception as exc:
            raise FileStorageUnavailable from exc


class MockStorageProvider:
    _objects: dict[str, tuple[bytes, str, dict[str, str]]] = {}
    _lock = threading.Lock()

    @classmethod
    def put_for_test(
        cls,
        key: str,
        data: bytes,
        content_type: str,
        *,
        metadata: dict[str, str] | None = None,
    ) -> None:
        with cls._lock:
            cls._objects[key] = (
                data,
                content_type,
                {"sha256": hashlib_sha256(data)} if metadata is None else dict(metadata),
            )

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._objects.clear()

    def create_upload_request(
        self, *, key: str, content_type: str, max_bytes: int
    ) -> UploadRequest:
        return UploadRequest(
            "mock://upload",
            {"key": key, "Content-Type": content_type, "x-max-bytes": str(max_bytes)},
            settings.FILE_UPLOAD_URL_TTL,
        )

    def head_object(self, key: str) -> ObjectMetadata:
        try:
            data, content_type, metadata = self._objects[key]
        except KeyError as exc:
            raise FileStorageUnavailable from exc
        return ObjectMetadata(len(data), hashlib_sha256(data)[:32], content_type, metadata)

    def open_object(self, key: str) -> BinaryIO:
        try:
            return io.BytesIO(self._objects[key][0])
        except KeyError as exc:
            raise FileStorageUnavailable from exc

    def copy_verified_object(
        self,
        *,
        source_key: str,
        final_key: str,
        source_etag: str,
        size: int,
        sha256: str,
        content_type: str,
    ) -> None:
        with self._lock:
            source = self._objects.get(source_key)
            if source is None:
                raise FileStorageUnavailable
            existing = self._objects.get(final_key)
            if existing is not None:
                if len(existing[0]) == size and existing[2].get("sha256") == sha256:
                    return
                raise FileStorageUnavailable
            self._objects[final_key] = (source[0], content_type, {"sha256": sha256})

    def delete_temporary_object(self, key: str) -> None:
        with self._lock:
            self._objects.pop(key, None)

    def create_download_url(self, *, key: str, filename: str, content_type: str) -> str:
        if key not in self._objects:
            raise FileStorageUnavailable
        return f"mock://download/{key}"

    def put_system_object(self, *, key: str, data: bytes, content_type: str) -> None:
        self.put_for_test(key, data, content_type)

    def put_system_stream(
        self,
        *,
        key: str,
        stream: BinaryIO,
        content_type: str,
        size: int,
        sha256: str,
    ) -> None:
        try:
            stream.seek(0)
            data = stream.read(size + 1)
        except Exception as exc:
            raise FileStorageUnavailable from exc
        if len(data) != size or hashlib_sha256(data) != sha256:
            raise FileStorageUnavailable
        self.put_for_test(key, data, content_type, metadata={"sha256": sha256})

    def list_system_objects(self, *, prefix: str, limit: int) -> list[StoredObject]:
        with self._lock:
            keys = sorted(key for key in self._objects if key.startswith(prefix))[:limit]
        return [StoredObject(key, datetime.now(UTC)) for key in keys]


class UnavailableStorageProvider:
    def __getattr__(self, name):
        raise FileStorageUnavailable


def hashlib_sha256(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def storage_provider() -> StorageProvider:
    provider = settings.FILE_STORAGE_PROVIDER
    if provider == "s3":
        return S3CompatibleStorageProvider()
    if provider == "mock" and settings.APP_ENV in {"local", "test"}:
        return MockStorageProvider()
    return UnavailableStorageProvider()
