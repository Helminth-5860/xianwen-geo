from __future__ import annotations

import hashlib
import json
import uuid

from django.db import transaction
from django.http import Http404
from django.utils import timezone

from apps.ai.content import StructuredContentPayload
from apps.ai.contracts import AIAdapterRequest, AIModelCapability
from apps.ai.errors import AIAdapterError
from apps.ai.runtime import get_capability_runtime_snapshot
from apps.documents.models import UserDocument
from apps.images.models import ImageAsset
from apps.keywords.models import Keyword, KeywordAssetPreference, KeywordSet
from apps.questions.bank_models import Question, QuestionBankWorkspace
from apps.subjects.models import Subject, SubjectBusinessProfile, SubjectProduct
from apps.subjects.subject_services import subject_for_user_or_404

from .ai import DeepSeekWebsiteAdapter
from .models import WebsiteGenerationJob, WebsiteProject

SITE_SCHEMA_VERSION = 1
MAX_SELECTED_MATERIALS = 12
MAX_KEYWORDS = 20
MAX_QUESTIONS = 20
IMAGE_DOCUMENT_KINDS = {"jpeg", "png", "webp"}
PAGE_KEYS = ("home", "about", "services", "solutions", "faq", "contact")
PAGE_SLUGS = {
    "home": "",
    "about": "about",
    "services": "services",
    "solutions": "solutions",
    "faq": "faq",
    "contact": "contact",
}
SECTION_TYPES = {"hero", "text", "cards", "faq", "contact"}
STYLE_LABELS: dict[str, str] = {
    "professional": "专业商务",
    "technology": "科技简约",
    "premium": "高端品牌",
}


class WebsiteInputError(Exception):
    pass


class WebsiteSchemaError(Exception):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _idempotency_digest(*, user_id, subject_id, raw_key: str) -> str:
    key = raw_key.strip()
    if not key or len(key) > 200 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise WebsiteInputError("请重新提交生成请求")
    value = f"website:v1:{user_id}:{subject_id}:{key}"
    return hashlib.sha256(value.encode()).hexdigest()


def _compact_value(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split())[:4000]
    if isinstance(value, list):
        return [_compact_value(item) for item in value[:30]]
    if isinstance(value, dict):
        return {str(key)[:100]: _compact_value(item) for key, item in list(value.items())[:50]}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def _confirmed_subject_fields(subject: Subject) -> list[dict[str, object]]:
    version = subject.current_version
    if version is None:
        return []
    schema = version.schema_snapshot if isinstance(version.schema_snapshot, dict) else {}
    raw_fields = schema.get("fields")
    fields: list[object] = raw_fields if isinstance(raw_fields, list) else []
    labels: dict[str, str] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_key = field.get("field_key")
        if not isinstance(field_key, str) or field.get("used_for_ai") is not True:
            continue
        label = field.get("label")
        labels[field_key] = label.strip() if isinstance(label, str) and label.strip() else field_key

    results: list[dict[str, object]] = []
    for key, value in version.field_values.items():
        if key not in labels or value in (None, "", [], {}):
            continue
        results.append({"label": labels[key], "value": _compact_value(value)})
    return results[:40]


def _business_profile(subject: Subject) -> dict[str, object]:
    try:
        profile = subject.business_profile
    except SubjectBusinessProfile.DoesNotExist:
        return {}
    return {
        "brand_name": profile.brand_name,
        "primary_business": profile.primary_business,
        "business_address": profile.business_address,
        "contact_name": profile.contact_name,
        "contact_phone": profile.contact_phone,
        "social_channels": _compact_value(profile.social_channels),
    }


def _keyword_rows(*, user, subject: Subject) -> list[str]:
    preferences = list(
        KeywordAssetPreference.objects.filter(
            user=user,
            subject=subject,
            enabled=True,
            deleted_at__isnull=True,
        )
        .select_related("source_keyword")
        .order_by("source_keyword__sort_order", "created_at")[:MAX_KEYWORDS]
    )
    if preferences:
        return [
            item.display_text.strip() or item.source_keyword.text.strip()
            for item in preferences
            if item.display_text.strip() or item.source_keyword.text.strip()
        ]

    keyword_set = (
        KeywordSet.objects.filter(user=user, subject=subject)
        .select_related("current_version")
        .first()
    )
    if keyword_set is None or keyword_set.current_version_id is None:
        return []
    return list(
        Keyword.objects.filter(keyword_set_version=keyword_set.current_version)
        .order_by("sort_order")
        .values_list("text", flat=True)[:MAX_KEYWORDS]
    )


def _question_rows(*, user, subject: Subject) -> list[str]:
    workspace = (
        QuestionBankWorkspace.objects.filter(user=user, subject=subject)
        .select_related("current_version")
        .first()
    )
    if workspace is None or workspace.current_version_id is None:
        return []
    return list(
        Question.objects.filter(
            question_bank_version=workspace.current_version,
            participates_in_scoring=True,
        )
        .order_by("sort_order")
        .values_list("text", flat=True)[:MAX_QUESTIONS]
    )


def _approved_image_queryset(*, user, subject: Subject):
    return ImageAsset.objects.filter(
        user=user,
        subject=subject,
        is_subject_library=True,
        lifecycle_status=ImageAsset.LifecycleStatus.ACTIVE,
        moderation_status=ImageAsset.ModerationStatus.APPROVED,
    )


def _uploaded_image_queryset(*, user, subject: Subject):
    return (
        UserDocument.objects.filter(user=user, subject=subject, current_version__isnull=False)
        .select_related("current_version")
        .filter(current_version__detected_file_kind__in=IMAGE_DOCUMENT_KINDS)
    )


def _selected_materials(
    *,
    user,
    subject: Subject,
    asset_ids: list[uuid.UUID],
    document_ids: list[uuid.UUID],
) -> tuple[list[ImageAsset], list[UserDocument]]:
    unique_asset_ids = list(dict.fromkeys(asset_ids))
    unique_document_ids = list(dict.fromkeys(document_ids))
    if len(unique_asset_ids) + len(unique_document_ids) > MAX_SELECTED_MATERIALS:
        raise WebsiteInputError(f"官网素材最多选择 {MAX_SELECTED_MATERIALS} 张图片")

    asset_rows = list(
        _approved_image_queryset(user=user, subject=subject).filter(pk__in=unique_asset_ids)
    )
    assets_by_id = {row.pk: row for row in asset_rows}
    if len(assets_by_id) != len(unique_asset_ids):
        raise WebsiteInputError("部分图片素材不可用于当前官网，请重新选择")

    document_rows = list(
        _uploaded_image_queryset(user=user, subject=subject).filter(pk__in=unique_document_ids)
    )
    documents_by_id = {row.pk: row for row in document_rows}
    if len(documents_by_id) != len(unique_document_ids):
        raise WebsiteInputError("部分上传图片不可用于当前官网，请重新选择")

    return (
        [assets_by_id[item_id] for item_id in unique_asset_ids],
        [documents_by_id[item_id] for item_id in unique_document_ids],
    )


def _source_snapshot(
    *,
    user,
    subject: Subject,
    assets: list[ImageAsset],
    documents: list[UserDocument],
) -> dict[str, object]:
    version = subject.current_version
    if version is None:
        raise WebsiteInputError("请先完善并保存主体资料")
    products = list(
        SubjectProduct.objects.filter(subject_version=version)
        .order_by("display_value")
        .values_list("display_value", flat=True)[:30]
    )
    return {
        "subject": {
            "official_name": version.official_name,
            "subject_type": subject.subject_type.name,
            "confirmed_fields": _confirmed_subject_fields(subject),
            "products": products,
        },
        "business_profile": _business_profile(subject),
        "keywords": _keyword_rows(user=user, subject=subject),
        "questions": _question_rows(user=user, subject=subject),
        "image_assets": [
            {
                "id": str(asset.pk),
                "source": "内容图片库",
                "role": asset.role,
                "width": asset.width,
                "height": asset.height,
            }
            for asset in assets
        ],
        "uploaded_images": [
            {
                "id": str(document.pk),
                "source": "客户上传",
                "name": document.display_name,
                "file_kind": document.current_version.detected_file_kind,
            }
            for document in documents
            if document.current_version is not None
        ],
    }


def website_readiness(*, user, subject: Subject) -> dict[str, object]:
    version = subject.current_version
    product_count = (
        SubjectProduct.objects.filter(subject_version=version).count() if version is not None else 0
    )
    keywords = _keyword_rows(user=user, subject=subject) if version is not None else []
    questions = _question_rows(user=user, subject=subject) if version is not None else []
    library_count = _approved_image_queryset(user=user, subject=subject).count()
    uploaded_count = _uploaded_image_queryset(user=user, subject=subject).count()
    return {
        "can_generate": subject.status == Subject.Status.ACTIVE and version is not None,
        "subject_ready": subject.status == Subject.Status.ACTIVE and version is not None,
        "product_count": product_count,
        "keyword_count": len(keywords),
        "question_count": len(questions),
        "image_count": library_count + uploaded_count,
        "library_image_count": library_count,
        "uploaded_image_count": uploaded_count,
    }


def _contact_from_snapshot(snapshot: dict[str, object]) -> dict[str, str]:
    profile = snapshot.get("business_profile")
    if not isinstance(profile, dict):
        return {}
    result: dict[str, str] = {}
    keys = (
        "brand_name",
        "primary_business",
        "business_address",
        "contact_name",
        "contact_phone",
    )
    for key in keys:
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    return result


def project_payload(project: WebsiteProject) -> dict[str, object]:
    return {
        "id": str(project.pk),
        "subject_id": str(project.subject_id),
        "subject_version_id": str(project.subject_version_id),
        "style_key": project.style_key,
        "style_name": STYLE_LABELS.get(project.style_key, "专业商务"),
        "status": project.status,
        "selected_asset_ids": project.selected_asset_ids,
        "selected_document_ids": project.selected_document_ids,
        "site_schema_version": project.site_schema_version,
        "site": project.site_json or None,
        "contact": _contact_from_snapshot(project.source_snapshot),
        "generation_count": project.generation_count,
        "error_message": (
            "官网生成暂未完成，请重新尝试" if project.status == WebsiteProject.Status.FAILED else ""
        ),
        "version": project.version,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def job_payload(job: WebsiteGenerationJob) -> dict[str, object]:
    return {
        "id": str(job.pk),
        "project_id": str(job.project_id),
        "status": job.status,
        "error_message": (
            "官网生成暂未完成，请重新尝试"
            if job.status == WebsiteGenerationJob.Status.FAILED
            else ""
        ),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def website_state(*, user, subject_id) -> dict[str, object]:
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    project = (
        WebsiteProject.objects.filter(user=user, subject=subject)
        .select_related("subject", "subject_version")
        .first()
    )
    latest_job = (
        project.generation_jobs.filter(user=user).order_by("-created_at").first()
        if project is not None
        else None
    )
    return {
        "subject": {
            "id": str(subject.pk),
            "official_name": (
                subject.current_version.official_name if subject.current_version is not None else ""
            ),
        },
        "readiness": website_readiness(user=user, subject=subject),
        "project": project_payload(project) if project is not None else None,
        "latest_job": job_payload(latest_job) if latest_job is not None else None,
    }


def website_job_for_user(*, user, job_id) -> WebsiteGenerationJob:
    try:
        return WebsiteGenerationJob.objects.select_related(
            "project",
            "project__subject",
            "project__subject_version",
        ).get(pk=job_id, user=user)
    except WebsiteGenerationJob.DoesNotExist as exc:
        raise Http404 from exc


def _runtime_and_adapter():
    runtime = get_capability_runtime_snapshot(
        provider_key="deepseek",
        capability=AIModelCapability.TEXT_GENERATION,
    )
    return runtime, DeepSeekWebsiteAdapter()


def create_generation_job(
    *,
    user,
    subject_id,
    style_key: str,
    image_asset_ids: list[uuid.UUID],
    document_ids: list[uuid.UUID],
    idempotency_key: str,
    request_id,
) -> tuple[WebsiteProject, WebsiteGenerationJob, bool]:
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    subject_version = subject.current_version
    if subject.status != Subject.Status.ACTIVE or subject_version is None:
        raise WebsiteInputError("请先完善并保存主体资料")
    if style_key not in STYLE_LABELS:
        raise WebsiteInputError("请选择网站风格")

    assets, documents = _selected_materials(
        user=user,
        subject=subject,
        asset_ids=image_asset_ids,
        document_ids=document_ids,
    )
    source_snapshot = _source_snapshot(
        user=user,
        subject=subject,
        assets=assets,
        documents=documents,
    )
    runtime, adapter = _runtime_and_adapter()
    input_snapshot = {
        "style_key": style_key,
        "style_name": STYLE_LABELS[style_key],
        "selected_asset_ids": [str(item.pk) for item in assets],
        "selected_document_ids": [str(item.pk) for item in documents],
        "source": source_snapshot,
    }
    input_digest = _digest(input_snapshot)
    idem = _idempotency_digest(
        user_id=user.pk,
        subject_id=subject.pk,
        raw_key=idempotency_key,
    )

    with transaction.atomic():
        replay = WebsiteGenerationJob.objects.filter(idempotency_key_digest=idem).first()
        if replay is not None:
            if replay.input_digest != input_digest or replay.user_id != user.pk:
                raise WebsiteInputError("生成内容已变化，请重新操作")
            replay_project = WebsiteProject.objects.select_related("subject", "subject_version").get(
                pk=replay.project_id
            )
            return replay_project, replay, False

        existing_project = (
            WebsiteProject.objects.select_for_update().filter(subject=subject, user=user).first()
        )
        if existing_project is None:
            project = WebsiteProject.objects.create(
                user=user,
                subject=subject,
                subject_version=subject_version,
                style_key=style_key,
                status=WebsiteProject.Status.DRAFT,
            )
        else:
            project = existing_project

        running = (
            WebsiteGenerationJob.objects.select_for_update()
            .filter(
                project=project,
                user=user,
                status__in=(
                    WebsiteGenerationJob.Status.QUEUED,
                    WebsiteGenerationJob.Status.RUNNING,
                ),
            )
            .order_by("-created_at")
            .first()
        )
        if running is not None:
            return project, running, False

        project.subject_version = subject_version
        project.style_key = style_key
        project.status = WebsiteProject.Status.GENERATING
        project.selected_asset_ids = [str(item.pk) for item in assets]
        project.selected_document_ids = [str(item.pk) for item in documents]
        project.source_snapshot = source_snapshot
        project.last_error_code = ""
        project.version += 1
        project.save()

        try:
            normalized_request_id = uuid.UUID(str(request_id))
        except (TypeError, ValueError, AttributeError):
            normalized_request_id = uuid.uuid4()
        job = WebsiteGenerationJob.objects.create(
            user=user,
            project=project,
            input_snapshot=input_snapshot,
            input_digest=input_digest,
            provider_key=runtime.provider_key,
            provider_model_id=runtime.provider_model_id,
            adapter_version=adapter.descriptor.adapter_version,
            prompt_version=adapter.descriptor.prompt_version,
            idempotency_key_digest=idem,
            request_id=normalized_request_id,
        )

        from .tasks import execute_website_generation_task

        transaction.on_commit(lambda: execute_website_generation_task.delay(str(job.pk)))
        return project, job, True


def _text(value: object, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise WebsiteSchemaError("text_invalid")
    normalized = " ".join(value.split())
    if (not normalized and not allow_empty) or len(normalized) > maximum:
        raise WebsiteSchemaError("text_invalid")
    return normalized


def _normalize_item(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"title", "body"}:
        raise WebsiteSchemaError("item_invalid")
    return {
        "title": _text(value["title"], 200),
        "body": _text(value["body"], 1500),
    }


def normalize_site_output(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"tagline", "pages"}:
        raise WebsiteSchemaError("site_invalid")
    pages = value["pages"]
    if not isinstance(pages, list) or len(pages) != len(PAGE_KEYS):
        raise WebsiteSchemaError("pages_invalid")

    normalized_pages: list[dict[str, object]] = []
    seen: set[str] = set()
    required_page_fields = {
        "key",
        "title",
        "seo_title",
        "seo_description",
        "sections",
    }
    for page in pages:
        if not isinstance(page, dict) or set(page) != required_page_fields:
            raise WebsiteSchemaError("page_invalid")
        key = page["key"]
        if not isinstance(key, str) or key not in PAGE_KEYS or key in seen:
            raise WebsiteSchemaError("page_key_invalid")
        seen.add(key)
        sections = page["sections"]
        if not isinstance(sections, list) or not 1 <= len(sections) <= 8:
            raise WebsiteSchemaError("sections_invalid")

        normalized_sections: list[dict[str, object]] = []
        for section in sections:
            if not isinstance(section, dict) or set(section) != {
                "type",
                "title",
                "body",
                "items",
            }:
                raise WebsiteSchemaError("section_invalid")
            section_type = section["type"]
            if not isinstance(section_type, str) or section_type not in SECTION_TYPES:
                raise WebsiteSchemaError("section_type_invalid")
            items = section["items"]
            if not isinstance(items, list) or len(items) > 12:
                raise WebsiteSchemaError("section_items_invalid")
            normalized_sections.append(
                {
                    "type": section_type,
                    "title": _text(section["title"], 200, allow_empty=True),
                    "body": _text(section["body"], 3000, allow_empty=True),
                    "items": [_normalize_item(item) for item in items],
                }
            )

        normalized_pages.append(
            {
                "key": key,
                "slug": PAGE_SLUGS[key],
                "title": _text(page["title"], 100),
                "seo_title": _text(page["seo_title"], 120),
                "seo_description": _text(page["seo_description"], 300),
                "sections": normalized_sections,
            }
        )

    if seen != set(PAGE_KEYS):
        raise WebsiteSchemaError("page_set_invalid")
    normalized_pages.sort(key=lambda page: PAGE_KEYS.index(str(page["key"])))
    return {
        "schema_version": SITE_SCHEMA_VERSION,
        "tagline": _text(value["tagline"], 200),
        "pages": normalized_pages,
    }


def _system_prompt() -> str:
    return (
        "你是企业官网内容规划助手。所有可见文案必须使用自然、专业、易理解的中文。"
        "只允许使用 authorized_subject 中已经确认的企业事实，不得虚构客户、案例、资质、"
        "荣誉、数据、地址、电话、网址、团队规模或经营成果。keywords 和 questions 只能用于"
        "自然组织主题，不得堆砌关键词。FAQ 的回答必须能被已确认资料支持。"
        "不要输出 HTML、CSS、Markdown、技术术语或内部沟通语言。"
        "围绕当前主体生成一个适合 GEO 与搜索理解的企业官网草稿。"
        "必须返回 JSON，且只包含两个顶层字段：tagline 和 pages。"
        "pages 必须恰好包含 home、about、services、solutions、faq、contact 六个页面，每个页面"
        "必须恰好包含 key、title、seo_title、seo_description、sections。"
        "每个 sections 元素必须恰好包含 type、title、body、items；type 只能是 hero、text、"
        "cards、faq、contact；items 必须是数组，每项恰好包含 title 和 body。"
        "首页突出主体是谁、做什么、能帮助谁；关于页强调已确认事实；服务页围绕真实产品或服务；"
        "解决方案页按真实业务与用户问题组织；FAQ 优先覆盖已有检测问题；联系页只写联系引导，"
        "具体联系方式由系统从已确认资料展示。不要在文案中承诺未被资料支持的效果。"
    )


def _mark_failed(job_id: str) -> dict[str, str]:
    with transaction.atomic():
        failed = (
            WebsiteGenerationJob.objects.select_for_update()
            .select_related("project")
            .get(pk=job_id)
        )
        if failed.status not in {
            WebsiteGenerationJob.Status.QUEUED,
            WebsiteGenerationJob.Status.RUNNING,
        }:
            return {"status": failed.status}
        failed.status = WebsiteGenerationJob.Status.FAILED
        failed.safe_error_code = "WEBSITE_GENERATION_FAILED"
        failed.finished_at = timezone.now()
        failed.save(update_fields=("status", "safe_error_code", "finished_at", "updated_at"))
        project = WebsiteProject.objects.select_for_update().get(pk=failed.project_id)
        project.status = (
            WebsiteProject.Status.READY if project.site_json else WebsiteProject.Status.FAILED
        )
        project.last_error_code = "WEBSITE_GENERATION_FAILED"
        project.version += 1
        project.save(update_fields=("status", "last_error_code", "version", "updated_at"))
    return {"status": "failed"}


def execute_generation_job(*, job_id: str) -> dict[str, str]:
    with transaction.atomic():
        try:
            job = (
                WebsiteGenerationJob.objects.select_for_update()
                .select_related("project")
                .get(pk=job_id)
            )
        except WebsiteGenerationJob.DoesNotExist:
            return {"status": "missing"}
        if job.status != WebsiteGenerationJob.Status.QUEUED:
            return {"status": job.status}
        job.status = WebsiteGenerationJob.Status.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=("status", "started_at", "updated_at"))

    adapter = DeepSeekWebsiteAdapter()
    try:
        runtime = get_capability_runtime_snapshot(
            provider_key="deepseek",
            capability=AIModelCapability.TEXT_GENERATION,
        )
        response = adapter.invoke(
            AIAdapterRequest(
                request_id=str(job.request_id),
                correlation_id=str(job.request_id),
                identity=adapter.descriptor.identity,
                capability=AIModelCapability.TEXT_GENERATION,
                adapter_version=job.adapter_version,
                prompt_version=job.prompt_version,
                timeout_seconds=runtime.timeout_seconds,
                payload=StructuredContentPayload(
                    provider_model_id=job.provider_model_id,
                    system_prompt=_system_prompt(),
                    user_payload={
                        "site_style": job.input_snapshot.get("style_name", "专业商务"),
                        "authorized_subject": job.input_snapshot.get("source", {}),
                    },
                    max_output_tokens=10_000,
                    temperature=0.2,
                ),
            )
        )
        normalized = normalize_site_output(response.output.content)
    except (AIAdapterError, WebsiteSchemaError, ValueError, TypeError):
        return _mark_failed(job_id)

    with transaction.atomic():
        succeeded = (
            WebsiteGenerationJob.objects.select_for_update()
            .select_related("project")
            .get(pk=job_id)
        )
        if succeeded.status != WebsiteGenerationJob.Status.RUNNING:
            return {"status": succeeded.status}
        project = WebsiteProject.objects.select_for_update().get(pk=succeeded.project_id)
        project.site_json = normalized
        project.status = WebsiteProject.Status.READY
        project.last_error_code = ""
        project.generation_count += 1
        project.version += 1
        project.save(
            update_fields=(
                "site_json",
                "status",
                "last_error_code",
                "generation_count",
                "version",
                "updated_at",
            )
        )
        succeeded.status = WebsiteGenerationJob.Status.SUCCEEDED
        succeeded.provider_request_id = response.provider_request_id or ""
        succeeded.normalized_usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.total_tokens,
        }
        succeeded.finished_at = timezone.now()
        succeeded.save(
            update_fields=(
                "status",
                "provider_request_id",
                "normalized_usage",
                "finished_at",
                "updated_at",
            )
        )
    return {"status": "succeeded"}
