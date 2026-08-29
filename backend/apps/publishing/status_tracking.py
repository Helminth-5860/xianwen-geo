from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .credentials import PlatformCredentialRuntimeUnavailable, platform_credentials
from .models import PlatformAccount, PublicationTarget
from .publication_state import aggregate_publication
from .security import PublishingCredentialError
from .worker_client import PublishingWorkerError, check_platform_publication_status


def _next_check(target: PublicationTarget):
    submitted = target.submitted_at or target.updated_at
    age = max(timedelta(0), timezone.now() - submitted)
    if age < timedelta(hours=1):
        return timezone.now() + timedelta(minutes=15)
    if age < timedelta(hours=6):
        return timezone.now() + timedelta(minutes=30)
    if age < timedelta(hours=24):
        return timezone.now() + timedelta(hours=2)
    # 超过 24 小时仍无法确认时保持“平台审核中”，不误报失败，也不无限制造后台任务。
    return None


def check_submitted_target(*, target_id) -> dict:
    target = (
        PublicationTarget.objects.select_related(
            "publication",
            "publication__user",
            "publication__subject",
            "account",
        )
        .get(pk=target_id)
    )
    if target.status != PublicationTarget.Status.SUBMITTED:
        return {"status": target.status}
    if target.next_status_check_at and target.next_status_check_at > timezone.now():
        return {"status": "scheduled", "eta": target.next_status_check_at}
    if target.account is None or target.account.status != PlatformAccount.Status.CONNECTED:
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.AUTH_REQUIRED,
            safe_error_code="authorization_required",
            next_status_check_at=None,
        )
        aggregate_publication(target.publication_id)
        return {"status": "auth_required"}
    try:
        credentials = platform_credentials(target.account)
    except PlatformCredentialRuntimeUnavailable:
        # 微信第三方平台 ticket / 网络临时不可用，不代表客户授权失效。
        eta = _next_check(target)
        PublicationTarget.objects.filter(pk=target.pk).update(
            next_status_check_at=eta,
            safe_error_code="",
        )
        return {"status": "submitted", "eta": eta}
    except PublishingCredentialError:
        PlatformAccount.objects.filter(pk=target.account_id).update(
            status=PlatformAccount.Status.ACTION_REQUIRED,
            last_error_code="authorization_required",
            last_checked_at=timezone.now(),
        )
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.AUTH_REQUIRED,
            safe_error_code="authorization_required",
            next_status_check_at=None,
        )
        aggregate_publication(target.publication_id)
        return {"status": "auth_required"}

    try:
        result = check_platform_publication_status(
            platform_key=target.platform_key,
            external_post_id=target.external_post_id,
            management_url=target.management_url,
            expected_title=target.adapted_title,
            credentials=credentials,
        )
    except PublishingWorkerError:
        eta = _next_check(target)
        PublicationTarget.objects.filter(pk=target.pk).update(
            next_status_check_at=eta,
            safe_error_code="",
        )
        return {"status": "submitted", "eta": eta}

    status = str(result.get("status") or "unknown")
    management_url = str(result.get("managementUrl") or target.management_url or "")
    if status == "published" and result.get("publicUrl"):
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.SUCCEEDED,
            published_at=timezone.now(),
            public_url=str(result.get("publicUrl") or ""),
            management_url=management_url,
            next_status_check_at=None,
            safe_error_code="",
        )
        aggregate_publication(target.publication_id)
        return {"status": "succeeded"}
    if status == "failed":
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.FAILED,
            management_url=management_url,
            next_status_check_at=None,
            safe_error_code=str(result.get("safeErrorCode") or "content_rejected")[:100],
        )
        aggregate_publication(target.publication_id)
        return {"status": "failed"}
    if status == "auth_required":
        PlatformAccount.objects.filter(pk=target.account_id).update(
            status=PlatformAccount.Status.EXPIRED,
            last_error_code="authorization_required",
            last_checked_at=timezone.now(),
        )
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.AUTH_REQUIRED,
            management_url=management_url,
            next_status_check_at=None,
            safe_error_code="authorization_required",
        )
        aggregate_publication(target.publication_id)
        return {"status": "auth_required"}

    eta = _next_check(target)
    PublicationTarget.objects.filter(pk=target.pk).update(
        management_url=management_url,
        next_status_check_at=eta,
        safe_error_code="",
    )
    return {"status": "submitted", "eta": eta}
