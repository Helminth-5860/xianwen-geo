from __future__ import annotations

import html
import os
import re
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.storage import storage_provider
from apps.images.models import ImageAsset, ImageDerivative
from apps.keywords.models import Keyword, KeywordSet

from .catalog import PLATFORM_BY_KEY
from .credentials import PlatformCredentialRuntimeUnavailable, platform_credentials
from .models import PlatformAccount, PublicationTarget, PublishingPreference
from .pause_control import AUTOMATION_PAUSED_CODE, PLATFORM_DISABLED_CODE
from .platform_health import platform_circuit_open
from .publication_state import aggregate_publication
from .security import PublishingCredentialError
from .worker_client import PublishingWorkerError, publish_to_platform


_TRANSIENT_RETRY_SECONDS = 75
_CIRCUIT_RETRY_SECONDS = 30 * 60


def _target_max_retries() -> int:
    try:
        value = int(os.getenv("PUBLISHING_TARGET_MAX_RETRIES", "3"))
    except ValueError:
        value = 3
    return max(1, min(10, value))


def _plain_text(value: str) -> str:
    text = re.sub(r"```.*?```", "", value, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_~`>#-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _simple_html(value: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if not paragraph:
            return
        blocks.append(f"<p>{'<br/>'.join(html.escape(item) for item in paragraph)}</p>")
        paragraph.clear()

    for raw in value.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush()
            level = min(3, len(heading.group(1)) + 1)
            blocks.append(f"<h{level}>{html.escape(heading.group(2).strip())}</h{level}>")
        elif line.startswith(("- ", "* ")):
            flush()
            blocks.append(f"<p>• {html.escape(line[2:].strip())}</p>")
        else:
            paragraph.append(line)
    flush()
    return "\n".join(blocks) or f"<p>{html.escape(value)}</p>"


def _publication_tags(target: PublicationTarget) -> list[str]:
    keyword_set = (
        KeywordSet.objects.filter(
            user=target.publication.user,
            subject=target.publication.subject,
            current_version__isnull=False,
        )
        .select_related("current_version")
        .first()
    )
    if keyword_set is None or keyword_set.current_version_id is None:
        return []

    title = target.adapted_title.strip().lower()
    content = _plain_text(target.adapted_content).lower()
    candidates = list(
        Keyword.objects.filter(keyword_set_version_id=keyword_set.current_version_id)
        .only("text", "priority", "relevance_score", "sort_order")
        .order_by("sort_order")[:100]
    )
    ranked: list[tuple[int, int, str]] = []
    for item in candidates:
        value = " ".join((item.text or "").strip().split())
        if not value or len(value) > 40:
            continue
        normalized = value.lower()
        score = 0
        if normalized in title:
            score += 8
        if normalized in content:
            score += 5
        if item.priority == "high":
            score += 2
        elif item.priority == "medium":
            score += 1
        if item.relevance_score is not None and item.relevance_score >= 80:
            score += 1
        if normalized not in title and normalized not in content:
            continue
        ranked.append((score, -item.sort_order, value))

    ranked.sort(reverse=True)
    result: list[str] = []
    seen: set[str] = set()
    for _score, _order, value in ranked:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= 8:
            break
    return result


def _delivery_assets(target: PublicationTarget) -> list[dict[str, Any]]:
    items = list((target.media_payload or {}).get("assets") or [])
    asset_ids = [item.get("asset_id") for item in items if item.get("asset_id")]
    derivative_ids = [item.get("derivative_id") for item in items if item.get("derivative_id")]
    assets = {
        str(item.pk): item
        for item in ImageAsset.objects.filter(
            pk__in=asset_ids,
            user=target.publication.user,
            subject=target.publication.subject,
            lifecycle_status=ImageAsset.LifecycleStatus.ACTIVE,
            moderation_status=ImageAsset.ModerationStatus.APPROVED,
        )
    }
    derivatives = {
        str(item.pk): item
        for item in ImageDerivative.objects.filter(
            pk__in=derivative_ids,
            user=target.publication.user,
        )
    }
    provider = storage_provider()
    result: list[dict[str, Any]] = []
    for item in items:
        asset = assets.get(str(item.get("asset_id") or ""))
        if asset is None:
            continue
        purpose = str(item.get("purpose") or "inline")
        derivative = derivatives.get(str(item.get("derivative_id") or ""))
        if derivative is not None:
            url = provider.create_download_url(
                key=derivative.object_key,
                filename=f"publishing-{derivative.pk}",
                content_type=derivative.mime_type,
            )
        else:
            url = provider.create_download_url(
                key=asset.object_key,
                filename=f"publishing-{asset.pk}",
                content_type=asset.mime_type,
            )
        result.append(
            {
                "role": "information"
                if purpose == "information"
                else ("cover" if purpose == "cover" else "inline"),
                "url": url,
                "alt": target.adapted_title[:120],
            }
        )
    return result


def execute_target(*, target_id) -> dict[str, Any]:
    with transaction.atomic():
        target = (
            PublicationTarget.objects.select_for_update()
            .select_related(
                "publication",
                "publication__user",
                "publication__subject",
                "publication__article",
                "account",
            )
            .get(pk=target_id)
        )
        if target.status in {
            PublicationTarget.Status.SUCCEEDED,
            PublicationTarget.Status.SUBMITTED,
            PublicationTarget.Status.AUTH_REQUIRED,
            PublicationTarget.Status.PAUSED,
        }:
            return {"status": target.status}

        preference_enabled = PublishingPreference.objects.filter(
            user=target.publication.user,
            subject=target.publication.subject,
            is_enabled=True,
        ).exists()
        if not preference_enabled:
            target.status = PublicationTarget.Status.PAUSED
            target.safe_error_code = AUTOMATION_PAUSED_CODE
            target.save(update_fields=("status", "safe_error_code", "updated_at"))
            aggregate_publication(target.publication_id)
            return {"status": "paused"}

        if target.scheduled_at and target.scheduled_at > timezone.now():
            return {"status": "scheduled", "eta": target.scheduled_at}

        account = target.account
        if account is None or account.status != PlatformAccount.Status.CONNECTED:
            target.status = PublicationTarget.Status.AUTH_REQUIRED
            target.safe_error_code = "authorization_required"
            target.save(update_fields=("status", "safe_error_code", "updated_at"))
            aggregate_publication(target.publication_id)
            return {"status": "auth_required"}
        if not account.enabled_for_auto:
            target.status = PublicationTarget.Status.PAUSED
            target.safe_error_code = PLATFORM_DISABLED_CODE
            target.save(update_fields=("status", "safe_error_code", "updated_at"))
            aggregate_publication(target.publication_id)
            return {"status": "paused"}
        if platform_circuit_open(target.platform_key):
            # Do not open a browser or consume an attempt while a shared platform
            # circuit is cooling down. The Celery task will return after the circuit TTL.
            return {"status": "retry", "retry_after": _CIRCUIT_RETRY_SECONDS}
        if target.status not in {
            PublicationTarget.Status.READY,
            PublicationTarget.Status.FAILED,
            PublicationTarget.Status.WAITING,
        }:
            return {"status": target.status}
        target.status = PublicationTarget.Status.RUNNING
        target.attempts += 1
        target.safe_error_code = ""
        target.save(update_fields=("status", "attempts", "safe_error_code", "updated_at"))

    target = (
        PublicationTarget.objects.select_related(
            "publication",
            "publication__user",
            "publication__subject",
            "publication__article",
            "account",
        )
        .get(pk=target_id)
    )
    try:
        credentials = platform_credentials(target.account)
    except PlatformCredentialRuntimeUnavailable:
        if target.attempts < _target_max_retries():
            PublicationTarget.objects.filter(pk=target.pk).update(
                status=PublicationTarget.Status.READY,
                safe_error_code="platform_unavailable",
            )
            aggregate_publication(target.publication_id)
            return {"status": "retry", "retry_after": _TRANSIENT_RETRY_SECONDS}
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.PAUSED,
            safe_error_code="platform_unavailable",
        )
        aggregate_publication(target.publication_id)
        return {"status": "paused"}
    except PublishingCredentialError:
        PlatformAccount.objects.filter(pk=target.account_id).update(
            status=PlatformAccount.Status.ACTION_REQUIRED,
            last_error_code="authorization_required",
            last_checked_at=timezone.now(),
        )
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.AUTH_REQUIRED,
            safe_error_code="authorization_required",
        )
        aggregate_publication(target.publication_id)
        return {"status": "auth_required"}

    try:
        assets = _delivery_assets(target)
    except FileStorageUnavailable:
        assets = []

    if target.platform_key not in PLATFORM_BY_KEY:
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.PAUSED,
            safe_error_code="platform_unavailable",
        )
        aggregate_publication(target.publication_id)
        return {"status": "paused"}
    if target.platform_key in {"xiaohongshu", "douyin"} and not assets:
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.FAILED,
            safe_error_code="media_invalid",
        )
        aggregate_publication(target.publication_id)
        return {"status": "failed"}

    text = _plain_text(target.adapted_content)
    tags = _publication_tags(target)
    try:
        result = publish_to_platform(
            platform_key=target.platform_key,
            target_id=str(target.pk),
            title=target.adapted_title,
            content_html=_simple_html(target.adapted_content),
            content_text=text,
            summary=text[:180],
            tags=tags,
            assets=assets,
            credentials=credentials,
            publish_mode="public",
        )
    except PublishingWorkerError as exc:
        if exc.code == "platform_circuit_open":
            PublicationTarget.objects.filter(pk=target.pk).update(
                status=PublicationTarget.Status.READY,
                safe_error_code="platform_unavailable",
            )
            aggregate_publication(target.publication_id)
            return {"status": "retry", "retry_after": _CIRCUIT_RETRY_SECONDS}
        retryable = exc.code in {"worker_timeout", "worker_unavailable"}
        if retryable and target.attempts < _target_max_retries():
            PublicationTarget.objects.filter(pk=target.pk).update(
                status=PublicationTarget.Status.READY,
                safe_error_code="platform_unavailable",
            )
            aggregate_publication(target.publication_id)
            return {"status": "retry", "retry_after": _TRANSIENT_RETRY_SECONDS}
        paused = exc.code == "platform_not_ready"
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.PAUSED if paused else PublicationTarget.Status.FAILED,
            safe_error_code="platform_unavailable",
        )
        aggregate_publication(target.publication_id)
        return {"status": "paused" if paused else "failed"}

    remote_status = str(result.get("status") or "failed")
    external_id = str(result.get("externalPostId") or "")[:255]
    management_url = str(result.get("managementUrl") or result.get("editUrl") or "")
    if (
        bool(result.get("success"))
        and remote_status == "published"
        and result.get("publicUrl")
    ):
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.SUCCEEDED,
            submitted_at=target.submitted_at or timezone.now(),
            published_at=timezone.now(),
            external_post_id=external_id,
            management_url=management_url,
            public_url=str(result.get("publicUrl") or ""),
            next_status_check_at=None,
            safe_error_code="",
        )
        aggregate_publication(target.publication_id)
        return {"status": "succeeded"}

    if bool(result.get("success")) and remote_status == "submitted":
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.SUBMITTED,
            submitted_at=timezone.now(),
            external_post_id=external_id,
            management_url=management_url,
            next_status_check_at=timezone.now() + timedelta(minutes=15),
            safe_error_code="",
        )
        aggregate_publication(target.publication_id)
        return {"status": "submitted"}

    if remote_status == "auth_required":
        PlatformAccount.objects.filter(pk=target.account_id).update(
            status=PlatformAccount.Status.EXPIRED,
            last_error_code="authorization_required",
            last_checked_at=timezone.now(),
        )
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.AUTH_REQUIRED,
            safe_error_code="authorization_required",
        )
        aggregate_publication(target.publication_id)
        return {"status": "auth_required"}

    code = str(result.get("safeErrorCode") or "platform_unavailable")[:100]
    status = (
        PublicationTarget.Status.PAUSED
        if remote_status in {"drafted", "action_required"}
        else PublicationTarget.Status.FAILED
    )
    PublicationTarget.objects.filter(pk=target.pk).update(
        status=status,
        external_post_id=external_id,
        management_url=management_url,
        safe_error_code=code,
    )
    aggregate_publication(target.publication_id)
    return {"status": status}
