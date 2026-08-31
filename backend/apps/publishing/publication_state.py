from __future__ import annotations

import uuid

from django.db import transaction

from apps.quotas.services import consume_hold, release_hold

from .models import Publication, PublicationTarget


def _settle_publication(publication: Publication, *, consume: bool) -> None:
    if not publication.quota_hold_id:
        return
    operation = consume_hold if consume else release_hold
    action = "consume" if consume else "release"
    operation(
        hold_id=publication.quota_hold_id,
        amount=1,
        idempotency_key=f"auto-publish-{action}-{publication.pk}",
        request_id=publication.request_id or uuid.uuid4(),
    )


@transaction.atomic
def aggregate_publication(publication_id) -> str:
    publication = Publication.objects.select_for_update().get(pk=publication_id)
    rows = list(publication.targets.values_list("status", "safe_error_code"))
    statuses = [status for status, _code in rows]
    if publication.status == Publication.Status.CANCELLED:
        _settle_publication(
            publication,
            consume=any(status == PublicationTarget.Status.SUCCEEDED for status in statuses),
        )
        return publication.status

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
    if next_status in {Publication.Status.SUCCEEDED, Publication.Status.PARTIAL}:
        _settle_publication(publication, consume=True)
    elif next_status == Publication.Status.FAILED:
        _settle_publication(publication, consume=False)
    return next_status
