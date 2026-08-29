from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.cache import cache

from .catalog import PLATFORM_BY_KEY
from .worker_client import PublishingWorkerError, publishing_capabilities

_CACHE_KEY = "publishing:worker-capabilities:v2"
_POSITIVE_CACHE_SECONDS = 30
_NEGATIVE_CACHE_SECONDS = 5
_AUTH_CAPABILITY = "auth"
_DRAFT_CAPABILITY = "draft"
_IMAGE_UPLOAD_CAPABILITY = "image_upload"
_PUBLIC_CAPABILITIES = frozenset({"public", "public_publish"})


@dataclass(frozen=True)
class WorkerCapabilitySnapshot:
    service_available: bool
    verified_platforms: dict[str, frozenset[str]]
    implemented_platforms: dict[str, frozenset[str]]

    def verified_for(self, platform_key: str) -> frozenset[str]:
        return self.verified_platforms.get(platform_key, frozenset())

    def implemented_for(self, platform_key: str) -> frozenset[str]:
        return self.implemented_platforms.get(platform_key, frozenset())


def _snapshot_from_cache(value: object) -> WorkerCapabilitySnapshot | None:
    if not isinstance(value, dict):
        return None
    available = value.get("service_available")
    raw_verified = value.get("verified_platforms")
    raw_implemented = value.get("implemented_platforms")
    if (
        not isinstance(available, bool)
        or not isinstance(raw_verified, dict)
        or not isinstance(raw_implemented, dict)
    ):
        return None

    def normalized(raw: dict[object, object]) -> dict[str, frozenset[str]]:
        result: dict[str, frozenset[str]] = {}
        for key, capabilities in raw.items():
            if key not in PLATFORM_BY_KEY or not isinstance(capabilities, list):
                continue
            result[str(key)] = frozenset(
                str(item).strip().lower()
                for item in capabilities
                if isinstance(item, str) and str(item).strip()
            )
        return result

    return WorkerCapabilitySnapshot(
        service_available=available,
        verified_platforms=normalized(raw_verified),
        implemented_platforms=normalized(raw_implemented),
    )


def _cache_payload(snapshot: WorkerCapabilitySnapshot) -> dict[str, Any]:
    return {
        "service_available": snapshot.service_available,
        "verified_platforms": {
            key: sorted(capabilities)
            for key, capabilities in snapshot.verified_platforms.items()
        },
        "implemented_platforms": {
            key: sorted(capabilities)
            for key, capabilities in snapshot.implemented_platforms.items()
        },
    }


def worker_capability_snapshot(*, force_refresh: bool = False) -> WorkerCapabilitySnapshot:
    """Return the publishing worker's verified capability declaration.

    Environment allowlists decide which integrations may be considered for rollout,
    but this runtime declaration is the fail-closed source of truth for what the
    worker has actually verified. Only short-lived, non-sensitive capability names
    are cached.
    """

    if not force_refresh:
        cached = _snapshot_from_cache(cache.get(_CACHE_KEY))
        if cached is not None:
            return cached

    try:
        response = publishing_capabilities()
    except PublishingWorkerError:
        snapshot = WorkerCapabilitySnapshot(
            service_available=False,
            verified_platforms={},
            implemented_platforms={},
        )
        cache.set(_CACHE_KEY, _cache_payload(snapshot), timeout=_NEGATIVE_CACHE_SECONDS)
        return snapshot

    raw_publishers = response.get("publishers") if isinstance(response, dict) else None
    if not isinstance(raw_publishers, list):
        snapshot = WorkerCapabilitySnapshot(
            service_available=False,
            verified_platforms={},
            implemented_platforms={},
        )
        cache.set(_CACHE_KEY, _cache_payload(snapshot), timeout=_NEGATIVE_CACHE_SECONDS)
        return snapshot

    verified_platforms: dict[str, frozenset[str]] = {}
    implemented_platforms: dict[str, frozenset[str]] = {}
    for item in raw_publishers:
        if not isinstance(item, dict):
            continue
        key = str(item.get("platform_key") or "").strip().lower()
        raw_verified = item.get("verified_capabilities")
        raw_implemented = item.get("implemented_capabilities")
        if key not in PLATFORM_BY_KEY or not isinstance(raw_verified, list):
            continue
        # Legacy workers used the word "verified" for code-path declarations,
        # before real-account acceptance was separated from implementation. During
        # a rolling deployment those declarations are safe only for explicit
        # internal validation; they must never unlock ordinary users.
        if not isinstance(raw_implemented, list):
            raw_implemented = raw_verified
            raw_verified = []
        verified_platforms[key] = frozenset(
            str(capability).strip().lower()
            for capability in raw_verified
            if isinstance(capability, str) and str(capability).strip()
        )
        implemented_platforms[key] = frozenset(
            str(capability).strip().lower()
            for capability in raw_implemented
            if isinstance(capability, str) and str(capability).strip()
        )

    snapshot = WorkerCapabilitySnapshot(
        service_available=True,
        verified_platforms=verified_platforms,
        implemented_platforms=implemented_platforms,
    )
    cache.set(_CACHE_KEY, _cache_payload(snapshot), timeout=_POSITIVE_CACHE_SECONDS)
    return snapshot


def authorization_verified(capabilities: frozenset[str]) -> bool:
    return _AUTH_CAPABILITY in capabilities


def draft_verified(capabilities: frozenset[str]) -> bool:
    return _DRAFT_CAPABILITY in capabilities


def public_publish_verified(capabilities: frozenset[str]) -> bool:
    return bool(_PUBLIC_CAPABILITIES & capabilities)


def image_upload_verified(capabilities: frozenset[str]) -> bool:
    return _IMAGE_UPLOAD_CAPABILITY in capabilities


def clear_worker_capability_cache() -> None:
    cache.delete(_CACHE_KEY)
