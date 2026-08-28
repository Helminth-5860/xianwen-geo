from __future__ import annotations

import html
import re
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.storage import storage_provider
from apps.images.models import ImageAsset, ImageDerivative

from .catalog import PLATFORM_BY_KEY
from .models import PlatformAccount, Publication, PublicationTarget
from .security import PublishingCredentialError, decrypt_secret
from .worker_client import PublishingWorkerError, publish_to_platform


_TRANSIENT_RETRY_SECONDS = 75


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
                "role": "information" if purpose == "information" else ("cover" if purpose == "cover" else "inline"),
                "url": url,
                "alt": target.adapted_title[:120],
            }
        )
    return result


def _aggregate_publication(publication_id) -> None:
    with transaction.atomic():
        publication = Publication.objects.select_for_update().get(pk=publication_id)
        statuses = list(publication.targets.values_list("status", flat=True))
        terminal_non_success = {
            PublicationTarget.Status.FAILED,
            PublicationTarget.Status.AUTH_REQUIRED,
            PublicationTarget.Status.PAUSED,
        }
        if not statuses:
            publication.status = Publication.Status.FAILED
        elif all(value == PublicationTarget.Status.SUCCEEDED for value in statuses):
            publication.status = Publication.Status.SUCCEEDED
        elif any(value == PublicationTarget.Status.SUBMITTED for value in statuses):
            publication.status = Publication.Status.RUNNING
        elif any(value == PublicationTarget.Status.SUCCEEDED for value in statuses) and all(
            value == PublicationTarget.Status.SUCCEEDED or value in terminal_non_success
            for value in statuses
        ):
            publication.status = Publication.Status.PARTIAL
        elif all(value in terminal_non_success for value in statuses):
            publication.status = Publication.Status.FAILED
        else:
            publication.status = Publication.Status.RUNNING
        publication.save(update_fields=("status", "updated_at"))


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
        if target.scheduled_at and target.scheduled_at > timezone.now():
            return {"status": "scheduled", "eta": target.scheduled_at}
        account = target.account
        if account is None or account.status != PlatformAccount.Status.CONNECTED or not account.enabled_for_auto:
            target.status = PublicationTarget.Status.AUTH_REQUIRED
            target.safe_error_code = "authorization_required"
            target.save(update_fields=("status", "safe_error_code", "updated_at"))
            _aggregate_publication(target.publication_id)
            return {"status": "auth_required"}
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
        credentials = decrypt_secret(target.account.secret_ciphertext if target.account else "")
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
        _aggregate_publication(target.publication_id)
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
        _aggregate_publication(target.publication_id)
        return {"status": "paused"}
    if target.platform_key in {"xiaohongshu", "douyin"} and not assets:
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.FAILED,
            safe_error_code="media_invalid",
        )
        _aggregate_publication(target.publication_id)
        return {"status": "failed"}

    text = _plain_text(target.adapted_content)
    try:
        result = publish_to_platform(
            platform_key=target.platform_key,
            target_id=str(target.pk),
            title=target.adapted_title,
            content_html=_simple_html(target.adapted_content),
            content_text=text,
            summary=text[:180],
            tags=[],
            assets=assets,
            credentials=credentials,
            publish_mode="public",
        )
    except PublishingWorkerError as exc:
        retryable = exc.code in {"worker_timeout", "worker_unavailable"}
        max_retries = int(getattr(settings, "PUBLISHING_TARGET_MAX_RETRIES", 3))
        if retryable and target.attempts < max_retries:
            PublicationTarget.objects.filter(pk=target.pk).update(
                status=PublicationTarget.Status.READY,
                safe_error_code="platform_unavailable",
            )
            return {"status": "retry", "retry_after": _TRANSIENT_RETRY_SECONDS}
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.PAUSED if exc.code == "platform_not_ready" else PublicationTarget.Status.FAILED,
            safe_error_code="platform_unavailable",
        )
        _aggregate_publication(target.publication_id)
        return {"status": "failed"}

    remote_status = str(result.get("status") or "failed")
    external_id = str(result.get("externalPostId") or "")[:255]
    management_url = str(result.get("managementUrl") or result.get("editUrl") or "")
    if bool(result.get("success")) and remote_status == "published" and result.get("publicUrl"):
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
        _aggregate_publication(target.publication_id)
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
        _aggregate_publication(target.publication_id)
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
        _aggregate_publication(target.publication_id)
        return {"status": "auth_required"}

    code = str(result.get("safeErrorCode") or "platform_unavailable")[:100]
    # 草稿成功或需要人工动作都不等于公开发布成功。
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
    _aggregate_publication(target.publication_id)
    return {"status": status}
