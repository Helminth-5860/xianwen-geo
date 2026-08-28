from __future__ import annotations

from celery import shared_task  # type: ignore[import-untyped]

from .execution import execute_target, prepare_publication


@shared_task(name="publishing.prepare_publication", bind=True, ignore_result=True)
def prepare_publication_task(self, publication_id: str):
    result = prepare_publication(publication_id=publication_id)
    if result.get("status") == "waiting":
        self.apply_async(
            args=[publication_id],
            countdown=max(2, min(30, int(result.get("retry_after") or 4))),
        )
        return None
    if result.get("status") == "ready":
        from .models import PublicationTarget

        targets = PublicationTarget.objects.filter(
            publication_id=publication_id,
            status=PublicationTarget.Status.READY,
        ).only("id", "scheduled_at")
        for target in targets:
            if target.scheduled_at:
                execute_publication_target_task.apply_async(args=[str(target.pk)], eta=target.scheduled_at)
            else:
                execute_publication_target_task.delay(str(target.pk))
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
    return None
