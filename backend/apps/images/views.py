from __future__ import annotations

import logging
import uuid
from typing import Any

from django.db import transaction
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_202_ACCEPTED
from rest_framework.views import APIView

from apps.admin_rbac.permissions import HasAdminPermission
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.quotas.exceptions import QuotaError
from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .exceptions import ImageBusinessError
from .models import ImageAsset, ImageSizePreset, ImageStylePreset
from .serializers import (
    AttachImageSerializer,
    ExpectedImageVersionSerializer,
    GenerateImagesSerializer,
    ImageBatchDownloadSerializer,
    ImageDerivativeSerializer,
    ImageSizePresetWriteSerializer,
    ImageStylePresetWriteSerializer,
    ModerationAppealSerializer,
)
from .services import (
    _subject,
    _terminal_failure,
    attach_to_article,
    create_ai_derivative_job,
    create_batch_download,
    create_derivative,
    create_image_job,
    derivative_payload,
    image_job_for_user,
    image_payload,
    job_payload,
    quota_summary,
    recommendations,
    request_moderation_appeal,
    restore_image,
    save_to_library,
    trash_image,
)
from .tasks import execute_image_job_task

logger = logging.getLogger(__name__)


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _image_error(exc: ImageBusinessError, request):
    core_code = (
        ErrorCode.VALIDATION_ERROR
        if exc.status == 422
        else ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE
        if exc.status == 503
        else ErrorCode.PERMISSION_DENIED
        if exc.status == 403
        else ErrorCode.IDEMPOTENCY_CONFLICT
    )
    return _no_store(
        error_response(
            core_code,
            status_code=exc.status,
            request=request,
            message=exc.code,
            details={"image_code": exc.code},
        )
    )


def _quota_error(exc: QuotaError, request):
    return _no_store(
        error_response(
            ErrorCode.QUOTA_INSUFFICIENT
            if exc.code == "QUOTA_INSUFFICIENT"
            else ErrorCode.QUOTA_STATE_CONFLICT,
            status_code=409,
            request=request,
            details={"quota_code": exc.code},
        )
    )


def _enqueue(job):
    try:
        execute_image_job_task.apply_async(args=[str(job.pk)], queue="image_generation")
    except Exception:
        logger.exception(
            "image generation enqueue failed", extra={"context": {"job_id": str(job.pk)}}
        )
        _terminal_failure(job.pk, "IMAGE_QUEUE_UNAVAILABLE")


def _size_payload(row):
    return {
        "id": str(row.pk),
        "key": row.key,
        "name": row.name,
        "aspect_ratio": row.aspect_ratio,
        "width": row.width,
        "height": row.height,
        "applicable_channels": row.applicable_channels,
        "applicable_roles": row.applicable_roles,
        "status": row.status,
        "sort_order": row.sort_order,
        "version": row.version,
    }


def _style_payload(row):
    return {
        "id": str(row.pk),
        "key": row.key,
        "name": row.name,
        "description": row.description,
        "applicable_roles": row.applicable_roles,
        "status": row.status,
        "sort_order": row.sort_order,
        "version": row.version,
    }


def _admin_size_payload(row):
    return {**_size_payload(row), "provider_params": row.provider_params}


def _admin_style_payload(row):
    return {
        **_style_payload(row),
        "prompt_template": row.prompt_template,
        "example_object_key_configured": bool(row.example_object_key),
    }


class ImageSizeListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        rows = ImageSizePreset.objects.filter(status="active")
        return _no_store(Response([_size_payload(row) for row in rows]))


class ImageStyleListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        rows = ImageStylePreset.objects.filter(status="active")
        return _no_store(Response([_style_payload(row) for row in rows]))


class ImageRecommendationView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, article_id):
        try:
            payload = recommendations(user=request.user, article_id=article_id)
        except ImageBusinessError as exc:
            return _image_error(exc, request)
        return _no_store(Response(payload))


class ImageGenerateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = GenerateImagesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        raw_items = data.pop("items", None)
        items = [dict(item) for item in raw_items] if raw_items else [data]
        raw_key = request.headers.get("Idempotency-Key", "")
        request_id = uuid.UUID(str(request.request_id))
        jobs = []
        created_jobs = []
        try:
            with transaction.atomic():
                for index, item in enumerate(items):
                    item = {
                        "article_id": None,
                        "reference_asset_id": None,
                        "reference_document_version_id": None,
                        "reference_url": "",
                        **item,
                    }
                    job, created = create_image_job(
                        user=request.user,
                        subject_id=subject_id,
                        idempotency_key=(raw_key if len(items) == 1 else f"{raw_key}:{index}"),
                        request_id=request_id,
                        **item,
                    )
                    jobs.append(job)
                    if created:
                        created_jobs.append(job)
                transaction.on_commit(lambda: [_enqueue(job) for job in created_jobs])
        except ImageBusinessError as exc:
            return _image_error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        payloads = [job_payload(job) for job in jobs]
        response = {"jobs": payloads, "quota": quota_summary(request.user)}
        if len(payloads) == 1:
            response["job"] = payloads[0]
        return _no_store(Response(response, status=HTTP_202_ACCEPTED))


class ImageJobView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, job_id):
        job = image_job_for_user(user=request.user, job_id=job_id)
        return _no_store(Response(job_payload(job)))


class SubjectImagesView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = _subject(request.user, subject_id)
        rows = ImageAsset.objects.filter(user=request.user, subject=subject)
        if request.query_params.get("trash") != "true":
            rows = rows.filter(lifecycle_status="active")
        if request.query_params.get("library") == "true":
            rows = rows.filter(is_subject_library=True)
        rows = rows.order_by("-created_at", "-id")[:100]
        return _no_store(
            Response(
                {
                    "results": [image_payload(row) for row in rows],
                    "quota": quota_summary(request.user),
                }
            )
        )


class ImageSaveLibraryView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, image_id):
        serializer = ExpectedImageVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            image = save_to_library(
                user=request.user, image_id=image_id, **serializer.validated_data
            )
        except ImageBusinessError as exc:
            return _image_error(exc, request)
        return _no_store(Response(image_payload(image)))


class ImageAttachView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, image_id):
        serializer = AttachImageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            image = attach_to_article(
                user=request.user, image_id=image_id, **serializer.validated_data
            )
        except ImageBusinessError as exc:
            return _image_error(exc, request)
        return _no_store(Response(image_payload(image)))


class ImageDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def delete(self, request, image_id):
        serializer = ExpectedImageVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            image = trash_image(user=request.user, image_id=image_id, **serializer.validated_data)
        except ImageBusinessError as exc:
            return _image_error(exc, request)
        return _no_store(Response(image_payload(image, include_url=False)))


class ImageRestoreView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, image_id):
        serializer = ExpectedImageVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            image = restore_image(user=request.user, image_id=image_id, **serializer.validated_data)
        except ImageBusinessError as exc:
            return _image_error(exc, request)
        return _no_store(Response(image_payload(image)))


class ImageAppealView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, image_id):
        serializer = ModerationAppealSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = request_moderation_appeal(
                user=request.user, image_id=image_id, **serializer.validated_data
            )
        except ImageBusinessError as exc:
            return _image_error(exc, request)
        return _no_store(Response({"status": review.decision, "appeal_no": review.appeal_no}))


class ImageDerivativeView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, image_id):
        serializer = ImageDerivativeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        ai = values.pop("ai")
        try:
            if ai:
                with transaction.atomic():
                    job, created = create_ai_derivative_job(
                        user=request.user,
                        image_id=image_id,
                        idempotency_key=request.headers.get("Idempotency-Key", ""),
                        request_id=uuid.UUID(str(request.request_id)),
                        **values,
                    )
                    if created:
                        transaction.on_commit(lambda: _enqueue(job))
                return _no_store(
                    Response(
                        {"job": job_payload(job), "quota": quota_summary(request.user)},
                        status=HTTP_202_ACCEPTED,
                    )
                )
            row = create_derivative(user=request.user, image_id=image_id, **values)
        except ImageBusinessError as exc:
            return _image_error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        return _no_store(Response(derivative_payload(row), status=HTTP_201_CREATED))


class ImageBatchDownloadView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = ImageBatchDownloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row, url = create_batch_download(user=request.user, **serializer.validated_data)
        except ImageBusinessError as exc:
            return _image_error(exc, request)
        return _no_store(
            Response(
                {
                    "id": str(row.pk),
                    "image_count": row.image_count,
                    "url": url,
                    "url_expires_in": min(
                        row.expires_at.timestamp() - row.created_at.timestamp(), 300
                    ),
                    "expires_at": row.expires_at,
                },
                status=HTTP_201_CREATED,
            )
        )


class AdminPresetListCreateView(APIView):
    permission_classes = [HasAdminPermission]
    required_permissions_by_method = {"GET": "models.list", "POST": "models.manage"}
    model: Any = ImageSizePreset
    serializer_class: Any = ImageSizePresetWriteSerializer
    payload = staticmethod(_admin_size_payload)

    def get(self, request):
        return _no_store(Response([self.payload(row) for row in self.model.objects.all()]))

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        values.pop("expected_version", None)
        required = (
            {"key", "name", "aspect_ratio", "width", "height"}
            if self.model is ImageSizePreset
            else {"key", "name", "prompt_template"}
        )
        if not required.issubset(values):
            return _image_error(ImageBusinessError("IMAGE_PRESET_INVALID", status=422), request)
        row = self.model.objects.create(**values)
        return _no_store(Response(self.payload(row), status=HTTP_201_CREATED))


class AdminSizePresetListCreateView(AdminPresetListCreateView):
    pass


class AdminStylePresetListCreateView(AdminPresetListCreateView):
    model = ImageStylePreset
    serializer_class = ImageStylePresetWriteSerializer
    payload = staticmethod(_admin_style_payload)


class AdminPresetDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "models.manage"
    model: Any = ImageSizePreset
    serializer_class: Any = ImageSizePresetWriteSerializer
    payload = staticmethod(_admin_size_payload)

    @method_decorator(csrf_protect)
    def patch(self, request, preset_id):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        expected_version = values.pop("expected_version", None)
        if expected_version is None:
            return _image_error(ImageBusinessError("IMAGE_VERSION_REQUIRED", status=422), request)
        try:
            with transaction.atomic():
                row = self.model.objects.select_for_update().get(pk=preset_id)
                if row.version != expected_version:
                    raise ImageBusinessError("IMAGE_VERSION_CONFLICT")
                for key, value in values.items():
                    setattr(row, key, value)
                row.version += 1
                row.save()
        except self.model.DoesNotExist as exc:
            raise Http404 from exc
        except ImageBusinessError as exc:
            return _image_error(exc, request)
        return _no_store(Response(self.payload(row)))


class AdminSizePresetDetailView(AdminPresetDetailView):
    pass


class AdminStylePresetDetailView(AdminPresetDetailView):
    model = ImageStylePreset
    serializer_class = ImageStylePresetWriteSerializer
    payload = staticmethod(_admin_style_payload)
