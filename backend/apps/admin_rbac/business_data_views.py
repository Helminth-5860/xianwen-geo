from __future__ import annotations

from math import ceil
from uuid import UUID

from django.db.models import Q
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.articles.models import Article
from apps.geo.models import GeoDetectionJob, GeoReport
from apps.images.models import ImageAsset
from apps.questions.bank_models import Question
from apps.subjects.models import Subject
from apps.users.phone_numbers import mask_phone

from .permissions import HasSuperuserAdminSession

PAGE_SIZE = 20
MAX_QUERY_LENGTH = 120
RESOURCE_TYPES = frozenset(
    {
        "subjects",
        "questions",
        "detections",
        "reports",
        "articles",
        "images",
    }
)

STATUS_LABELS = {
    "subjects": {
        "draft": "草稿",
        "active": "启用",
        "archived": "已归档",
    },
    "questions": {"confirmed": "已确认"},
    "detections": {
        "queued": "排队中",
        "running": "运行中",
        "partial": "部分完成",
        "succeeded": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
    },
    "reports": {"generated": "已生成"},
    "articles": {
        "draft": "草稿",
        "generating": "生成中",
        "reviewing": "审核中",
        "ready": "就绪",
        "rejected": "已驳回",
    },
    "images": {
        "active": "可用",
        "trashed": "已删除",
    },
}


def _parse_page(request) -> int:
    raw_page = request.query_params.get("page", "1")
    try:
        page = int(raw_page)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": ["分页参数不正确。"]}) from exc
    if page < 1:
        raise ValidationError({"page": ["页码必须大于等于 1。"]})
    return page


def _parse_resource(request) -> str:
    resource = request.query_params.get("resource", "subjects").strip()
    if resource not in RESOURCE_TYPES:
        raise ValidationError({"resource": ["业务数据类型不正确。"]})
    return resource


def _parse_query(request) -> str:
    return request.query_params.get("q", "").strip()[:MAX_QUERY_LENGTH]


def _parse_uuid(value: str) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _subject_name(subject: Subject) -> str:
    current_version = getattr(subject, "current_version", None)
    if current_version and current_version.official_name:
        return current_version.official_name
    if subject.bound_official_name:
        return subject.bound_official_name
    return f"主体 {str(subject.pk)[:8]}"


def _user_payload(user) -> dict:
    tenant = getattr(user, "tenant", None)
    return {
        "user_id": str(user.pk),
        "user_name": user.nickname,
        "user_phone_masked": mask_phone(user.phone),
        "tenant_id": str(tenant.pk) if tenant else None,
        "tenant_name": tenant.display_name if tenant else None,
    }


def _item_payload(
    *,
    resource: str,
    item_id,
    title: str,
    status: str,
    user,
    subject: Subject | None,
    created_at,
    updated_at,
    metadata: dict,
) -> dict:
    return {
        "id": str(item_id),
        "resource_type": resource,
        "title": title,
        "status": status,
        "status_label": STATUS_LABELS[resource].get(status, status),
        **_user_payload(user),
        "subject_id": str(subject.pk) if subject else None,
        "subject_name": _subject_name(subject) if subject else None,
        "created_at": created_at,
        "updated_at": updated_at,
        "metadata": metadata,
    }


def _common_search(prefix_user: str, prefix_subject: str, keyword: str) -> Q:
    conditions = (
        Q(**{f"{prefix_user}__nickname__icontains": keyword})
        | Q(**{f"{prefix_user}__phone__icontains": keyword})
        | Q(**{f"{prefix_user}__tenant__display_name__icontains": keyword})
        | Q(**{f"{prefix_subject}__bound_official_name__icontains": keyword})
        | Q(**{f"{prefix_subject}__current_version__official_name__icontains": keyword})
    )
    parsed_uuid = _parse_uuid(keyword)
    if parsed_uuid:
        conditions |= (
            Q(**{f"{prefix_user}__id": parsed_uuid})
            | Q(**{f"{prefix_subject}__id": parsed_uuid})
        )
    return conditions


def _subjects(keyword: str):
    queryset = Subject.objects.select_related(
        "user__tenant", "tenant", "subject_type", "current_version"
    ).order_by("-updated_at", "-id")
    if keyword:
        conditions = (
            Q(user__nickname__icontains=keyword)
            | Q(user__phone__icontains=keyword)
            | Q(user__tenant__display_name__icontains=keyword)
            | Q(tenant__display_name__icontains=keyword)
            | Q(bound_official_name__icontains=keyword)
            | Q(current_version__official_name__icontains=keyword)
            | Q(subject_type__name__icontains=keyword)
        )
        parsed_uuid = _parse_uuid(keyword)
        if parsed_uuid:
            conditions |= Q(pk=parsed_uuid) | Q(user_id=parsed_uuid) | Q(tenant_id=parsed_uuid)
        queryset = queryset.filter(conditions)
    return queryset


def _serialize_subject(subject: Subject) -> dict:
    return _item_payload(
        resource="subjects",
        item_id=subject.pk,
        title=_subject_name(subject),
        status=subject.status,
        user=subject.user,
        subject=subject,
        created_at=subject.created_at,
        updated_at=subject.updated_at,
        metadata={
            "主体类型": subject.subject_type.name,
            "版本": subject.version,
            "需复测": subject.retest_required,
        },
    )


def _questions(keyword: str):
    queryset = Question.objects.select_related(
        "question_bank_version__user__tenant",
        "question_bank_version__subject__current_version",
        "question_bank_version__subject__subject_type",
        "primary_category",
    ).order_by("-created_at", "-id")
    if keyword:
        conditions = (
            Q(text__icontains=keyword)
            | Q(primary_category_name__icontains=keyword)
            | _common_search(
                "question_bank_version__user",
                "question_bank_version__subject",
                keyword,
            )
        )
        parsed_uuid = _parse_uuid(keyword)
        if parsed_uuid:
            conditions |= Q(pk=parsed_uuid) | Q(question_bank_version_id=parsed_uuid)
        queryset = queryset.filter(conditions)
    return queryset


def _serialize_question(question: Question) -> dict:
    bank = question.question_bank_version
    return _item_payload(
        resource="questions",
        item_id=question.pk,
        title=question.text,
        status="confirmed",
        user=bank.user,
        subject=bank.subject,
        created_at=question.created_at,
        updated_at=question.created_at,
        metadata={
            "分类": question.primary_category_name,
            "优先级": question.priority,
            "问题类型": question.question_type,
            "参与评分": question.participates_in_scoring,
            "问题库版本": bank.version_no,
        },
    )


def _detections(keyword: str):
    queryset = GeoDetectionJob.objects.select_related(
        "user__tenant", "subject__current_version", "subject__subject_type"
    ).order_by("-created_at", "-id")
    if keyword:
        conditions = _common_search("user", "subject", keyword)
        parsed_uuid = _parse_uuid(keyword)
        if parsed_uuid:
            conditions |= Q(pk=parsed_uuid) | Q(request_id=parsed_uuid)
        queryset = queryset.filter(conditions)
    return queryset


def _serialize_detection(job: GeoDetectionJob) -> dict:
    return _item_payload(
        resource="detections",
        item_id=job.pk,
        title=f"检测任务 {str(job.pk)[:8]}",
        status=job.status,
        user=job.user,
        subject=job.subject,
        created_at=job.created_at,
        updated_at=job.updated_at,
        metadata={
            "计划问题": job.planned_question_count,
            "计划模型": job.planned_model_count,
            "计划检测点": job.planned_detection_points,
            "已完成调用": job.completed_calls,
            "成功调用": job.successful_calls,
            "失败调用": job.failed_calls,
        },
    )


def _reports(keyword: str):
    queryset = GeoReport.objects.select_related(
        "user__tenant", "subject__current_version", "subject__subject_type", "job"
    ).order_by("-generated_at", "-id")
    if keyword:
        conditions = _common_search("user", "subject", keyword)
        parsed_uuid = _parse_uuid(keyword)
        if parsed_uuid:
            conditions |= (
                Q(pk=parsed_uuid)
                | Q(job_id=parsed_uuid)
                | Q(baseline_report_id=parsed_uuid)
            )
        queryset = queryset.filter(conditions)
    return queryset


def _serialize_report(report: GeoReport) -> dict:
    return _item_payload(
        resource="reports",
        item_id=report.pk,
        title=f"GEO 报告 {str(report.pk)[:8]}",
        status="generated",
        user=report.user,
        subject=report.subject,
        created_at=report.generated_at,
        updated_at=report.generated_at,
        metadata={
            "检测任务": str(report.job_id),
            "评分规则版本": report.scoring_rule_version,
            "复测模式": report.retest_mode or "首次检测",
            "基线报告": str(report.baseline_report_id) if report.baseline_report_id else None,
        },
    )


def _articles(keyword: str):
    queryset = Article.objects.select_related(
        "user__tenant", "subject__current_version", "subject__subject_type", "article_type"
    ).order_by("-updated_at", "-id")
    if keyword:
        conditions = (
            Q(title__icontains=keyword)
            | Q(custom_type__icontains=keyword)
            | _common_search("user", "subject", keyword)
        )
        parsed_uuid = _parse_uuid(keyword)
        if parsed_uuid:
            conditions |= Q(pk=parsed_uuid)
        queryset = queryset.filter(conditions)
    return queryset


def _serialize_article(article: Article) -> dict:
    article_type = article.article_type.name if article.article_type else article.custom_type
    return _item_payload(
        resource="articles",
        item_id=article.pk,
        title=article.title or f"未命名文章 {str(article.pk)[:8]}",
        status=article.status,
        user=article.user,
        subject=article.subject,
        created_at=article.created_at,
        updated_at=article.updated_at,
        metadata={
            "文章类型": article_type or "未分类",
            "内容深度": article.content_depth,
            "质量分": article.current_quality_score,
            "审核状态": article.moderation_status,
            "版本": article.version,
        },
    )


def _images(keyword: str):
    queryset = ImageAsset.objects.select_related(
        "user__tenant",
        "subject__current_version",
        "subject__subject_type",
        "generation_job",
        "article",
    ).order_by("-updated_at", "-id")
    if keyword:
        conditions = _common_search("user", "subject", keyword)
        parsed_uuid = _parse_uuid(keyword)
        if parsed_uuid:
            conditions |= (
                Q(pk=parsed_uuid)
                | Q(generation_job_id=parsed_uuid)
                | Q(article_id=parsed_uuid)
            )
        queryset = queryset.filter(conditions)
    return queryset


def _serialize_image(asset: ImageAsset) -> dict:
    return _item_payload(
        resource="images",
        item_id=asset.pk,
        title=f"图片 {str(asset.pk)[:8]}",
        status=asset.lifecycle_status,
        user=asset.user,
        subject=asset.subject,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        metadata={
            "来源": asset.source_type,
            "用途": asset.role,
            "尺寸": f"{asset.width}×{asset.height}",
            "审核状态": asset.moderation_status,
            "主体图片库": asset.is_subject_library,
            "生成任务": str(asset.generation_job_id) if asset.generation_job_id else None,
            "文章": str(asset.article_id) if asset.article_id else None,
        },
    )


RESOURCE_HANDLERS = {
    "subjects": (_subjects, _serialize_subject),
    "questions": (_questions, _serialize_question),
    "detections": (_detections, _serialize_detection),
    "reports": (_reports, _serialize_report),
    "articles": (_articles, _serialize_article),
    "images": (_images, _serialize_image),
}


class BusinessDataView(APIView):
    permission_classes = [HasSuperuserAdminSession]

    def get(self, request):
        resource = _parse_resource(request)
        keyword = _parse_query(request)
        page = _parse_page(request)
        queryset_factory, serializer = RESOURCE_HANDLERS[resource]
        queryset = queryset_factory(keyword)
        count = queryset.count()
        offset = (page - 1) * PAGE_SIZE
        rows = queryset[offset : offset + PAGE_SIZE]
        return Response(
            {
                "resource": resource,
                "query": keyword,
                "items": [serializer(row) for row in rows],
                "page": page,
                "page_size": PAGE_SIZE,
                "total": count,
                "total_pages": ceil(count / PAGE_SIZE) if count else 0,
            }
        )
