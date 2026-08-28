from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Publication, PublicationTarget


AUTOMATION_PAUSED_CODE = "automation_paused"


@transaction.atomic
def pause_subject_publications(*, user_id, subject_id) -> int:
    publication_ids = list(
        Publication.objects.filter(
            user_id=user_id,
            subject_id=subject_id,
            status__in=(
                Publication.Status.PREPARING,
                Publication.Status.QUEUED,
                Publication.Status.RUNNING,
            ),
        ).values_list("id", flat=True)
    )
    if not publication_ids:
        return 0
    return PublicationTarget.objects.filter(
        publication_id__in=publication_ids,
        status__in=(
            PublicationTarget.Status.WAITING,
            PublicationTarget.Status.READY,
            PublicationTarget.Status.FAILED,
        ),
    ).update(
        status=PublicationTarget.Status.PAUSED,
        safe_error_code=AUTOMATION_PAUSED_CODE,
    )


@transaction.atomic
def resume_subject_publications(*, user_id, subject_id) -> int:
    targets = list(
        PublicationTarget.objects.select_for_update()
        .filter(
            publication__user_id=user_id,
            publication__subject_id=subject_id,
            publication__status__in=(
                Publication.Status.PREPARING,
                Publication.Status.QUEUED,
                Publication.Status.RUNNING,
                Publication.Status.PARTIAL,
            ),
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
    for index, target in enumerate(targets):
        target.status = PublicationTarget.Status.READY
        target.safe_error_code = ""
        if target.scheduled_at is None or target.scheduled_at <= now:
            target.scheduled_at = now + timedelta(seconds=15 + index * 10)
        target.save(update_fields=("status", "safe_error_code", "scheduled_at", "updated_at"))
        scheduled.append((str(target.pk), target.scheduled_at))

    def enqueue() -> None:
        from .tasks import execute_publication_target_task

        for target_id, eta in scheduled:
            execute_publication_target_task.apply_async(args=[target_id], eta=eta)

    transaction.on_commit(enqueue)
    return len(targets)
