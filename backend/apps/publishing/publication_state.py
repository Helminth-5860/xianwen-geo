from __future__ import annotations

from django.db import transaction

from .models import Publication, PublicationTarget


@transaction.atomic
def aggregate_publication(publication_id) -> str:
    publication = Publication.objects.select_for_update().get(pk=publication_id)
    if publication.status == Publication.Status.CANCELLED:
        return publication.status

    rows = list(publication.targets.values_list("status", "safe_error_code"))
    statuses = [status for status, _code in rows]

    if not statuses:
        next_status = Publication.Status.FAILED
    elif all(status == PublicationTarget.Status.SUCCEEDED for status in statuses):
        next_status = Publication.Status.SUCCEEDED
    elif any(
        status in {PublicationTarget.Status.RUNNING, PublicationTarget.Status.SUBMITTED}
        for status in statuses
    ):
        next_status = Publication.Status.RUNNING
    elif any(status == PublicationTarget.Status.SUCCEEDED for status in statuses):
        # Some channels have already published. Remaining queued targets mean the
        # publication is still progressing; otherwise the finished subset is partial.
        if any(
            status in {PublicationTarget.Status.WAITING, PublicationTarget.Status.READY}
            for status in statuses
        ):
            next_status = Publication.Status.RUNNING
        else:
            next_status = Publication.Status.PARTIAL
    elif any(
        status in {PublicationTarget.Status.WAITING, PublicationTarget.Status.READY}
        for status in statuses
    ):
        next_status = Publication.Status.QUEUED
    elif any(status == PublicationTarget.Status.PAUSED for status in statuses):
        # A deliberate/global/platform/health pause is resumable and must never be
        # collapsed into a permanent failure merely because every target is paused.
        next_status = Publication.Status.PAUSED
    else:
        next_status = Publication.Status.FAILED

    if publication.status != next_status:
        publication.status = next_status
        publication.save(update_fields=("status", "updated_at"))
    return next_status
