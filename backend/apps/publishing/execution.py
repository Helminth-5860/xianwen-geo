from __future__ import annotations

import html
import re
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.articles.models import ChannelAdaptation, PublishingChannel
from apps.articles.services import ContentError, create_channel_jobs
from apps.articles.tasks import execute_generation_job_task
from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.storage import storage_provider
from apps.images.exceptions import ImageBusinessError, ImageInputInvalid, ImageRuntimeUnavailable
from apps.images.models import ImageAsset, ImageDerivative, ImageGenerationJob, ImageSizePreset, ImageStylePreset
from apps.images.services import create_derivative, create_image_job
from apps.images.tasks import execute_image_job_task

from .catalog import PLATFORM_BY_KEY
from .image_planning import build_image_plan
from .models import PlatformAccount, Publication, PublicationTarget, PublishingPreference
from .security import PublishingCredentialError, decrypt_secret
from .worker_client import PublishingWorkerError, publish_to_platform


_PREPARATION_RETRY_SECONDS = 4
_TRANSIENT_RETRY_SECONDS = 75
_TITLE_LIMITS = {
    "xiaohongshu": 20,
    "toutiao": 30,
    "douyin": 30,
    "weibo": 40,
    "wechat": 64,
    "baijiahao": 64,
    "bilibili": 64,
    "qq": 64,
    "sohu": 64,
    "juejin": 80,
    "zhihu": 80,
    "csdn": 100,
    "oschina": 100,
    "segmentfault": 100,
    "jianshu": 100,
    "douban": 100,
    "cnblogs": 120,
}
_TEXT_LIMITS = {"xiaohongshu": 1000, "douyin": 800}
_COVER_SIZES = {
    "wechat": (900, 383),
    "toutiao": (1200, 675),
    "baijiahao": (1200, 675),
    "zhihu": (1200, 675),
    "xiaohongshu": (1080, 1440),
    "weibo": (1080, 1080),
    "bilibili": (1200, 675),
    "douyin": (1080, 1440),
    "qq": (1200, 675),
    "sohu": (1200, 675),
    "csdn": (1200, 675),
    "juejin": (1200, 675),
    "cnblogs": (1200, 675),
    "oschina": (1200, 675),
    "segmentfault": (1200, 675),
    "jianshu": (1200, 675),
    "douban": (1200, 675),
}


def _plain_text(value: str) -> str:
    text = re.sub(r"```.*?```", "", value, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_~`>#-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _simple_html(value: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if not paragraph:
            return
        blocks.append(f"<p>{'<br/>'.join(html.escape(item) for item in paragraph)}</p>")
        paragraph.clear()

    for raw in value.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush()
            level = min(3, len(heading.group(1)) + 1)
            blocks.append(f"<h{level}>{html.escape(heading.group(2).strip())}</h{level}>")
            continue
        if line.startswith(("- ", "* ")):
            flush()
            blocks.append(f"<p>• {html.escape(line[2:].strip())}</p>")
            continue
        paragraph.append(line)
    flush()
    return "\n".join(blocks) or f"<p>{html.escape(value)}</p>"


def _fallback_adaptation(*, platform_key: str, title: str, content: str) -> tuple[str, str]:
    clean_title = " ".join(title.split())
    title_limit = _TITLE_LIMITS.get(platform_key, 100)
    if len(clean_title) > title_limit:
        clean_title = clean_title[: max(1, title_limit - 1)].rstrip("，。！？、；： ") + "…"
    clean_content = content.strip()
    text_limit = _TEXT_LIMITS.get(platform_key)
    if text_limit and len(_plain_text(clean_content)) > text_limit:
        compact = _plain_text(clean_content)[: max(1, text_limit - 1)].rstrip("，。！？、；： ")
        clean_content = compact + "…"
    return clean_title, clean_content


def _publication(publication_id) -> Publication:
    return (
        Publication.objects.select_related("user", "subject", "article")
        .prefetch_related("targets", "targets__account")
        .get(pk=publication_id)
    )


def _pick_preset(role: str):
    sizes = list(ImageSizePreset.objects.filter(status="active").order_by("sort_order", "key"))
    styles = list(ImageStylePreset.objects.filter(status="active").order_by("sort_order", "key"))
    size = next((item for item in sizes if not item.applicable_roles or role in item.applicable_roles), None)
    style = next((item for item in styles if not item.applicable_roles or role in item.applicable_roles), None)
    return size, style


def _supplement_prompt(*, article_title: str, purpose: str, index: int) -> str:
    if purpose == "cover":
        return (
            f"为企业知识文章《{article_title[:120]}》生成专业封面视觉。"
            "使用抽象概念、业务元素或信息视觉表达主题，画面简洁、可用于企业内容发布。"
            "不得生成或暗示企业真实团队、真实工厂、真实产品实物、真实客户案例、证书、奖项或未经提供的品牌事实。"
        )
    if purpose == "information":
        return (
            f"为企业知识文章《{article_title[:120]}》生成第{index + 1}张简洁信息图背景或流程视觉。"
            "重点帮助理解概念和步骤，不虚构数据、客户、资质或企业现实场景，不在图片内生成无法核验的文字事实。"
        )
    return (
        f"为企业知识文章《{article_title[:120]}》生成第{index + 1}张正文概念插图。"
        "视觉需要与文章主题相关、专业克制，可表现抽象概念或通用业务场景。"
        "不得冒充企业真实团队、工厂、产品实物、案例现场、证书或奖项。"
    )


def _ensure_image_supplements(publication: Publication, plan: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    missing = list(plan.get("missing_assets") or [])
    if not missing or not plan.get("allow_ai_supplement"):
        return plan, True

    previous_ids = [str(item) for item in plan.get("supplement_job_ids") or []]
    if previous_ids:
        jobs = list(ImageGenerationJob.objects.filter(pk__in=previous_ids))
        if any(job.status in {ImageGenerationJob.Status.QUEUED, ImageGenerationJob.Status.RUNNING, ImageGenerationJob.Status.RETRY_WAIT} for job in jobs):
            return plan, False
        rebuilt = build_image_plan(
            user=publication.user,
            subject=publication.subject,
            article=publication.article,
            strategy=publication.image_strategy,
            density=(plan.get("density") or PublishingPreference.ImageDensity.STANDARD),
        )
        rebuilt["supplement_job_ids"] = previous_ids
        rebuilt["supplement_attempted"] = True
        if rebuilt.get("missing_assets"):
            rebuilt["supplement_incomplete"] = True
        return rebuilt, True

    created_ids: list[str] = []
    for missing_group in missing:
        purpose = str(missing_group.get("purpose") or "inline")
        count = max(0, min(6, int(missing_group.get("count") or 0)))
        role = ImageGenerationJob.Role.COVER if purpose == "cover" else ImageGenerationJob.Role.ILLUSTRATION
        size, style = _pick_preset(role)
        if size is None or style is None:
            continue
        for index in range(count):
            try:
                job, created = create_image_job(
                    user=publication.user,
                    subject_id=publication.subject_id,
                    article_id=publication.article_id,
                    role=role,
                    prompt=_supplement_prompt(article_title=publication.source_title, purpose=purpose, index=index),
                    size_preset_id=size.pk,
                    style_preset_id=style.pk,
                    reference_asset_id=None,
                    reference_document_version_id=None,
                    reference_url="",
                    idempotency_key=f"publishing:{publication.pk}:image:{purpose}:{index}",
                    request_id=uuid.uuid4(),
                )
            except (ImageBusinessError, ImageInputInvalid, ImageRuntimeUnavailable):
                continue
            created_ids.append(str(job.pk))
            if created:
                execute_image_job_task.delay(str(job.pk))

    plan["supplement_job_ids"] = created_ids
    plan["supplement_attempted"] = True
    if not created_ids:
        plan["supplement_incomplete"] = True
        return plan, True
    return plan, False


def _ensure_adaptations(publication: Publication) -> tuple[dict[str, ChannelAdaptation], bool]:
    targets = list(publication.targets.all())
    keys = [target.platform_key for target in targets if target.status != PublicationTarget.Status.AUTH_REQUIRED]
    channels = {item.key: item for item in PublishingChannel.objects.filter(key__in=keys, enabled=True)}
    if not channels:
        return {}, True

    try:
        rows = create_channel_jobs(
            user=publication.user,
            article_id=publication.article_id,
            channel_ids=[channel.pk for channel in channels.values()],
            idempotency_key=f"publishing-{publication.pk}-adapt",
            request_id=uuid.uuid4(),
        )
    except ContentError:
        return {}, True

    adaptation_by_key: dict[str, ChannelAdaptation] = {}
    waiting = False
    for adaptation, job, created in rows:
        key = adaptation.channel.key
        adaptation_by_key[key] = adaptation
        if created:
            execute_generation_job_task.delay(str(job.pk))
            waiting = True
            continue
        if job.status in {"queued", "running"}:
            waiting = True
    return adaptation_by_key, not waiting


def _ready_adaptations(publication: Publication) -> tuple[dict[str, ChannelAdaptation], bool]:
    rows = list(
        ChannelAdaptation.objects.filter(
            article=publication.article,
            job__idempotency_key_digest__isnull=False,
            channel__key__in=[item.platform_key for item in publication.targets.all()],
        )
        .select_related("channel", "job")
        .order_by("-created_at")
    )
    latest: dict[str, ChannelAdaptation] = {}
    for row in rows:
        latest.setdefault(row.channel.key, row)
    pending = any(row.status in {ChannelAdaptation.Status.QUEUED, ChannelAdaptation.Status.RUNNING} for row in latest.values())
    return latest, not pending


def _cover_derivative(publication: Publication, platform_key: str, asset_id: str) -> str | None:
    size = _COVER_SIZES.get(platform_key)
    if size is None:
        return None
    try:
        image = ImageAsset.objects.get(
            pk=asset_id,
            user=publication.user,
            subject=publication.subject,
            lifecycle_status=ImageAsset.LifecycleStatus.ACTIVE,
            moderation_status=ImageAsset.ModerationStatus.APPROVED,
        )
    except ImageAsset.DoesNotExist:
        return None
    for row in image.derivatives.filter(kind=ImageDerivative.Kind.CHANNEL).order_by("-created_at"):
        if row.width == size[0] and row.height == size[1] and row.mime_type == "image/jpeg":
            return str(row.pk)
    try:
        row = create_derivative(
            user=publication.user,
            image_id=image.pk,
            kind=ImageDerivative.Kind.CHANNEL,
            width=size[0],
            height=size[1],
            output_format="jpeg",
        )
    except (ImageBusinessError, ImageInputInvalid, ImageRuntimeUnavailable):
        return None
    return str(row.pk)


def _assign_target_payloads(publication: Publication, image_plan: dict[str, Any], adaptations: dict[str, ChannelAdaptation]) -> None:
    selected_assets = list(image_plan.get("selected_assets") or [])
    with transaction.atomic():
        targets = list(PublicationTarget.objects.select_for_update().filter(publication=publication))
        for target in targets:
            if target.status == PublicationTarget.Status.AUTH_REQUIRED:
                continue
            adaptation = adaptations.get(target.platform_key)
            if adaptation is not None and adaptation.status == ChannelAdaptation.Status.READY:
                title, content = adaptation.title, adaptation.content
            else:
                title, content = _fallback_adaptation(
                    platform_key=target.platform_key,
                    title=publication.source_title,
                    content=publication.article.content,
                )
            media: list[dict[str, Any]] = []
            for item in selected_assets:
                asset_id = str(item.get("asset_id") or "")
                purpose = str(item.get("purpose") or "inline")
                if not asset_id:
                    continue
                entry: dict[str, Any] = {"asset_id": asset_id, "purpose": purpose}
                if purpose == "cover":
                    derivative_id = _cover_derivative(publication, target.platform_key, asset_id)
                    if derivative_id:
                        entry["derivative_id"] = derivative_id
                media.append(entry)
            target.adapted_title = title
            target.adapted_content = content
            target.media_payload = {
                "assets": media,
                "image_plan_status": image_plan.get("status"),
                "supplement_incomplete": bool(image_plan.get("supplement_incomplete")),
            }
            target.status = PublicationTarget.Status.READY
            target.safe_error_code = ""
            target.save(update_fields=("adapted_title", "adapted_content", "media_payload", "status", "safe_error_code", "updated_at"))

        publication.image_plan = image_plan
        publication.status = Publication.Status.QUEUED
        publication.save(update_fields=("image_plan", "status", "updated_at"))


def prepare_publication(*, publication_id) -> dict[str, Any]:
    publication = _publication(publication_id)
    if publication.status in {Publication.Status.CANCELLED, Publication.Status.SUCCEEDED, Publication.Status.FAILED}:
        return {"status": publication.status}

    if publication.status != Publication.Status.PREPARING:
        Publication.objects.filter(pk=publication.pk).update(status=Publication.Status.PREPARING)
        publication.status = Publication.Status.PREPARING

    plan = build_image_plan(
        user=publication.user,
        subject=publication.subject,
        article=publication.article,
        strategy=publication.image_strategy,
        density=str(publication.image_plan.get("density") or PublishingPreference.ImageDensity.STANDARD),
    )
    previous = publication.image_plan if isinstance(publication.image_plan, dict) else {}
    if previous.get("supplement_job_ids"):
        plan["supplement_job_ids"] = list(previous.get("supplement_job_ids") or [])
        plan["supplement_attempted"] = bool(previous.get("supplement_attempted"))

    plan, images_ready = _ensure_image_supplements(publication, plan)
    Publication.objects.filter(pk=publication.pk).update(image_plan=plan)

    adaptations, adaptation_started_or_done = _ensure_adaptations(publication)
    if not adaptation_started_or_done:
        return {"status": "waiting", "retry_after": _PREPARATION_RETRY_SECONDS}
    refreshed_adaptations, adaptations_ready = _ready_adaptations(publication)
    if refreshed_adaptations:
        adaptations = refreshed_adaptations
    if not images_ready or not adaptations_ready:
        return {"status": "waiting", "retry_after": _PREPARATION_RETRY_SECONDS}

    # AI 补图任务完成后重新扫描一次，把新生成且已审核通过的图片纳入最终方案。
    if plan.get("supplement_job_ids"):
        rebuilt = build_image_plan(
            user=publication.user,
            subject=publication.subject,
            article=publication.article,
            strategy=publication.image_strategy,
            density=str(plan.get("density") or PublishingPreference.ImageDensity.STANDARD),
        )
        rebuilt["supplement_job_ids"] = list(plan.get("supplement_job_ids") or [])
        rebuilt["supplement_attempted"] = True
        if rebuilt.get("missing_assets"):
            rebuilt["supplement_incomplete"] = True
        plan = rebuilt

    _assign_target_payloads(publication, plan, adaptations)
    return {"status": "ready"}


def _download_url_for_asset(asset: ImageAsset) -> str:
    return storage_provider().create_download_url(
        key=asset.object_key,
        filename=f"publishing-{asset.pk}",
        content_type=asset.mime_type,
    )


def _delivery_assets(target: PublicationTarget) -> list[dict[str, Any]]:
    items = list((target.media_payload or {}).get("assets") or [])
    asset_ids = [item.get("asset_id") for item in items if item.get("asset_id")]
    derivative_ids = [item.get("derivative_id") for item in items if item.get("derivative_id")]
    assets = {
        str(item.pk): item
        for item in ImageAsset.objects.filter(
            pk__in=asset_ids,
            user=target.publication.user,
            subject=target.publication.subject,
            lifecycle_status=ImageAsset.LifecycleStatus.ACTIVE,
            moderation_status=ImageAsset.ModerationStatus.APPROVED,
        )
    }
    derivatives = {
        str(item.pk): item
        for item in ImageDerivative.objects.filter(
            pk__in=derivative_ids,
            user=target.publication.user,
        )
    }
    result: list[dict[str, Any]] = []
    provider = storage_provider()
    for item in items:
        asset = assets.get(str(item.get("asset_id") or ""))
        if asset is None:
            continue
        purpose = str(item.get("purpose") or "inline")
        derivative = derivatives.get(str(item.get("derivative_id") or ""))
        if derivative is not None:
            url = provider.create_download_url(
                key=derivative.object_key,
                filename=f"publishing-{derivative.pk}",
                content_type=derivative.mime_type,
            )
        else:
            url = _download_url_for_asset(asset)
        result.append(
            {
                "role": "information" if purpose == "information" else ("cover" if purpose == "cover" else "inline"),
                "url": url,
                "alt": target.adapted_title[:120],
            }
        )
    return result


def _aggregate_publication(publication_id) -> None:
    with transaction.atomic():
        publication = Publication.objects.select_for_update().get(pk=publication_id)
        statuses = list(publication.targets.values_list("status", flat=True))
        if not statuses:
            publication.status = Publication.Status.FAILED
        elif all(value == PublicationTarget.Status.SUCCEEDED for value in statuses):
            publication.status = Publication.Status.SUCCEEDED
        elif any(value == PublicationTarget.Status.SUCCEEDED for value in statuses) and all(
            value in {
                PublicationTarget.Status.SUCCEEDED,
                PublicationTarget.Status.FAILED,
                PublicationTarget.Status.AUTH_REQUIRED,
                PublicationTarget.Status.PAUSED,
            }
            for value in statuses
        ):
            publication.status = Publication.Status.PARTIAL
        elif all(
            value in {
                PublicationTarget.Status.FAILED,
                PublicationTarget.Status.AUTH_REQUIRED,
                PublicationTarget.Status.PAUSED,
            }
            for value in statuses
        ):
            publication.status = Publication.Status.FAILED
        else:
            publication.status = Publication.Status.RUNNING
        publication.save(update_fields=("status", "updated_at"))


def execute_target(*, target_id) -> dict[str, Any]:
    with transaction.atomic():
        target = (
            PublicationTarget.objects.select_for_update()
            .select_related("publication", "publication__user", "publication__subject", "publication__article", "account")
            .get(pk=target_id)
        )
        if target.status in {
            PublicationTarget.Status.SUCCEEDED,
            PublicationTarget.Status.AUTH_REQUIRED,
            PublicationTarget.Status.PAUSED,
        }:
            return {"status": target.status}
        if target.scheduled_at and target.scheduled_at > timezone.now() + timedelta(seconds=2):
            return {"status": "scheduled", "eta": target.scheduled_at}
        account = target.account
        if account is None or account.status != PlatformAccount.Status.CONNECTED or not account.enabled_for_auto:
            target.status = PublicationTarget.Status.AUTH_REQUIRED
            target.safe_error_code = "authorization_required"
            target.save(update_fields=("status", "safe_error_code", "updated_at"))
            _aggregate_publication(target.publication_id)
            return {"status": "auth_required"}
        if target.status not in {PublicationTarget.Status.READY, PublicationTarget.Status.FAILED, PublicationTarget.Status.WAITING}:
            return {"status": target.status}
        target.status = PublicationTarget.Status.RUNNING
        target.attempts += 1
        target.safe_error_code = ""
        target.save(update_fields=("status", "attempts", "safe_error_code", "updated_at"))

    target = (
        PublicationTarget.objects.select_related("publication", "publication__user", "publication__subject", "publication__article", "account")
        .get(pk=target_id)
    )
    try:
        credentials = decrypt_secret(target.account.secret_ciphertext if target.account else "")
    except PublishingCredentialError:
        PlatformAccount.objects.filter(pk=target.account_id).update(
            status=PlatformAccount.Status.ACTION_REQUIRED,
            last_error_code="authorization_required",
            last_checked_at=timezone.now(),
        )
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.AUTH_REQUIRED,
            safe_error_code="authorization_required",
        )
        _aggregate_publication(target.publication_id)
        return {"status": "auth_required"}

    try:
        assets = _delivery_assets(target)
    except FileStorageUnavailable:
        assets = []

    platform = PLATFORM_BY_KEY.get(target.platform_key)
    if platform is None:
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.PAUSED,
            safe_error_code="platform_unavailable",
        )
        _aggregate_publication(target.publication_id)
        return {"status": "paused"}

    # 图文平台没有任何可用图片时不进行不完整发布。
    if target.platform_key in {"xiaohongshu", "douyin"} and not assets:
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.FAILED,
            safe_error_code="media_invalid",
        )
        _aggregate_publication(target.publication_id)
        return {"status": "failed"}

    text = _plain_text(target.adapted_content)
    try:
        result = publish_to_platform(
            platform_key=target.platform_key,
            target_id=str(target.pk),
            title=target.adapted_title,
            content_html=_simple_html(target.adapted_content),
            content_text=text,
            summary=text[:180],
            tags=[],
            assets=assets,
            credentials=credentials,
            publish_mode="public",
        )
    except PublishingWorkerError as exc:
        retryable = exc.code in {"worker_timeout", "worker_unavailable"}
        max_retries = int(getattr(settings, "PUBLISHING_TARGET_MAX_RETRIES", 3))
        if retryable and target.attempts < max_retries:
            PublicationTarget.objects.filter(pk=target.pk).update(
                status=PublicationTarget.Status.READY,
                safe_error_code="platform_unavailable",
            )
            return {"status": "retry", "retry_after": _TRANSIENT_RETRY_SECONDS}
        code = "platform_unavailable" if exc.code != "platform_not_ready" else "platform_unavailable"
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.PAUSED if exc.code == "platform_not_ready" else PublicationTarget.Status.FAILED,
            safe_error_code=code,
        )
        _aggregate_publication(target.publication_id)
        return {"status": "failed"}

    remote_status = str(result.get("status") or "failed")
    if bool(result.get("success")) and remote_status == "published" and result.get("publicUrl"):
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.SUCCEEDED,
            published_at=timezone.now(),
            external_post_id=str(result.get("externalPostId") or "")[:255],
            public_url=str(result.get("publicUrl") or ""),
            safe_error_code="",
        )
        _aggregate_publication(target.publication_id)
        return {"status": "succeeded"}

    if remote_status == "auth_required":
        PlatformAccount.objects.filter(pk=target.account_id).update(
            status=PlatformAccount.Status.EXPIRED,
            last_error_code="authorization_required",
            last_checked_at=timezone.now(),
        )
        PublicationTarget.objects.filter(pk=target.pk).update(
            status=PublicationTarget.Status.AUTH_REQUIRED,
            safe_error_code="authorization_required",
        )
        _aggregate_publication(target.publication_id)
        return {"status": "auth_required"}

    code = str(result.get("safeErrorCode") or "platform_unavailable")[:100]
    # 草稿成功不等于自动公开发布成功；不能用“已发布”误导客户。
    status = PublicationTarget.Status.PAUSED if remote_status in {"drafted", "action_required"} else PublicationTarget.Status.FAILED
    PublicationTarget.objects.filter(pk=target.pk).update(status=status, safe_error_code=code)
    _aggregate_publication(target.publication_id)
    return {"status": status}
