from __future__ import annotations

import os
from datetime import timedelta

from celery import shared_task  # type: ignore[import-untyped]
from django.utils import timezone

from .execution import prepare_publication
from .recovery import recover_preparation_jobs
from .review import hold_publication_for_review, should_hold_for_review
from .scheduling import assign_publication_schedule
from .status_tracking import check_submitted_target
from .target_execution import execute_target


def _running_stale_seconds() -> int:
    try:
        value = int(os.getenv("PUBLISHING_RUNNING_STALE_SECONDS", "420"))
    except ValueError:
        value = 420
    # Must remain above the dedicated publishing.execute_target hard time limit.
    return max(390, min(3600, value))


def _automation_enabled_for_publication(publication_id: str) -> bool:
    from .models import Publication, PublishingPreference

    publication = Publication.objects.only("user_id", "subject_id").filter(pk=publication_id).first()
    if publication is None:
        return False
    return PublishingPreference.objects.filter(
        user_id=publication.user_id,
        subject_id=publication.subject_id,
        is_enabled=True,
    ).exists()


def _pause_publication_subject(publication_id: str) -> None:
    from .models import Publication
    from .pause_control import pause_subject_publications

    publication = Publication.objects.only("user_id", "subject_id").filter(pk=publication_id).first()
    if publication is None:
        return
    pause_subject_publications(
        user_id=publication.user_id,
        subject_id=publication.subject_id,
    )


@shared_task(name="publishing.sync_authorization_session", bind=True, ignore_result=True)
def sync_authorization_session_task(self, session_id: str):
    from .authorization import sync_authorization_session
    from .models import PlatformAccount, PlatformAuthorizationSession

    try:
        session = PlatformAuthorizationSession.objects.select_related("account").get(pk=session_id)
    except PlatformAuthorizationSession.DoesNotExist:
        return None
    if session.auth_method == PlatformAccount.AuthMethod.OFFICIAL_API:
        # Official authorization completes through the signed platform callback.
        return None
    session = sync_authorization_session(session)
    if session.status in {
        PlatformAuthorizationSession.Status.CREATED,
        PlatformAuthorizationSession.Status.STARTING,
        PlatformAuthorizationSession.Status.WAITING_USER,
    } and session.expires_at > timezone.now():
        self.apply_async(args=[session_id], countdown=3)
    return None


@shared_task(name="publishing.prepare_publication", bind=True, ignore_result=True)
def prepare_publication_task(self, publication_id: str):
    # The user may disable automation while a previous preparation retry is already
    # queued. Stop before creating more adaptation/image work in that case.
    if not _automation_enabled_for_publication(publication_id):
        _pause_publication_subject(publication_id)
        return None

    recover_preparation_jobs(publication_id)
    result = prepare_publication(publication_id=publication_id)

    # Preparation can take long enough for the user to turn automation off while AI
    # image/content jobs are running. Check again before rescheduling or publishing.
    if not _automation_enabled_for_publication(publication_id):
        _pause_publication_subject(publication_id)
        return None

    if result.get("status") == "waiting":
        self.apply_async(
            args=[publication_id],
            countdown=max(2, min(30, int(result.get("retry_after") or 4))),
        )
        return None
    if result.get("status") == "ready":
        from .models import Publication, PublicationTarget

        publication = Publication.objects.select_related("user", "subject").get(pk=publication_id)
        if should_hold_for_review(publication):
            hold_publication_for_review(publication_id)
            return None

        base_time = assign_publication_schedule(publication_id)
        targets = list(
            PublicationTarget.objects.filter(
                publication_id=publication_id,
                status=PublicationTarget.Status.READY,
            )
            .only("id", "scheduled_at", "platform_key")
            .order_by("platform_key", "id")
        )
        for index, target in enumerate(targets):
            eta = target.scheduled_at or (base_time + timedelta(minutes=35 * index))
            if target.scheduled_at is None:
                PublicationTarget.objects.filter(pk=target.pk).update(scheduled_at=eta)
            execute_publication_target_task.apply_async(args=[str(target.pk)], eta=eta)
    return None


@shared_task(name="publishing.execute_target", bind=True, ignore_result=True)
def execute_publication_target_task(self, target_id: str):
    result = execute_target(target_id=target_id)
    if result.get("status") == "scheduled" and result.get("eta") is not None:
        self.apply_async(args=[target_id], eta=result["eta"])
    elif result.get("status") == "retry":
        self.apply_async(
            args=[target_id],
            countdown=max(30, min(900, int(result.get("retry_after") or 75))),
        )
    elif result.get("status") == "submitted":
        from .models import PublicationTarget

        target = PublicationTarget.objects.only("next_status_check_at").get(pk=target_id)
        if target.next_status_check_at is not None:
            check_submitted_target_task.apply_async(args=[target_id], eta=target.next_status_check_at)
    return None


@shared_task(name="publishing.check_submitted_target", bind=True, ignore_result=True)
def check_submitted_target_task(self, target_id: str):
    result = check_submitted_target(target_id=target_id)
    eta = result.get("eta")
    if result.get("status") in {"scheduled", "submitted"} and eta is not None:
        self.apply_async(args=[target_id], eta=eta)
    return None


@shared_task(name="publishing.recover_interrupted", ignore_result=True)
def recover_interrupted_publishing_task():
    from .models import Publication, PublicationTarget
    from .publication_state import aggregate_publication

    now = timezone.now()
    stale = now - timedelta(minutes=2)
    publication_ids = list(
        Publication.objects.filter(
            status__in=(Publication.Status.PREPARING, Publication.Status.QUEUED),
            updated_at__lte=stale,
        )
        .exclude(
            targets__status=PublicationTarget.Status.PAUSED,
            targets__safe_error_code="awaiting_review",
        )
        .values_list("id", flat=True)[:100]
    )
    for publication_id in publication_ids:
        prepare_publication_task.delay(str(publication_id))

    # A stale RUNNING target may have already reached the external platform before
    # the Celery process died. Replaying it can duplicate a public article, so fail
    # closed: pause it for result verification instead of automatically publishing again.
    stale_running = now - timedelta(seconds=_running_stale_seconds())
    stale_targets = list(
        PublicationTarget.objects.filter(
            status=PublicationTarget.Status.RUNNING,
            updated_at__lte=stale_running,
        ).values_list("id", "publication_id")[:100]
    )
    for target_id, publication_id in stale_targets:
        updated = PublicationTarget.objects.filter(
            pk=target_id,
            status=PublicationTarget.Status.RUNNING,
        ).update(
            status=PublicationTarget.Status.PAUSED,
            safe_error_code="publish_result_unconfirmed",
        )
        if updated:
            aggregate_publication(publication_id)

    due_target_ids = list(
        PublicationTarget.objects.filter(
            status=PublicationTarget.Status.SUBMITTED,
            next_status_check_at__isnull=False,
            next_status_check_at__lte=now,
        )
        .values_list("id", flat=True)[:100]
    )
    for target_id in due_target_ids:
        check_submitted_target_task.delay(str(target_id))
    return None


@shared_task(name="publishing.adopt_ready_articles", ignore_result=True)
def adopt_ready_articles_task(user_id: str, subject_id: str):
    from apps.articles.models import Article

    from .models import Publication, PublishingPreference
    from .services import PublishingInputError, create_publication

    preference = PublishingPreference.objects.filter(
        user_id=user_id,
        subject_id=subject_id,
        is_enabled=True,
        mode__in=(PublishingPreference.Mode.MANAGED, PublishingPreference.Mode.REVIEW),
    ).first()
    if preference is None:
        return None

    limit = max(
        1,
        min(
            10,
            preference.posts_per_day
            if preference.frequency_mode == PublishingPreference.FrequencyMode.FIXED
            else 3,
        ),
    )
    candidates = Article.objects.filter(
        user_id=user_id,
        subject_id=subject_id,
        status=Article.Status.READY,
        moderation_status=Article.Moderation.PASSED,
    ).order_by("-updated_at")[: limit * 3]
    adopted = 0
    for article in candidates:
        if adopted >= limit:
            break
        if Publication.objects.filter(
            user_id=user_id,
            subject_id=subject_id,
            article=article,
        ).exclude(status=Publication.Status.CANCELLED).exists():
            continue
        try:
            publication = create_publication(
                user=article.user,
                subject_id=subject_id,
                article_id=article.pk,
                platform_keys=None,
                scheduled_at=None,
            )
        except PublishingInputError:
            continue
        prepare_publication_task.delay(str(publication.pk))
        adopted += 1
    return None
