from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.articles.models import Article

from .models import Publication, PublishingPreference

logger = logging.getLogger(__name__)


def _create_managed_publication(article_id) -> None:
    from .services import PublishingInputError, create_publication
    from .tasks import prepare_publication_task

    try:
        article = Article.objects.select_related("user", "subject").get(pk=article_id)
    except Article.DoesNotExist:
        return
    if article.status != Article.Status.READY or article.moderation_status != Article.Moderation.PASSED:
        return
    preference = PublishingPreference.objects.filter(
        user=article.user,
        subject=article.subject,
        is_enabled=True,
        mode__in=(PublishingPreference.Mode.MANAGED, PublishingPreference.Mode.REVIEW),
    ).first()
    if preference is None:
        return
    if Publication.objects.filter(
        user=article.user,
        subject=article.subject,
        article=article,
    ).exclude(status=Publication.Status.CANCELLED).exists():
        return
    try:
        publication = create_publication(
            user=article.user,
            subject_id=article.subject_id,
            article_id=article.pk,
            platform_keys=None,
            scheduled_at=None,
        )
    except PublishingInputError:
        # 没有已授权平台等属于当前业务状态，不应影响文章生成成功。
        return
    prepare_publication_task.delay(str(publication.pk))


@receiver(post_save, sender=Article, dispatch_uid="publishing.auto_queue_ready_article")
def queue_ready_article(sender, instance: Article, **kwargs) -> None:
    if instance.status != Article.Status.READY or instance.moderation_status != Article.Moderation.PASSED:
        return
    article_id = instance.pk
    transaction.on_commit(lambda: _create_managed_publication(article_id))
