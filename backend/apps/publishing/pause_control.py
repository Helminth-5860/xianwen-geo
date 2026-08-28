from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Publication, PublicationTarget
from .publication_state import aggregate_publication


AUTOMATION_PAUSED_CODE = "automation_paused"
PLATFORM_DISABLED_CODE = "platform_disabled"


def _resumable_publication_statuses() -> tuple[str, ...]:
    return (
        Publication.Status.PREPARING,
        Publication.Status.QUEUED,
        Publication.Status.RUNNING,
        Publication.Status.PAUSED,
        Publication.Status.PARTIAL,
        # Older in-flight records may have been aggregated to failed before the
        # paused publication state existed. Target reason codes keep revival safe.
        Publication.Status.FAILED,
    )


def _enqueue_targets(scheduled: list[tuple[str, object]]) -> None:
    if not scheduled:
        return

    def enqueue() -> None:
        from .tasks import execute_publication_target_task

        for target_id, eta in scheduled:
            execute_publication_target_task.apply_async(args=[target_id], eta=eta)

    transaction.on_commit(enqueue)


@transaction.atomic
def pause_subject_publications(*, user_id, subject_id) -> int:
    publication_ids = list(
        Publication.objects.filter(
            user_id=user_id,
            subject_id=subject_id,
            status__in=_resumable_publication_statuses(),
        ).values_list("id", flat=True)
    )
    if not publication_ids:
        return 0

    updated = PublicationTarget.objects.filter(
        publication_id__in=publication_ids,
        status__in=(
            PublicationTarget.Status.WAITING,
            PublicationTarget.Status.READY,
        ),
    ).update(
        status=PublicationTarget.Status.PAUSED,
        safe_error_code=AUTOMATION_PAUSED_CODE,
    )
    for publication_id in publication_ids:
        aggregate_publication(publication_id)
    return updated


@transaction.atomic
def resume_subject_publications(*, user_id, subject_id) -> int:
    targets = list(
        PublicationTarget.objects.select_for_update()
        .filter(
            publication__user_id=user_id,
            publication__subject_id=subject_id,
            publication__status__in=_resumable_publication_statuses(),
            status=PublicationTarget.Status.PAUSED,
            safe_error_code=AUTOMATION_PAUSED_CODE,
        )
        .select_related("publication")
        .order_by("scheduled_at", "id")
    )
    if not targets:
        return 0

    now = timezone.now()
    scheduled: list[tuple[str, object]] = []
    publication_ids: set[object] = set()
    for index, target in enumerate(targets):
        target.status = PublicationTarget.Status.READY
        target.safe_error_code = ""
        if target.scheduled_at is None or target.scheduled_at <= now:
            target.scheduled_at = now + timedelta(seconds=15 + index * 10)
        target.save(update_fields=("status", "safe_error_code", "scheduled_at", "updated_at"))
        scheduled.append((str(target.pk), target.scheduled_at))
        publication_ids.add(target.publication_id)

    for publication_id in publication_ids:
        aggregate_publication(publication_id)
    _enqueue_targets(scheduled)
    return len(targets)


@transaction.atomic
def pause_platform_publications(*, user_id, subject_id, platform_key: str) -> int:
    targets = list(
        PublicationTarget.objects.select_for_update()
        .filter(
            publication__user_id=user_id,
            publication__subject_id=subject_id,
            publication__status__in=_resumable_publication_statuses(),
            platform_key=platform_key,
            status__in=(PublicationTarget.Status.WAITING, PublicationTarget.Status.READY),
        )
        .only("id", "publication_id")
    )
    if not targets:
        return 0
    target_ids = [target.pk for target in targets]
    PublicationTarget.objects.filter(pk__in=target_ids).update(
        status=PublicationTarget.Status.PAUSED,
        safe_error_code=PLATFORM_DISABLED_CODE,
    )
    for publication_id in {target.publication_id for target in targets}:
        aggregate_publication(publication_id)
    return len(targets)


@transaction.atomic
def resume_platform_publications(
    *, user_id, subject_id, platform_key: str, automation_enabled: bool
) -> int:
    targets = list(
        PublicationTarget.objects.select_for_update()
        .filter(
            publication__user_id=user_id,
            publication__subject_id=subject_id,
            publication__status__in=_resumable_publication_statuses(),
            platform_key=platform_key,
            status=PublicationTarget.Status.PAUSED,
            safe_error_code=PLATFORM_DISABLED_CODE,
        )
        .select_related("publication")
        .order_by("scheduled_at", "id")
    )
    if not targets:
        return 0

    publication_ids = {target.publication_id for target in targets}
    if not automation_enabled:
        PublicationTarget.objects.filter(pk__in=[target.pk for target in targets]).update(
            safe_error_code=AUTOMATION_PAUSED_CODE
        )
        for publication_id in publication_ids:
            aggregate_publication(publication_id)
        return len(targets)

    now = timezone.now()
    scheduled: list[tuple[str, object]] = []
    for index, target in enumerate(targets):
        target.status = PublicationTarget.Status.READY
        target.safe_error_code = ""
        if target.scheduled_at is None or target.scheduled_at <= now:
            target.scheduled_at = now + timedelta(seconds=15 + index * 10)
        target.save(update_fields=("status", "safe_error_code", "scheduled_at", "updated_at"))
        scheduled.append((str(target.pk), target.scheduled_at))

    for publication_id in publication_ids:
        aggregate_publication(publication_id)
    _enqueue_targets(scheduled)
    return len(targets)
