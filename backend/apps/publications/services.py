from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import Http404
from django.utils import timezone

from apps.ai.credential_crypto import decrypt_secret, encrypt_secret
from apps.articles.models import Article, ChannelAdaptation
from apps.articles.services import ContentError, create_channel_jobs
from apps.articles.tasks import execute_generation_job_task
from apps.images.models import ImageAsset, ImageGenerationJob, ImageSizePreset, ImageStylePreset
from apps.images.services import create_image_job
from apps.images.tasks import execute_image_job_task
from apps.subjects.models import Subject
from apps.subjects.subject_services import subject_for_user_or_404

from .models import (
    AuthorizationSession,
    AutoPublishPolicy,
    PlatformAccount,
    PublicationJob,
    PublicationPlatform,
    PublicationTarget,
    PublicationVisual,
)

logger = logging.getLogger(__name__)


class PublicationInputError(Exception):
    def __init__(self, code: str, *, status: int = 409):
        super().__init__(code)
        self.code = code
        self.status = status


def _digest_idempotency(*, user_id, namespace: str, raw_key: str) -> str:
    value = raw_key.strip()
    if not value or len(value) > 200:
        raise PublicationInputError("PUBLICATION_IDEMPOTENCY_KEY_REQUIRED", status=422)
    derived = hmac.new(
        settings.PUBLISHING_IDEMPOTENCY_HMAC_KEY.encode(),
        f"publication:{namespace}:v1".encode(),
        hashlib.sha256,
    ).digest()
    return hmac.new(derived, f"{user_id}:{value}".encode(), hashlib.sha256).hexdigest()


def _subject(user, subject_id, *, lock=False) -> Subject:
    return subject_for_user_or_404(user=user, subject_id=subject_id, lock=lock)


def _platform(platform_key: str) -> PublicationPlatform:
    try:
        return PublicationPlatform.objects.select_related("channel").get(
            channel__key=platform_key, channel__enabled=True
        )
    except PublicationPlatform.DoesNotExist as exc:
        raise PublicationInputError("PUBLICATION_PLATFORM_UNAVAILABLE", status=422) from exc


def _account_for_subject(user, subject, platform, *, lock=False) -> PlatformAccount | None:
    query = PlatformAccount.objects.filter(
        user=user, subject=subject, platform=platform, is_default=True
    )
    if lock:
        query = query.select_for_update()
    return query.order_by("created_at").first()


def get_or_create_policy(*, user, subject_id, lock=False) -> AutoPublishPolicy:
    subject = _subject(user, subject_id, lock=lock)
    query = AutoPublishPolicy.objects.filter(user=user, subject=subject)
    if lock:
        query = query.select_for_update()
    policy = query.first()
    if policy is not None:
        return policy
    return AutoPublishPolicy.objects.create(user=user, subject=subject)


def policy_payload(policy: AutoPublishPolicy) -> dict[str, Any]:
    return {
        "id": str(policy.pk),
        "subject_id": str(policy.subject_id),
        "enabled": policy.enabled,
        "operating_mode": policy.operating_mode,
        "distribution_strategy": policy.distribution_strategy,
        "custom_platform_keys": policy.custom_platform_keys,
        "frequency_mode": policy.frequency_mode,
        "custom_daily_limit": policy.custom_daily_limit,
        "image_strategy": policy.image_strategy,
        "image_richness": policy.image_richness,
        "version": policy.version,
        "updated_at": policy.updated_at,
    }


@transaction.atomic
def update_policy(*, user, subject_id, data, expected_version):
    policy = get_or_create_policy(user=user, subject_id=subject_id, lock=True)
    if policy.version != expected_version:
        raise PublicationInputError("PUBLICATION_POLICY_VERSION_CONFLICT")
    if data.get("distribution_strategy") == AutoPublishPolicy.DistributionStrategy.CUSTOM:
        keys = list(dict.fromkeys(data.get("custom_platform_keys", [])))
        existing = set(
            PublicationPlatform.objects.filter(channel__key__in=keys).values_list(
                "channel__key", flat=True
            )
        )
        if set(keys) != existing:
            raise PublicationInputError("PUBLICATION_PLATFORM_SELECTION_INVALID", status=422)
        data["custom_platform_keys"] = keys
    for field in (
        "enabled",
        "operating_mode",
        "distribution_strategy",
        "custom_platform_keys",
        "frequency_mode",
        "custom_daily_limit",
        "image_strategy",
        "image_richness",
    ):
        if field in data:
            setattr(policy, field, data[field])
    policy.version += 1
    policy.save()
    return policy


def account_payload(account: PlatformAccount | None) -> dict[str, Any] | None:
    if account is None:
        return None
    return {
        "id": str(account.pk),
        "display_name": account.display_name,
        "external_account_id": account.external_account_id,
        "auth_method": account.auth_method,
        "auth_status": account.auth_status,
        "enabled_for_auto_publish": account.enabled_for_auto_publish,
        "authorized_at": account.authorized_at,
        "expires_at": account.expires_at,
        "last_auth_check_at": account.last_auth_check_at,
        "version": account.version,
    }


def platform_payload(platform: PublicationPlatform, account=None) -> dict[str, Any]:
    channel = platform.channel
    return {
        "id": str(platform.pk),
        "key": channel.key,
        "name": channel.name,
        "official_url": channel.official_url,
        "channel_type": channel.channel_type,
        "auth_mode": platform.auth_mode,
        "publish_mode": platform.publish_mode,
        "validation_status": platform.validation_status,
        "health_status": platform.health_status,
        "capabilities": platform.capabilities,
        "minimum_interval_minutes": platform.minimum_interval_minutes,
        "account": account_payload(account),
    }


def platform_catalog(*, user, subject_id) -> list[dict[str, Any]]:
    subject = _subject(user, subject_id)
    platforms = list(
        PublicationPlatform.objects.select_related("channel").filter(channel__enabled=True)
    )
    accounts = {
        row.platform_id: row
        for row in PlatformAccount.objects.filter(
            user=user, subject=subject, is_default=True
        ).select_related("platform")
    }
    return [platform_payload(row, accounts.get(row.pk)) for row in platforms]


def authorization_payload(session: AuthorizationSession) -> dict[str, Any]:
    return {
        "id": str(session.pk),
        "platform_key": session.platform.channel.key,
        "platform_name": session.platform.channel.name,
        "status": session.status,
        "auth_method": session.auth_method,
        "login_snapshot_data_url": session.login_snapshot_data_url,
        "safe_error_code": session.safe_error_code,
        "expires_at": session.expires_at,
        "last_snapshot_at": session.last_snapshot_at,
        "account": account_payload(session.account),
    }


def authorization_session_for_user(*, user, session_id):
    try:
        return AuthorizationSession.objects.select_related(
            "platform__channel", "account", "subject"
        ).get(pk=session_id, user=user)
    except AuthorizationSession.DoesNotExist as exc:
        raise Http404 from exc


@transaction.atomic
def begin_authorization(*, user, subject_id, platform_key, credentials=None):
    subject = _subject(user, subject_id, lock=True)
    platform = _platform(platform_key)
    if platform.validation_status == PublicationPlatform.ValidationStatus.PAUSED:
        raise PublicationInputError("PUBLICATION_PLATFORM_PAUSED", status=422)
    if (
        platform.validation_status == PublicationPlatform.ValidationStatus.TESTING
        and not settings.AUTO_PUBLISH_ALLOW_TESTING_PLATFORMS
    ):
        raise PublicationInputError("PUBLICATION_PLATFORM_STILL_TESTING", status=422)

    account = _account_for_subject(user, subject, platform, lock=True)
    if account is None:
        account = PlatformAccount.objects.create(
            user=user,
            subject=subject,
            platform=platform,
            auth_method=platform.auth_mode,
            auth_status=PlatformAccount.AuthStatus.AUTHORIZING,
        )
    else:
        account.auth_method = platform.auth_mode
        account.auth_status = PlatformAccount.AuthStatus.AUTHORIZING
        account.version += 1

    if platform.auth_mode == PublicationPlatform.AuthMode.OFFICIAL_CREDENTIALS:
        raw = credentials or {}
        app_id = str(raw.get("app_id", "")).strip()
        app_secret = str(raw.get("app_secret", "")).strip()
        if not app_id or len(app_id) > 128 or not app_secret or len(app_secret) > 256:
            raise PublicationInputError("PUBLICATION_CREDENTIALS_REQUIRED", status=422)
        account.encrypted_auth_state = encrypt_secret(
            json.dumps(
                {"kind": "official_credentials", "app_id": app_id, "app_secret": app_secret},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        account.auth_metadata = {"credential_kind": "official_credentials", "app_id_suffix": app_id[-6:]}
    else:
        account.encrypted_auth_state = ""
        account.auth_metadata = {"credential_kind": "browser_storage_state"}
    account.save()

    now = timezone.now()
    session = AuthorizationSession.objects.create(
        user=user,
        subject=subject,
        platform=platform,
        account=account,
        auth_method=platform.auth_mode,
        expires_at=now + timedelta(minutes=6),
    )
    from .tasks import execute_authorization_session_task

    transaction.on_commit(
        lambda: execute_authorization_session_task.apply_async(
            args=[str(session.pk)], queue="publication"
        )
    )
    return session


@transaction.atomic
def revoke_account(*, user, subject_id, platform_key):
    subject = _subject(user, subject_id, lock=True)
    platform = _platform(platform_key)
    account = _account_for_subject(user, subject, platform, lock=True)
    if account is None:
        raise Http404
    account.encrypted_auth_state = ""
    account.auth_metadata = {}
    account.auth_status = PlatformAccount.AuthStatus.REVOKED
    account.authorized_at = None
    account.expires_at = None
    account.enabled_for_auto_publish = False
    account.version += 1
    account.save()
    AuthorizationSession.objects.filter(
        account=account,
        status__in=(AuthorizationSession.Status.QUEUED, AuthorizationSession.Status.WAITING),
    ).update(
        status=AuthorizationSession.Status.CANCELLED,
        login_snapshot_data_url="",
        finished_at=timezone.now(),
    )
    return account


@transaction.atomic
def set_account_participation(*, user, subject_id, platform_key, enabled, expected_version):
    subject = _subject(user, subject_id, lock=True)
    platform = _platform(platform_key)
    account = _account_for_subject(user, subject, platform, lock=True)
    if account is None:
        raise Http404
    if account.version != expected_version:
        raise PublicationInputError("PUBLICATION_ACCOUNT_VERSION_CONFLICT")
    if enabled and account.auth_status != PlatformAccount.AuthStatus.AUTHORIZED:
        raise PublicationInputError("PUBLICATION_ACCOUNT_NOT_AUTHORIZED")
    account.enabled_for_auto_publish = enabled
    account.version += 1
    account.save(update_fields=("enabled_for_auto_publish", "version", "updated_at"))
    return account


def decrypt_account_state(account: PlatformAccount) -> dict[str, Any]:
    if not account.encrypted_auth_state:
        raise PublicationInputError("PUBLICATION_ACCOUNT_NOT_AUTHORIZED")
    try:
        value = json.loads(decrypt_secret(account.encrypted_auth_state))
    except Exception as exc:
        raise PublicationInputError("PUBLICATION_AUTH_STATE_UNAVAILABLE") from exc
    if not isinstance(value, dict):
        raise PublicationInputError("PUBLICATION_AUTH_STATE_UNAVAILABLE")
    return value


def _policy_snapshot(policy: AutoPublishPolicy) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "operating_mode": policy.operating_mode,
        "distribution_strategy": policy.distribution_strategy,
        "custom_platform_keys": list(policy.custom_platform_keys),
        "frequency_mode": policy.frequency_mode,
        "custom_daily_limit": policy.custom_daily_limit,
        "image_strategy": policy.image_strategy,
        "image_richness": policy.image_richness,
        "version": policy.version,
    }


def _authorized_accounts(*, user, subject):
    return list(
        PlatformAccount.objects.select_related("platform__channel")
        .filter(
            user=user,
            subject=subject,
            is_default=True,
            auth_status=PlatformAccount.AuthStatus.AUTHORIZED,
            enabled_for_auto_publish=True,
            platform__validation_status=PublicationPlatform.ValidationStatus.AVAILABLE,
            platform__health_status__in=(
                PublicationPlatform.HealthStatus.HEALTHY,
                PublicationPlatform.HealthStatus.DEGRADED,
            ),
        )
        .order_by("platform__channel__sort_order")
    )


def _smart_platform_keys(article: Article, available_keys: set[str]) -> list[str]:
    recommended: list[str] = []
    if article.template_version_id and article.template_version:
        recommended.extend(article.template_version.recommended_channel_keys or [])

    text = f"{article.title}\n{article.custom_type}\n{article.content[:4000]}".casefold()
    tech_terms = ("代码", "api", "架构", "开发", "技术", "算法", "软件", "系统", "程序")
    social_terms = ("品牌", "产品", "服务", "消费", "门店", "体验", "案例", "活动")
    if any(term in text for term in tech_terms):
        recommended.extend(("zhihu", "csdn", "juejin", "cnblogs", "oschina", "segmentfault", "wechat"))
    if any(term in text for term in social_terms):
        recommended.extend(("wechat", "zhihu", "toutiao", "baijiahao", "xiaohongshu", "weibo", "douyin"))
    if not recommended:
        recommended.extend(("wechat", "zhihu", "toutiao", "baijiahao", "weibo"))

    selected = [key for key in dict.fromkeys(recommended) if key in available_keys]
    if selected:
        return selected[:8]
    return sorted(available_keys)[:6]


def _selected_accounts(policy: AutoPublishPolicy, article: Article, accounts):
    by_key = {row.platform.channel.key: row for row in accounts}
    if policy.distribution_strategy == AutoPublishPolicy.DistributionStrategy.ALL_AUTHORIZED:
        return list(by_key.values())
    if policy.distribution_strategy == AutoPublishPolicy.DistributionStrategy.CUSTOM:
        return [by_key[key] for key in policy.custom_platform_keys if key in by_key]
    return [by_key[key] for key in _smart_platform_keys(article, set(by_key)) if key in by_key]


def _visual_requirements(richness: str) -> tuple[int, int]:
    return {
        AutoPublishPolicy.ImageRichness.SIMPLE: (1, 1),
        AutoPublishPolicy.ImageRichness.STANDARD: (1, 2),
        AutoPublishPolicy.ImageRichness.RICH: (1, 4),
    }.get(richness, (1, 2))


def _candidate_images(job: PublicationJob):
    return (
        ImageAsset.objects.filter(
            user=job.user,
            subject=job.subject,
            lifecycle_status=ImageAsset.LifecycleStatus.ACTIVE,
            moderation_status=ImageAsset.ModerationStatus.APPROVED,
        )
        .annotate(
            article_rank=Case(
                When(article=job.article, then=Value(0)),
                When(article__isnull=True, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ),
            source_rank=Case(
                When(source_type=ImageAsset.SourceType.UPLOADED, then=Value(0)),
                When(is_subject_library=True, then=Value(1)),
                When(source_type=ImageAsset.SourceType.DERIVATIVE, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            ),
        )
        .order_by("article_rank", "source_rank", "-created_at")
    )


def _enqueue_image_generation(job: PublicationJob, *, role: str, ordinal: int):
    size_key = "landscape_16_9"
    style_key = "editorial"
    size = ImageSizePreset.objects.filter(key=size_key, status="active").first()
    style = ImageStylePreset.objects.filter(key=style_key, status="active").first()
    if size is None or style is None:
        return None
    purpose = "封面" if role == "cover" else f"正文插图 {ordinal + 1}"
    prompt = (
        f"为文章《{job.article.title[:120]}》生成{purpose}。"
        "使用概念性、编辑插画式商业视觉，不生成或冒充客户真实工厂、团队、产品实物、案例现场、"
        "资质证书，不生成不可核验的数据和文字，不添加水印。"
    )
    try:
        image_job, created = create_image_job(
            user=job.user,
            subject_id=job.subject_id,
            article_id=job.article_id,
            role=role,
            prompt=prompt,
            size_preset_id=size.pk,
            style_preset_id=style.pk,
            reference_asset_id=None,
            reference_document_version_id=None,
            reference_url="",
            idempotency_key=f"auto-publish:{job.pk}:{role}:{ordinal}",
            request_id=uuid.uuid4(),
        )
    except Exception:
        logger.exception("automatic publication image request failed", extra={"job_id": str(job.pk)})
        return None
    if created:
        transaction.on_commit(
            lambda: execute_image_job_task.apply_async(
                args=[str(image_job.pk)], queue="image_generation"
            )
        )
    return image_job


def _plan_visuals(job: PublicationJob) -> dict[str, Any]:
    policy = job.policy
    cover_count, illustration_count = _visual_requirements(policy.image_richness)
    selected_ids = set(
        PublicationVisual.objects.filter(job=job).values_list("image_id", flat=True)
    )
    candidates = [row for row in _candidate_images(job) if row.pk not in selected_ids]
    uploaded_only = policy.image_strategy == AutoPublishPolicy.ImageStrategy.CUSTOMER_ONLY
    if uploaded_only:
        candidates = [row for row in candidates if row.source_type == ImageAsset.SourceType.UPLOADED]

    cover_candidates = [row for row in candidates if row.role == ImageGenerationJob.Role.COVER]
    other_candidates = [row for row in candidates if row not in cover_candidates]
    cover_assets = (cover_candidates + other_candidates)[:cover_count]
    remaining = [row for row in candidates if row not in cover_assets]
    illustration_assets = remaining[:illustration_count]

    for ordinal, image in enumerate(cover_assets):
        PublicationVisual.objects.get_or_create(
            job=job,
            target=None,
            image=image,
            role=PublicationVisual.Role.COVER,
            ordinal=ordinal,
            defaults={"source_strategy": "customer_asset" if image.source_type == "uploaded" else "approved_asset"},
        )
    for ordinal, image in enumerate(illustration_assets):
        PublicationVisual.objects.get_or_create(
            job=job,
            target=None,
            image=image,
            role=PublicationVisual.Role.ILLUSTRATION,
            ordinal=ordinal,
            defaults={"source_strategy": "customer_asset" if image.source_type == "uploaded" else "approved_asset"},
        )

    pending: list[str] = []
    if policy.image_strategy != AutoPublishPolicy.ImageStrategy.CUSTOMER_ONLY:
        for ordinal in range(len(cover_assets), cover_count):
            row = _enqueue_image_generation(job, role="cover", ordinal=ordinal)
            if row is not None:
                pending.append(str(row.pk))
        for ordinal in range(len(illustration_assets), illustration_count):
            row = _enqueue_image_generation(job, role="illustration", ordinal=ordinal)
            if row is not None:
                pending.append(str(row.pk))

    return {
        "cover_required": cover_count,
        "illustrations_required": illustration_count,
        "selected_visual_ids": [
            str(pk) for pk in PublicationVisual.objects.filter(job=job).values_list("id", flat=True)
        ],
        "pending_image_job_ids": pending,
        "customer_assets_first": policy.image_strategy != AutoPublishPolicy.ImageStrategy.AUTO,
    }


def _attach_finished_generated_visuals(job: PublicationJob) -> tuple[bool, dict[str, Any]]:
    plan = dict(job.visual_plan or {})
    pending_ids = plan.get("pending_image_job_ids") or []
    if not pending_ids:
        return True, plan
    rows = {
        str(row.pk): row
        for row in ImageGenerationJob.objects.filter(pk__in=pending_ids).select_related("result_asset")
    }
    still_pending: list[str] = []
    generated_index = 0
    for job_id in pending_ids:
        row = rows.get(str(job_id))
        if row is None:
            continue
        if row.status in {
            ImageGenerationJob.Status.QUEUED,
            ImageGenerationJob.Status.RUNNING,
            ImageGenerationJob.Status.RETRY_WAIT,
        }:
            still_pending.append(str(row.pk))
            continue
        asset = getattr(row, "result_asset", None)
        if (
            row.status == ImageGenerationJob.Status.SUCCEEDED
            and asset is not None
            and asset.moderation_status == ImageAsset.ModerationStatus.APPROVED
        ):
            role = (
                PublicationVisual.Role.COVER
                if row.role == ImageGenerationJob.Role.COVER
                else PublicationVisual.Role.ILLUSTRATION
            )
            PublicationVisual.objects.get_or_create(
                job=job,
                target=None,
                image=asset,
                role=role,
                ordinal=generated_index + 50,
                defaults={"source_strategy": "ai_fill"},
            )
            generated_index += 1
    plan["pending_image_job_ids"] = still_pending
    plan["selected_visual_ids"] = [
        str(pk) for pk in PublicationVisual.objects.filter(job=job).values_list("id", flat=True)
    ]
    return not still_pending, plan


def _schedule_targets(job: PublicationJob):
    now = timezone.now()
    cursor = now + timedelta(minutes=5)
    for target in job.targets.select_related("platform").order_by("platform__channel__sort_order"):
        target.scheduled_at = cursor
        target.status = PublicationTarget.Status.SCHEDULED
        target.save(update_fields=("scheduled_at", "status", "updated_at"))
        cursor += timedelta(minutes=max(10, target.platform.minimum_interval_minutes))
    job.scheduled_for = job.targets.order_by("scheduled_at").values_list("scheduled_at", flat=True).first()
    job.status = PublicationJob.Status.SCHEDULED
    job.save(update_fields=("scheduled_for", "status", "updated_at"))


@transaction.atomic
def create_publication_job(*, user, article_id, idempotency_key, force_review=False):
    try:
        article = (
            Article.objects.select_for_update()
            .select_related("subject", "template_version")
            .get(pk=article_id, user=user)
        )
    except Article.DoesNotExist as exc:
        raise Http404 from exc
    if article.status != Article.Status.READY or article.moderation_status != Article.Moderation.PASSED:
        raise PublicationInputError("PUBLICATION_ARTICLE_NOT_READY", status=422)
    policy = get_or_create_policy(user=user, subject_id=article.subject_id, lock=True)
    digest = _digest_idempotency(
        user_id=user.pk,
        namespace=f"article:{article.pk}",
        raw_key=idempotency_key,
    )
    existing = PublicationJob.objects.filter(idempotency_key_digest=digest).first()
    if existing is not None:
        return existing, False

    accounts = _authorized_accounts(user=user, subject=article.subject)
    selected = _selected_accounts(policy, article, accounts)
    if not selected:
        raise PublicationInputError("PUBLICATION_NO_AUTHORIZED_PLATFORM", status=422)

    job = PublicationJob.objects.create(
        user=user,
        subject=article.subject,
        article=article,
        policy=policy,
        policy_snapshot=_policy_snapshot(policy),
        distribution_plan={
            "strategy": policy.distribution_strategy,
            "platform_keys": [row.platform.channel.key for row in selected],
            "awaiting_review": bool(force_review or policy.operating_mode == AutoPublishPolicy.OperatingMode.REVIEW),
        },
        idempotency_key_digest=digest,
        status=PublicationJob.Status.PLANNING,
    )
    for account in selected:
        PublicationTarget.objects.create(
            job=job,
            platform=account.platform,
            account=account,
            status=PublicationTarget.Status.WAITING,
        )
    from .tasks import prepare_publication_job_task

    if not job.distribution_plan["awaiting_review"]:
        transaction.on_commit(
            lambda: prepare_publication_job_task.apply_async(
                args=[str(job.pk)], queue="system_tasks"
            )
        )
    return job, True


@transaction.atomic
def approve_publication_job(*, user, job_id):
    try:
        job = PublicationJob.objects.select_for_update().get(pk=job_id, user=user)
    except PublicationJob.DoesNotExist as exc:
        raise Http404 from exc
    plan = dict(job.distribution_plan or {})
    if not plan.get("awaiting_review"):
        return job
    plan["awaiting_review"] = False
    job.distribution_plan = plan
    job.save(update_fields=("distribution_plan", "updated_at"))
    from .tasks import prepare_publication_job_task

    transaction.on_commit(
        lambda: prepare_publication_job_task.apply_async(args=[str(job.pk)], queue="system_tasks")
    )
    return job


def maybe_enqueue_article(article_id: str):
    try:
        article = Article.objects.select_related("subject").get(pk=article_id)
    except Article.DoesNotExist:
        return None
    policy = AutoPublishPolicy.objects.filter(
        user=article.user,
        subject=article.subject,
        enabled=True,
    ).first()
    if policy is None or policy.operating_mode == AutoPublishPolicy.OperatingMode.SELECTED:
        return None
    try:
        job, _ = create_publication_job(
            user=article.user,
            article_id=article.pk,
            idempotency_key=f"managed:{article.pk}:v{article.version}",
            force_review=policy.operating_mode == AutoPublishPolicy.OperatingMode.REVIEW,
        )
        return job
    except PublicationInputError:
        return None


def prepare_publication_job(job_id: str):
    with transaction.atomic():
        try:
            job = (
                PublicationJob.objects.select_for_update()
                .select_related("user", "subject", "article", "policy")
                .get(pk=job_id)
            )
        except PublicationJob.DoesNotExist:
            return {"status": "missing"}
        if job.status in {
            PublicationJob.Status.SUCCEEDED,
            PublicationJob.Status.PARTIAL,
            PublicationJob.Status.FAILED,
            PublicationJob.Status.CANCELLED,
        }:
            return {"status": job.status}
        if job.distribution_plan.get("awaiting_review"):
            return {"status": "awaiting_review"}
        job.status = PublicationJob.Status.PREPARING
        job.save(update_fields=("status", "updated_at"))
        if not job.visual_plan:
            job.visual_plan = _plan_visuals(job)
            job.save(update_fields=("visual_plan", "updated_at"))

        targets = list(job.targets.select_related("platform__channel"))
        channel_ids = [row.platform.channel_id for row in targets]
        try:
            adaptations = create_channel_jobs(
                user=job.user,
                article_id=job.article_id,
                channel_ids=channel_ids,
                idempotency_key=f"auto-publish:{job.pk}",
                request_id=uuid.uuid4(),
            )
        except ContentError as exc:
            job.safe_error_code = exc.code
            job.status = PublicationJob.Status.FAILED
            job.finished_at = timezone.now()
            job.save(update_fields=("safe_error_code", "status", "finished_at", "updated_at"))
            return {"status": "failed"}
        adaptation_by_channel = {row.channel_id: (row, generation, created) for row, generation, created in adaptations}
        for target in targets:
            adaptation, generation, created = adaptation_by_channel[target.platform.channel_id]
            target.adaptation = adaptation
            target.status = PublicationTarget.Status.ADAPTING
            target.save(update_fields=("adaptation", "status", "updated_at"))
            if created:
                transaction.on_commit(
                    lambda generation_id=str(generation.pk): execute_generation_job_task.apply_async(
                        args=[generation_id], queue="system_tasks"
                    )
                )

    from .tasks import refresh_publication_job_task

    refresh_publication_job_task.apply_async(args=[str(job_id)], countdown=5, queue="system_tasks")
    return {"status": "preparing"}


def refresh_publication_job(job_id: str):
    with transaction.atomic():
        try:
            job = (
                PublicationJob.objects.select_for_update()
                .select_related("article", "policy")
                .get(pk=job_id)
            )
        except PublicationJob.DoesNotExist:
            return {"status": "missing"}
        if job.status != PublicationJob.Status.PREPARING:
            return {"status": job.status}

        images_ready, updated_visual_plan = _attach_finished_generated_visuals(job)
        job.visual_plan = updated_visual_plan
        job.save(update_fields=("visual_plan", "updated_at"))

        targets = list(job.targets.select_related("adaptation", "platform__channel"))
        adaptations_ready = True
        any_failed = False
        for target in targets:
            adaptation = target.adaptation
            if adaptation is None or adaptation.status in {
                ChannelAdaptation.Status.QUEUED,
                ChannelAdaptation.Status.RUNNING,
            }:
                adaptations_ready = False
                continue
            if adaptation.status == ChannelAdaptation.Status.FAILED:
                target.status = PublicationTarget.Status.FAILED
                target.safe_error_code = adaptation.safe_error_code or "PUBLICATION_ADAPTATION_FAILED"
                target.save(update_fields=("status", "safe_error_code", "updated_at"))
                any_failed = True
                continue
            target.payload_snapshot = {
                "title": adaptation.title,
                "content": adaptation.content,
                "adaptation_version": adaptation.version,
                "article_version": job.article.version,
            }
            target.status = PublicationTarget.Status.READY
            target.save(update_fields=("payload_snapshot", "status", "updated_at"))

        if not adaptations_ready or not images_ready:
            from .tasks import refresh_publication_job_task

            transaction.on_commit(
                lambda: refresh_publication_job_task.apply_async(
                    args=[str(job.pk)], countdown=10, queue="system_tasks"
                )
            )
            return {"status": "preparing"}

        ready_targets = [row for row in targets if row.status == PublicationTarget.Status.READY]
        if not ready_targets:
            job.status = PublicationJob.Status.FAILED
            job.safe_error_code = "PUBLICATION_PREPARATION_FAILED"
            job.finished_at = timezone.now()
            job.save(update_fields=("status", "safe_error_code", "finished_at", "updated_at"))
            return {"status": "failed"}
        _schedule_targets(job)

    from .tasks import dispatch_due_publication_targets_task

    dispatch_due_publication_targets_task.apply_async(countdown=1, queue="system_tasks")
    return {"status": "scheduled", "partial_preparation": any_failed}


def job_payload(job: PublicationJob) -> dict[str, Any]:
    visuals = list(job.visuals.select_related("image").all())
    targets = list(
        job.targets.select_related("platform__channel", "account", "adaptation").all()
    )
    return {
        "id": str(job.pk),
        "subject_id": str(job.subject_id),
        "article": {"id": str(job.article_id), "title": job.article.title},
        "status": job.status,
        "policy_snapshot": job.policy_snapshot,
        "distribution_plan": job.distribution_plan,
        "visual_plan": job.visual_plan,
        "scheduled_for": job.scheduled_for,
        "safe_error_code": job.safe_error_code,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "visuals": [
            {
                "id": str(row.pk),
                "image_id": str(row.image_id),
                "image_url": f"/api/v1/subjects/{row.image.subject_id}/images/{row.image_id}/content",
                "role": row.role,
                "ordinal": row.ordinal,
                "source_strategy": row.source_strategy,
            }
            for row in visuals
        ],
        "targets": [
            {
                "id": str(row.pk),
                "platform_key": row.platform.channel.key,
                "platform_name": row.platform.channel.name,
                "status": row.status,
                "scheduled_at": row.scheduled_at,
                "published_at": row.published_at,
                "public_url": row.public_url,
                "external_post_id": row.external_post_id,
                "safe_error_code": row.safe_error_code,
                "attempts": row.attempts,
                "adaptation_id": str(row.adaptation_id) if row.adaptation_id else None,
            }
            for row in targets
        ],
    }


def publication_job_for_user(*, user, job_id):
    try:
        return PublicationJob.objects.select_related("article", "subject", "policy").get(
            pk=job_id, user=user
        )
    except PublicationJob.DoesNotExist as exc:
        raise Http404 from exc


def dashboard_state(*, user, subject_id):
    subject = _subject(user, subject_id)
    policy = get_or_create_policy(user=user, subject_id=subject.pk)
    catalog = platform_catalog(user=user, subject_id=subject.pk)
    today = timezone.localdate()
    targets = PublicationTarget.objects.filter(job__user=user, job__subject=subject)
    today_targets = targets.filter(scheduled_at__date=today)
    recent_jobs = list(
        PublicationJob.objects.select_related("article", "subject", "policy")
        .filter(user=user, subject=subject)
        .order_by("-created_at")[:20]
    )
    return {
        "policy": policy_payload(policy),
        "platforms": catalog,
        "summary": {
            "authorized": sum(
                1
                for row in catalog
                if row.get("account") and row["account"]["auth_status"] == "authorized"
            ),
            "platform_total": len(catalog),
            "today_planned": today_targets.count(),
            "today_published": today_targets.filter(status="published").count(),
            "needs_attention": targets.filter(
                Q(status="requires_auth") | Q(status="failed")
            ).count(),
        },
        "today_targets": [
            item
            for job in recent_jobs
            for item in job_payload(job)["targets"]
            if item["scheduled_at"] and item["scheduled_at"].date() == today
        ],
        "recent_jobs": [job_payload(job) for job in recent_jobs],
    }
