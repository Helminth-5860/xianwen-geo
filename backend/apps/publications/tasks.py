from __future__ import annotations

import logging

from celery import shared_task  # type: ignore[import-untyped]
from django.db import transaction
from django.utils import timezone

from .browser import (
    PublicationAuthorizationRequired,
    PublicationBrowserFailed,
    PublicationBrowserUnavailable,
    execute_browser_authorization,
    publish_browser_target,
)
from .models import (
    AuthorizationSession,
    PlatformAccount,
    PublicationJob,
    PublicationPlatform,
    PublicationTarget,
)
from .services import (
    PublicationInputError,
    decrypt_account_state,
    prepare_publication_job,
    refresh_publication_job,
)
from .wechat import (
    WeChatCredentialError,
    WeChatPublishError,
    publish_wechat_target,
    validate_wechat_credentials,
)

logger = logging.getLogger(__name__)


def _platform_failure(platform: PublicationPlatform):
    failures = platform.consecutive_failures + 1
    health = platform.health_status
    if failures >= 8:
        health = PublicationPlatform.HealthStatus.UNAVAILABLE
    elif failures >= 3:
        health = PublicationPlatform.HealthStatus.DEGRADED
    PublicationPlatform.objects.filter(pk=platform.pk).update(
        consecutive_failures=failures,
        health_status=health,
        last_failure_at=timezone.now(),
        last_checked_at=timezone.now(),
        updated_at=timezone.now(),
    )


def _platform_success(platform: PublicationPlatform):
    PublicationPlatform.objects.filter(pk=platform.pk).update(
        consecutive_failures=0,
        health_status=PublicationPlatform.HealthStatus.HEALTHY,
        last_success_at=timezone.now(),
        last_checked_at=timezone.now(),
        updated_at=timezone.now(),
    )


def _mark_authorization_failed(session: AuthorizationSession, code: str, *, needs_verification=False):
    status = (
        AuthorizationSession.Status.NEEDS_INTERACTION
        if needs_verification
        else AuthorizationSession.Status.FAILED
    )
    account_status = (
        PlatformAccount.AuthStatus.NEEDS_VERIFICATION
        if needs_verification
        else PlatformAccount.AuthStatus.FAILED
    )
    AuthorizationSession.objects.filter(pk=session.pk).update(
        status=status,
        safe_error_code=code,
        login_snapshot_data_url="",
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )
    if session.account_id:
        PlatformAccount.objects.filter(pk=session.account_id).update(
            auth_status=account_status,
            updated_at=timezone.now(),
        )


@shared_task(
    name="publications.execute_authorization_session",
    ignore_result=True,
    soft_time_limit=350,
    time_limit=370,
)
def execute_authorization_session_task(session_id: str):
    try:
        session = AuthorizationSession.objects.select_related(
            "platform__channel", "account"
        ).get(pk=session_id)
    except AuthorizationSession.DoesNotExist:
        return {"status": "missing"}
    if session.status != AuthorizationSession.Status.QUEUED:
        return {"status": session.status}
    if session.platform.auth_mode == PublicationPlatform.AuthMode.OFFICIAL_CREDENTIALS:
        try:
            if session.account is None:
                raise PublicationInputError("PUBLICATION_ACCOUNT_NOT_FOUND")
            state = decrypt_account_state(session.account)
            validate_wechat_credentials(state)
        except (PublicationInputError, WeChatCredentialError, WeChatPublishError):
            _mark_authorization_failed(session, "PUBLICATION_CREDENTIAL_VALIDATION_FAILED")
            return {"status": "failed"}
        now = timezone.now()
        PlatformAccount.objects.filter(pk=session.account_id).update(
            auth_status=PlatformAccount.AuthStatus.AUTHORIZED,
            authorized_at=now,
            last_auth_check_at=now,
            enabled_for_auto_publish=True,
            updated_at=now,
        )
        AuthorizationSession.objects.filter(pk=session.pk).update(
            status=AuthorizationSession.Status.AUTHORIZED,
            safe_error_code="",
            login_snapshot_data_url="",
            started_at=now,
            finished_at=now,
            updated_at=now,
        )
        _platform_success(session.platform)
        return {"status": "authorized"}
    try:
        result = execute_browser_authorization(str(session.pk))
    except PublicationBrowserUnavailable:
        _mark_authorization_failed(session, "PUBLICATION_BROWSER_WORKER_UNAVAILABLE")
        _platform_failure(session.platform)
        return {"status": "failed"}
    if result.get("status") == "authorized":
        _platform_success(session.platform)
    return result


@shared_task(name="publications.prepare_job", ignore_result=True)
def prepare_publication_job_task(job_id: str):
    return prepare_publication_job(job_id)


@shared_task(name="publications.refresh_job", ignore_result=True)
def refresh_publication_job_task(job_id: str):
    return refresh_publication_job(job_id)


def _finalize_parent(job_id):
    with transaction.atomic():
        try:
            job = PublicationJob.objects.select_for_update().get(pk=job_id)
        except PublicationJob.DoesNotExist:
            return
        if job.status in {
            PublicationJob.Status.SUCCEEDED,
            PublicationJob.Status.PARTIAL,
            PublicationJob.Status.FAILED,
            PublicationJob.Status.CANCELLED,
        }:
            return
        statuses = list(job.targets.values_list("status", flat=True))
        terminal = {
            PublicationTarget.Status.PUBLISHED,
            PublicationTarget.Status.FAILED,
            PublicationTarget.Status.REQUIRES_AUTH,
            PublicationTarget.Status.SKIPPED,
        }
        if not statuses or any(value not in terminal for value in statuses):
            return
        published = sum(value == PublicationTarget.Status.PUBLISHED for value in statuses)
        if published == len(statuses):
            job.status = PublicationJob.Status.SUCCEEDED
        elif published:
            job.status = PublicationJob.Status.PARTIAL
        else:
            job.status = PublicationJob.Status.FAILED
        job.finished_at = timezone.now()
        job.save(update_fields=("status", "finished_at", "updated_at"))


def _requires_auth(target: PublicationTarget, code: str):
    PlatformAccount.objects.filter(pk=target.account_id).update(
        auth_status=PlatformAccount.AuthStatus.EXPIRED,
        enabled_for_auto_publish=False,
        last_auth_check_at=timezone.now(),
        updated_at=timezone.now(),
    )
    PublicationTarget.objects.filter(pk=target.pk).update(
        status=PublicationTarget.Status.REQUIRES_AUTH,
        safe_error_code=code,
        updated_at=timezone.now(),
    )


def _mark_target_failed(target: PublicationTarget, code: str):
    PublicationTarget.objects.filter(pk=target.pk).update(
        status=PublicationTarget.Status.FAILED,
        safe_error_code=code,
        updated_at=timezone.now(),
    )
    _platform_failure(target.platform)


@shared_task(
    name="publications.execute_target",
    ignore_result=True,
    soft_time_limit=170,
    time_limit=190,
)
def execute_publication_target_task(target_id: str):
    with transaction.atomic():
        try:
            target = (
                PublicationTarget.objects.select_for_update()
                .select_related("job", "job__article", "platform__channel", "account")
                .get(pk=target_id)
            )
        except PublicationTarget.DoesNotExist:
            return {"status": "missing"}
        if target.status not in {
            PublicationTarget.Status.SCHEDULED,
            PublicationTarget.Status.PUBLISHING,
        }:
            return {"status": target.status}
        if target.account.auth_status != PlatformAccount.AuthStatus.AUTHORIZED:
            _requires_auth(target, "PUBLICATION_ACCOUNT_AUTH_EXPIRED")
            transaction.on_commit(lambda: _finalize_parent(target.job_id))
            return {"status": "requires_auth"}
        target.status = PublicationTarget.Status.PUBLISHING
        target.attempts += 1
        target.save(update_fields=("status", "attempts", "updated_at"))

    try:
        state = decrypt_account_state(target.account)
        if target.platform.publish_mode == PublicationPlatform.PublishMode.OFFICIAL_API:
            result = publish_wechat_target(target, state)
            if result.status == "pending":
                PublicationTarget.objects.filter(pk=target.pk).update(
                    external_post_id=result.external_post_id,
                    status=PublicationTarget.Status.PUBLISHING,
                    safe_error_code="",
                    updated_at=timezone.now(),
                )
                execute_publication_target_task.apply_async(
                    args=[str(target.pk)], countdown=30, queue="publication"
                )
                return {"status": "publishing"}
            public_url = result.public_url
            external_post_id = result.external_post_id
        else:
            result = publish_browser_target(target, state)
            public_url = result.public_url
            external_post_id = result.external_post_id
    except (PublicationAuthorizationRequired, WeChatCredentialError):
        _requires_auth(target, "PUBLICATION_ACCOUNT_AUTH_EXPIRED")
        _platform_failure(target.platform)
        _finalize_parent(target.job_id)
        return {"status": "requires_auth"}
    except PublicationBrowserUnavailable:
        _mark_target_failed(target, "PUBLICATION_BROWSER_WORKER_UNAVAILABLE")
        _finalize_parent(target.job_id)
        return {"status": "failed"}
    except (PublicationBrowserFailed, WeChatPublishError):
        _mark_target_failed(target, "PUBLICATION_PLATFORM_SUBMISSION_FAILED")
        _finalize_parent(target.job_id)
        return {"status": "failed"}
    except Exception:
        logger.exception(
            "publication target execution failed", extra={"context": {"target_id": str(target.pk)}}
        )
        _mark_target_failed(target, "PUBLICATION_TEMPORARILY_UNAVAILABLE")
        _finalize_parent(target.job_id)
        return {"status": "failed"}

    now = timezone.now()
    PublicationTarget.objects.filter(pk=target.pk).update(
        status=PublicationTarget.Status.PUBLISHED,
        public_url=public_url,
        external_post_id=external_post_id,
        published_at=now,
        safe_error_code="",
        updated_at=now,
    )
    PlatformAccount.objects.filter(pk=target.account_id).update(
        last_auth_check_at=now,
        updated_at=now,
    )
    _platform_success(target.platform)
    _finalize_parent(target.job_id)
    return {"status": "published", "public_url": public_url}


@shared_task(name="publications.dispatch_due_targets", ignore_result=True)
def dispatch_due_publication_targets_task():
    now = timezone.now()
    rows = list(
        PublicationTarget.objects.filter(
            status=PublicationTarget.Status.SCHEDULED,
            scheduled_at__lte=now,
        )
        .select_related("platform")
        .order_by("scheduled_at", "created_at")[:50]
    )
    for row in rows:
        execute_publication_target_task.apply_async(
            args=[str(row.pk)], queue="publication"
        )
    return {"dispatched": len(rows)}
