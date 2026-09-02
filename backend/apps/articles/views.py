from __future__ import annotations

import logging
from functools import partial

from django.db import transaction
from django.http import FileResponse, Http404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_202_ACCEPTED
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.storage import storage_provider
from apps.quotas.exceptions import QuotaError
from apps.subjects.permissions import IsAvailableAuthenticatedUser
from apps.subjects.subject_services import subject_for_user_or_404

from .models import (
    Article,
    ArticleComparisonCandidate,
    ArticleExport,
    ArticleGenerationJob,
    ArticleModerationReview,
    ArticleType,
    ChannelAdaptation,
    PublicationLinkCheck,
    PublishingChannel,
)
from .serializers import (
    AdaptationWriteSerializer,
    ArticleCreateSerializer,
    ArticleDraftSerializer,
    ArticleExportSerializer,
    ChannelBatchSerializer,
    ComparisonChoiceSerializer,
    OptimizationSerializer,
    OutlineWriteSerializer,
    PublicationCheckSerializer,
    SourcePackConfirmSerializer,
    SourcePackCreateSerializer,
)
from .services import (
    ContentError,
    adaptation_payload,
    appeal_moderation,
    article_for_user,
    article_payload,
    autosave_article,
    channel_payload,
    check_publication_link,
    choose_comparison,
    confirm_source_pack,
    create_article,
    create_article_export,
    create_channel_jobs,
    create_generation_job,
    create_source_pack,
    job_payload,
    publication_payload,
    quality_payload,
    quota_summary,
    save_outline,
    source_pack_for_user,
    source_pack_payload,
    update_adaptation,
)
from .tasks import execute_generation_job_task

logger = logging.getLogger(__name__)


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _content_error(exc, request):
    return error_response(
        ErrorCode.VALIDATION_ERROR
        if exc.status == 422
        else ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE
        if exc.status == 503
        else ErrorCode.PERMISSION_DENIED
        if exc.status == 403
        else ErrorCode.IDEMPOTENCY_CONFLICT,
        status_code=exc.status,
        request=request,
        message=exc.code,
        details={"content_code": exc.code},
    )


def _quota_error(exc, request):
    return error_response(
        ErrorCode.QUOTA_INSUFFICIENT
        if exc.code == "QUOTA_INSUFFICIENT"
        else ErrorCode.QUOTA_STATE_CONFLICT,
        status_code=409,
        request=request,
        details={"quota_code": exc.code},
    )


def _enqueue(job):
    try:
        execute_generation_job_task.apply_async(args=[str(job.pk)], queue="ai_content")
    except Exception:
        logger.exception(
            "article generation enqueue failed", extra={"context": {"job_id": str(job.pk)}}
        )
        from .services import _failure

        _failure(job.pk, "ARTICLE_QUEUE_UNAVAILABLE")


class ArticleTypeListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        items = []
        for row in ArticleType.objects.filter(status="active").prefetch_related("versions"):
            template = next((version for version in row.versions.all() if version.is_current), None)
            if template is None:
                continue
            items.append(
                {
                    "id": str(row.pk),
                    "key": row.key,
                    "name": row.name,
                    "description": row.description,
                    "template_version": {
                        "id": str(template.pk),
                        "version_no": template.version_no,
                        "structure": template.structure,
                        "network_policy": template.network_policy,
                        "citation_required": template.citation_required,
                        "allowed_source_types": template.allowed_source_types,
                        "recommended_channel_keys": template.recommended_channel_keys,
                    },
                }
            )
        return _no_store(Response({"items": items}))


class SourcePackCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = SourcePackCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            pack = create_source_pack(user=request.user, **serializer.validated_data)
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(Response(source_pack_payload(pack), status=HTTP_201_CREATED))


class SourcePackDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, pack_id):
        return _no_store(Response(source_pack_payload(source_pack_for_user(request.user, pack_id))))


class SourcePackSearchView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, pack_id):
        pack = source_pack_for_user(request.user, pack_id)
        return _no_store(
            Response(
                {**source_pack_payload(pack), "search_status": "succeeded"},
                status=HTTP_202_ACCEPTED,
            )
        )


class SourcePackConfirmView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, pack_id):
        serializer = SourcePackConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            pack = confirm_source_pack(
                user=request.user, pack_id=pack_id, **serializer.validated_data
            )
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(Response(source_pack_payload(pack)))


class SubjectArticleListCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        page = max(1, int(request.query_params.get("page", "1")))
        page_size = min(100, max(1, int(request.query_params.get("page_size", "20"))))
        query = Article.objects.filter(subject=subject, user=request.user).select_related(
            "article_type", "template_version", "primary_channel", "source_pack"
        )
        if request.query_params.get("library") == "1":
            query = query.filter(autosaved_at__isnull=False).exclude(content="")
        count = query.count()
        rows = query[(page - 1) * page_size : page * page_size]
        return _no_store(
            Response(
                {
                    "items": [article_payload(row) for row in rows],
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "count": count,
                        "total_pages": (count + page_size - 1) // page_size,
                    },
                    "quota": quota_summary(request.user, subject),
                }
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = ArticleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            article = create_article(
                user=request.user, subject_id=subject_id, **serializer.validated_data
            )
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(Response(article_payload(article), status=HTTP_201_CREATED))


class ArticleDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, article_id):
        return _no_store(Response(article_payload(article_for_user(request.user, article_id))))


class ArticleDraftView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def patch(self, request, article_id):
        serializer = ArticleDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            article = autosave_article(
                user=request.user, article_id=article_id, **serializer.validated_data
            )
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(Response(article_payload(article)))


def _generation_response(request, article_id, operation, extra=None):
    try:
        with transaction.atomic():
            job, created = create_generation_job(
                user=request.user,
                article_id=article_id,
                operation=operation,
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                request_id=request.request_id,
                extra=extra,
            )
            if created:
                transaction.on_commit(lambda: _enqueue(job))
    except ContentError as exc:
        return _content_error(exc, request)
    except QuotaError as exc:
        return _quota_error(exc, request)
    return _no_store(Response(job_payload(job), status=HTTP_202_ACCEPTED))


class OutlineGenerateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, article_id):
        return _generation_response(request, article_id, "outline")


class OutlineView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def patch(self, request, article_id):
        serializer = OutlineWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            outline = save_outline(
                user=request.user, article_id=article_id, **serializer.validated_data
            )
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(
            Response(
                {
                    "text": outline.text,
                    "status": outline.status,
                    "version": outline.version,
                    "confirmed_at": outline.confirmed_at,
                }
            )
        )


class ArticleGenerateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, article_id):
        return _generation_response(request, article_id, "body")


class ArticleQualityCheckView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, article_id):
        return _generation_response(request, article_id, "quality")


class ArticleQualityView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, article_id):
        article = article_for_user(request.user, article_id)
        check = article.quality_checks.order_by("-created_at", "-id").first()
        if check is None:
            raise Http404
        return _no_store(Response(quality_payload(check)))


class ArticleOptimizeView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]
    operation = "local_optimize"

    @method_decorator(csrf_protect)
    def post(self, request, article_id):
        serializer = OptimizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if (
            self.operation == "local_optimize"
            and not serializer.validated_data["selection"].strip()
        ):
            return _content_error(
                ContentError("ARTICLE_LOCAL_SELECTION_REQUIRED", status=422), request
            )
        return _generation_response(request, article_id, self.operation, serializer.validated_data)


class ArticleFullOptimizeView(ArticleOptimizeView):
    operation = "full_optimize"


class ComparisonView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, comparison_id):
        try:
            row = ArticleComparisonCandidate.objects.select_related("article").get(
                pk=comparison_id, article__user=request.user
            )
        except ArticleComparisonCandidate.DoesNotExist as exc:
            raise Http404 from exc
        if row.status != "pending" or row.expires_at <= timezone.now():
            return _content_error(ContentError("ARTICLE_COMPARISON_UNAVAILABLE"), request)
        return _no_store(
            Response(
                {
                    "id": str(row.pk),
                    "article_id": str(row.article_id),
                    "original": {"title": row.original_title, "content": row.original_content},
                    "optimized": {"title": row.optimized_title, "content": row.optimized_content},
                    "expires_at": row.expires_at,
                }
            )
        )


class ComparisonChooseView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, comparison_id):
        serializer = ComparisonChoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            article = choose_comparison(
                user=request.user, comparison_id=comparison_id, **serializer.validated_data
            )
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(Response(article_payload(article)))


class ArticleModerationView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, article_id):
        article = article_for_user(request.user, article_id)
        reviews = ArticleModerationReview.objects.filter(article=article).order_by(
            "created_at", "id"
        )
        return _no_store(
            Response(
                {
                    "status": article.moderation_status,
                    "blocks_distribution": article.moderation_status != "passed",
                    "appeal_available": article.moderation_status in {"manual_review", "rejected"}
                    and not reviews.filter(kind="appeal").exists(),
                    "reviews": [
                        {
                            "kind": row.kind,
                            "result": row.result,
                            "responsibility": row.responsibility,
                            "safe_reason_code": row.safe_reason_code,
                            "review_no": row.review_no,
                            "created_at": row.created_at,
                        }
                        for row in reviews
                    ],
                }
            )
        )


class ArticleModerationAppealView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, article_id):
        try:
            review = appeal_moderation(user=request.user, article_id=article_id)
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(
            Response(
                {"review_id": str(review.pk), "status": review.result}, status=HTTP_202_ACCEPTED
            )
        )


class GenerationJobView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, job_id):
        try:
            job = ArticleGenerationJob.objects.select_related("article").get(
                pk=job_id, article__user=request.user
            )
        except ArticleGenerationJob.DoesNotExist as exc:
            raise Http404 from exc
        return _no_store(Response(job_payload(job)))


class PublishingChannelListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        return _no_store(
            Response(
                {
                    "items": [
                        channel_payload(row)
                        for row in PublishingChannel.objects.filter(enabled=True).prefetch_related(
                            "versions"
                        )
                    ]
                }
            )
        )


class ArticleChannelAdaptationsView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, article_id):
        article = article_for_user(request.user, article_id)
        page = max(1, int(request.query_params.get("page", "1")))
        page_size = min(100, max(1, int(request.query_params.get("page_size", "20"))))
        query = article.channel_adaptations.select_related(
            "channel", "template_version", "job"
        ).all()
        count = query.count()
        rows = query[(page - 1) * page_size : page * page_size]
        return _no_store(
            Response(
                {
                    "items": [adaptation_payload(row) for row in rows],
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "count": count,
                        "total_pages": (count + page_size - 1) // page_size,
                    },
                }
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request, article_id):
        serializer = ChannelBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                rows = create_channel_jobs(
                    user=request.user,
                    article_id=article_id,
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=request.request_id,
                    **serializer.validated_data,
                )
                for _, job, created in rows:
                    if created:
                        transaction.on_commit(partial(_enqueue, job))
        except ContentError as exc:
            return _content_error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        return _no_store(
            Response(
                {
                    "items": [
                        {**adaptation_payload(adaptation), "job": job_payload(job)}
                        for adaptation, job, _ in rows
                    ],
                    "estimated_article_credits": len(rows),
                },
                status=HTTP_202_ACCEPTED,
            )
        )


class ChannelAdaptationView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, adaptation_id):
        try:
            row = ChannelAdaptation.objects.select_related(
                "article", "channel", "template_version", "job"
            ).get(pk=adaptation_id, article__user=request.user)
        except ChannelAdaptation.DoesNotExist as exc:
            raise Http404 from exc
        return _no_store(Response(adaptation_payload(row)))

    @method_decorator(csrf_protect)
    def patch(self, request, adaptation_id):
        serializer = AdaptationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = update_adaptation(
                user=request.user, adaptation_id=adaptation_id, **serializer.validated_data
            )
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(Response(adaptation_payload(row)))


class PublicationChecksView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = PublicationCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = check_publication_link(user=request.user, **serializer.validated_data)
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(Response(publication_payload(row), status=HTTP_201_CREATED))


class PublicationCheckDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, check_id):
        try:
            row = PublicationLinkCheck.objects.get(pk=check_id, user=request.user)
        except PublicationLinkCheck.DoesNotExist as exc:
            raise Http404 from exc
        return _no_store(Response(publication_payload(row)))


class SubjectPublicationChecksView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        page = max(1, int(request.query_params.get("page", "1")))
        page_size = min(100, max(1, int(request.query_params.get("page_size", "20"))))
        query = PublicationLinkCheck.objects.filter(user=request.user, subject=subject)
        count = query.count()
        rows = query[(page - 1) * page_size : page * page_size]
        return _no_store(
            Response(
                {
                    "items": [publication_payload(row) for row in rows],
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "count": count,
                        "total_pages": (count + page_size - 1) // page_size,
                    },
                }
            )
        )


class ArticleExportView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, article_id):
        serializer = ArticleExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            export, _ = create_article_export(
                user=request.user, article_id=article_id, **serializer.validated_data
            )
        except ContentError as exc:
            return _content_error(exc, request)
        except FileStorageUnavailable:
            return _content_error(
                ContentError("ARTICLE_EXPORT_STORAGE_UNAVAILABLE", status=503), request
            )
        return _no_store(
            Response(
                {
                    "id": str(export.pk),
                    "article_id": str(export.article_id),
                    "format": export.format,
                    "download_url": request.build_absolute_uri(
                        reverse("article-export-download", args=(export.pk,))
                    ),
                    "filename": _export_filename(export),
                    "created_at": export.created_at,
                },
                status=HTTP_201_CREATED,
            )
        )


def _export_filename(export: ArticleExport) -> str:
    extension = {
        "word": "docx",
        "pdf": "pdf",
        "txt": "txt",
        "markdown": "md",
        "html": "html",
    }[export.format]
    title = "".join(
        char for char in (export.article.title or "未命名文章") if char not in '\\/:*?"<>|'
    ).strip()[:80]
    return f"{title or '未命名文章'}.{extension}"


class ArticleExportDownloadView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, export_id):
        try:
            export = ArticleExport.objects.select_related("article").get(
                pk=export_id, user=request.user
            )
            stream = storage_provider().open_object(export.object_key)
        except ArticleExport.DoesNotExist as exc:
            raise Http404 from exc
        except FileStorageUnavailable:
            return _content_error(
                ContentError("ARTICLE_EXPORT_STORAGE_UNAVAILABLE", status=503), request
            )
        content_type = {
            "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pdf": "application/pdf",
            "txt": "text/plain; charset=utf-8",
            "markdown": "text/markdown; charset=utf-8",
            "html": "text/html; charset=utf-8",
        }[export.format]
        return _no_store(
            FileResponse(
                stream,
                as_attachment=True,
                filename=_export_filename(export),
                content_type=content_type,
            )
        )
