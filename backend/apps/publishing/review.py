from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Publication, PublicationTarget, PublishingPreference
from .scheduling import assign_publication_schedule


AWAITING_REVIEW_CODE = "awaiting_review"


def should_hold_for_review(publication: Publication) -> bool:
    preference = PublishingPreference.objects.filter(
        user=publication.user,
        subject=publication.subject,
        is_enabled=True,
        mode=PublishingPreference.Mode.REVIEW,
    ).first()
    return preference is not None


@transaction.atomic
def hold_publication_for_review(publication_id) -> Publication:
    publication = Publication.objects.select_for_update().get(pk=publication_id)
    PublicationTarget.objects.filter(
        publication=publication,
        status=PublicationTarget.Status.READY,
    ).update(
        status=PublicationTarget.Status.PAUSED,
        safe_error_code=AWAITING_REVIEW_CODE,
    )
    publication.status = Publication.Status.QUEUED
    publication.save(update_fields=("status", "updated_at"))
    return publication


def is_waiting_review(publication: Publication) -> bool:
    return publication.targets.filter(
        status=PublicationTarget.Status.PAUSED,
        safe_error_code=AWAITING_REVIEW_CODE,
    ).exists()


@transaction.atomic
def approve_publication(*, user, publication_id) -> Publication:
    publication = get_object_or_404(
        Publication.objects.select_for_update().select_related("subject"),
        pk=publication_id,
        user=user,
    )
    if publication.status in {
        Publication.Status.CANCELLED,
        Publication.Status.SUCCEEDED,
        Publication.Status.FAILED,
    }:
        return publication

    targets = list(
        PublicationTarget.objects.select_for_update()
        .filter(
            publication=publication,
            status=PublicationTarget.Status.PAUSED,
            safe_error_code=AWAITING_REVIEW_CODE,
        )
        .order_by("platform_key", "id")
    )
    if not targets:
        return publication

    base_time = assign_publication_schedule(publication.pk)
    now = timezone.now()
    scheduled: list[tuple[str, object]] = []
    for index, target in enumerate(targets):
        eta = target.scheduled_at or (base_time + timedelta(minutes=35 * index))
        if eta < now:
            eta = now + timedelta(seconds=10 + index * 5)
        target.status = PublicationTarget.Status.READY
        target.safe_error_code = ""
        target.scheduled_at = eta
        target.save(update_fields=("status", "safe_error_code", "scheduled_at", "updated_at"))
        scheduled.append((str(target.pk), eta))

    publication.status = Publication.Status.QUEUED
    publication.save(update_fields=("status", "updated_at"))

    def enqueue() -> None:
        from .tasks import execute_publication_target_task

        for target_id, eta in scheduled:
            execute_publication_target_task.apply_async(args=[target_id], eta=eta)

    transaction.on_commit(enqueue)
    return publication
