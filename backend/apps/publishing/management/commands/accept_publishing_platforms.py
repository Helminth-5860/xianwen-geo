from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from apps.articles.models import Article
from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.storage import storage_provider
from apps.images.models import ImageAsset
from apps.subjects.models import Subject

from ...catalog import PLATFORM_BY_KEY, PLATFORMS
from ...credentials import (
    PlatformCredentialRuntimeUnavailable,
    platform_credentials,
)
from ...models import PlatformAccount
from ...security import PublishingCredentialError
from ...target_execution import _plain_text, _simple_html
from ...worker_client import PublishingWorkerError, publish_to_platform

PUBLIC_CONFIRMATION = "我确认公开发布验收内容"
IMAGE_REQUIRED_PLATFORM_KEYS = frozenset({"wechat", "xiaohongshu", "douyin"})
SAFE_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


@dataclass(frozen=True)
class AcceptanceCase:
    platform_key: str
    platform_name: str
    title: str
    content_html: str
    content_text: str
    summary: str
    assets: tuple[dict[str, Any], ...]
    credentials: dict[str, Any] = field(repr=False)
    target_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class AcceptanceResult:
    platform_key: str
    platform_name: str
    outcome: str
    message: str


def _bounded_concurrency(value: int) -> int:
    return max(1, min(4, value))


def _platform_keys(raw_values: list[str] | None) -> list[str]:
    if not raw_values:
        return [item.key for item in PLATFORMS]
    values: list[str] = []
    for raw in raw_values:
        for item in raw.split(","):
            key = item.strip().lower()
            if key and key not in values:
                values.append(key)
    unknown = [key for key in values if key not in PLATFORM_BY_KEY]
    if unknown:
        raise CommandError("包含不支持的平台，请检查平台名称后重试")
    if not values:
        raise CommandError("请至少选择一个平台")
    return values


def _safe_worker_message(result: dict[str, Any], publish_mode: str) -> tuple[str, str]:
    success = result.get("success") is True
    status = str(result.get("status") or "")
    if publish_mode == "draft":
        if success and status == "drafted":
            return "passed", "草稿已保存并确认"
        if success and status in {"submitted", "published"}:
            return "failed", "平台未按草稿方式保存，已停止确认"
    elif (
        success
        and status == "published"
        and isinstance(result.get("publicUrl"), str)
        and str(result["publicUrl"]).startswith("https://")
    ):
        return "passed", "公开发布结果已确认"
    elif success and status == "submitted":
        return "failed", "已提交平台，但尚未取得可查看的发布结果"
    if status == "auth_required":
        return "failed", "账号授权已失效"
    if status == "action_required":
        return "failed", "平台需要人工确认结果"
    return "failed", "平台未能确认本次结果"


def _execute_case(case: AcceptanceCase, publish_mode: str) -> AcceptanceResult:
    close_old_connections()
    try:
        result = publish_to_platform(
            platform_key=case.platform_key,
            target_id=case.target_id,
            title=case.title,
            content_html=case.content_html,
            content_text=case.content_text,
            summary=case.summary,
            tags=[],
            assets=list(case.assets),
            credentials=case.credentials,
            publish_mode=publish_mode,
        )
    except PublishingWorkerError:
        return AcceptanceResult(
            case.platform_key,
            case.platform_name,
            "failed",
            "平台服务暂时无法完成验收",
        )
    except Exception:
        # Never include exception details: a provider exception can contain request
        # material or account data. The operator only needs a safe acceptance result.
        return AcceptanceResult(
            case.platform_key,
            case.platform_name,
            "failed",
            "本次验收未完成",
        )
    finally:
        close_old_connections()
    outcome, message = _safe_worker_message(result, publish_mode)
    return AcceptanceResult(case.platform_key, case.platform_name, outcome, message)


class Command(BaseCommand):
    help = "使用当前主体已授权账号，统一验收各平台的草稿保存或公开发布能力"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--subject-id", dest="subject_id")
        parser.add_argument("--article-id", dest="article_id")
        parser.add_argument(
            "--platforms",
            nargs="+",
            help="可填写多个平台名称，也可使用英文逗号分隔；不填则检查全部平台",
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=1,
            help="同时验收的平台数，范围为 1 至 4；默认依次执行，仍会统一汇总",
        )
        parser.add_argument(
            "--public",
            action="store_true",
            dest="public_publish",
            help="改为公开发布；默认只保存草稿",
        )
        parser.add_argument(
            "--confirm-public",
            default="",
            help=f"公开发布时必须完整填写：{PUBLIC_CONFIRMATION}",
        )

    def _subject(self, subject_id: str | None) -> Subject:
        connected = PlatformAccount.objects.filter(status=PlatformAccount.Status.CONNECTED)
        if subject_id:
            try:
                return Subject.objects.get(pk=subject_id)
            except (Subject.DoesNotExist, ValidationError, ValueError) as exc:
                raise CommandError("没有找到指定主体") from exc

        subject_ids = list(connected.order_by().values_list("subject_id", flat=True).distinct()[:2])
        if not subject_ids:
            raise CommandError("当前没有已授权平台账号")
        if len(subject_ids) > 1:
            raise CommandError("存在多个已授权主体，请使用 --subject-id 指定主体")
        return Subject.objects.get(pk=subject_ids[0])

    def _article(self, subject: Subject, article_id: str | None) -> Article:
        articles = (
            Article.objects.filter(
                user_id=subject.user_id,
                subject=subject,
                status=Article.Status.READY,
            )
            .exclude(title="")
            .exclude(content="")
        )
        if article_id:
            try:
                article = articles.get(pk=article_id)
            except (Article.DoesNotExist, ValidationError, ValueError) as exc:
                raise CommandError("指定文章不存在或尚未达到可发布状态") from exc
        else:
            article = articles.order_by("-updated_at", "-id").first()
            if article is None:
                raise CommandError("当前主体没有可用于验收的文章")
        if not article.title.strip() or not article.content.strip():
            raise CommandError("验收文章的标题和正文不能为空")
        return article

    def _account_map(self, subject: Subject) -> dict[str, PlatformAccount]:
        return {
            item.platform_key: item
            for item in PlatformAccount.objects.filter(
                user_id=subject.user_id,
                subject=subject,
                status=PlatformAccount.Status.CONNECTED,
            ).order_by("platform_key", "created_at")
        }

    def _safe_assets(self, subject: Subject, article: Article) -> tuple[dict[str, Any], ...]:
        image = (
            ImageAsset.objects.filter(
                user_id=subject.user_id,
                subject=subject,
                article=article,
                lifecycle_status=ImageAsset.LifecycleStatus.ACTIVE,
                moderation_status=ImageAsset.ModerationStatus.APPROVED,
                mime_type__in=SAFE_IMAGE_MIME_TYPES,
            )
            .exclude(object_key="")
            .order_by("-created_at", "-id")
            .first()
        )
        if image is None:
            image = (
                ImageAsset.objects.filter(
                    user_id=subject.user_id,
                    subject=subject,
                    is_subject_library=True,
                    lifecycle_status=ImageAsset.LifecycleStatus.ACTIVE,
                    moderation_status=ImageAsset.ModerationStatus.APPROVED,
                    mime_type__in=SAFE_IMAGE_MIME_TYPES,
                )
                .exclude(object_key="")
                .order_by("-created_at", "-id")
                .first()
            )
        if image is None:
            return ()
        try:
            url = storage_provider().create_download_url(
                key=image.object_key,
                filename=f"publishing-acceptance-{image.pk}",
                content_type=image.mime_type,
            )
        except FileStorageUnavailable:
            return ()
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            return ()
        return ({"role": "cover", "url": url, "alt": article.title[:120]},)

    def _case(
        self,
        *,
        account: PlatformAccount,
        article: Article,
        assets: tuple[dict[str, Any], ...],
        acceptance_title: str,
    ) -> AcceptanceCase | AcceptanceResult:
        platform = PLATFORM_BY_KEY[account.platform_key]
        if (
            platform.key != "wechat"
            and account.session_expires_at
            and account.session_expires_at <= timezone.now()
        ):
            return AcceptanceResult(
                platform.key,
                platform.name,
                "skipped",
                "账号授权已过期，已跳过",
            )
        if platform.key in IMAGE_REQUIRED_PLATFORM_KEYS and not assets:
            return AcceptanceResult(
                platform.key,
                platform.name,
                "failed",
                "缺少已审核的有效图片，未执行验收",
            )
        try:
            credentials = platform_credentials(account)
        except (PublishingCredentialError, PlatformCredentialRuntimeUnavailable):
            return AcceptanceResult(
                platform.key,
                platform.name,
                "skipped",
                "账号授权当前不可用，已跳过",
            )
        except Exception:
            return AcceptanceResult(
                platform.key,
                platform.name,
                "skipped",
                "账号授权当前不可用，已跳过",
            )

        content_text = _plain_text(article.content)
        return AcceptanceCase(
            platform_key=platform.key,
            platform_name=platform.name,
            title=acceptance_title,
            content_html=_simple_html(article.content),
            content_text=content_text,
            summary=content_text[:180],
            assets=assets,
            credentials=credentials,
        )

    def handle(self, *args, **options) -> None:
        publish_mode = "public" if options["public_publish"] else "draft"
        if publish_mode == "public" and options["confirm_public"] != PUBLIC_CONFIRMATION:
            raise CommandError(
                f'公开发布可能产生真实内容，必须同时填写 --confirm-public "{PUBLIC_CONFIRMATION}"'
            )

        keys = _platform_keys(options.get("platforms"))
        concurrency = _bounded_concurrency(options["concurrency"])
        subject = self._subject(options.get("subject_id"))
        article = self._article(subject, options.get("article_id"))
        if (
            publish_mode == "public"
            and article.moderation_status != Article.Moderation.PASSED
        ):
            raise CommandError("公开发布验收只能使用已通过内容检查的文章")
        account_map = self._account_map(subject)
        assets = self._safe_assets(subject, article)
        run_time = timezone.localtime().strftime("%Y%m%d%H%M%S")
        # Put the unique marker first so platforms with short title limits keep it.
        # A suffix marker may be truncated and accidentally match an older draft.
        marker = f"【验{run_time[-6:]}{uuid.uuid4().hex[:4]}】"
        acceptance_title = f"{marker}{article.title.strip()[: 500 - len(marker)]}"

        results: list[AcceptanceResult] = []
        cases: list[AcceptanceCase] = []
        for key in keys:
            platform = PLATFORM_BY_KEY[key]
            account = account_map.get(key)
            if account is None:
                results.append(AcceptanceResult(key, platform.name, "skipped", "尚未授权，已跳过"))
                continue
            case = self._case(
                account=account,
                article=article,
                assets=assets,
                acceptance_title=acceptance_title,
            )
            if isinstance(case, AcceptanceResult):
                results.append(case)
            else:
                cases.append(case)

        if cases:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                pending = {
                    executor.submit(_execute_case, case, publish_mode): case for case in cases
                }
                for future in as_completed(pending):
                    case = pending[future]
                    try:
                        results.append(future.result())
                    except Exception:
                        results.append(
                            AcceptanceResult(
                                case.platform_key,
                                case.platform_name,
                                "failed",
                                "本次验收未完成",
                            )
                        )

        order = {key: index for index, key in enumerate(keys)}
        results.sort(key=lambda item: order[item.platform_key])
        passed = sum(item.outcome == "passed" for item in results)
        failed = sum(item.outcome == "failed" for item in results)
        skipped = sum(item.outcome == "skipped" for item in results)

        self.stdout.write("统一验收结果")
        for item in results:
            label = "通过" if item.outcome == "passed" else "未通过"
            if item.outcome == "skipped":
                label = "已跳过"
            self.stdout.write(f"- {item.platform_name}：{label}，{item.message}")
        self.stdout.write(
            self.style.SUCCESS(
                f"汇总：共 {len(results)} 个平台，通过 {passed} 个，"
                f"未通过 {failed} 个，跳过 {skipped} 个"
            )
        )

        if failed or skipped:
            raise CommandError("存在未通过或尚未完成的平台，请根据上方结果处理后重新验收")
