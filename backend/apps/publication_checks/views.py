from __future__ import annotations

from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED
from rest_framework.views import APIView

from apps.subjects.permissions import IsAvailableAuthenticatedUser
from apps.subjects.subject_services import subject_for_user_or_404

from .models import PublicationVerificationCheck
from .serializers import (
    PublicationVerificationBulkDeleteSerializer,
    PublicationVerificationCreateSerializer,
)
from .services import create_publication_verification, publication_verification_payload

_ALLOWED_STATUSES = {
    PublicationVerificationCheck.Status.PUBLISHED,
    PublicationVerificationCheck.Status.FAILED,
    PublicationVerificationCheck.Status.UNKNOWN,
}


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _positive_int(raw: str | None, default: int, *, maximum: int) -> int:
    try:
        parsed = int(raw or default)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(1, parsed))


def _stats(query):
    total = query.count()
    published = query.filter(status=PublicationVerificationCheck.Status.PUBLISHED).count()
    failed = query.filter(status=PublicationVerificationCheck.Status.FAILED).count()
    unknown = query.filter(status=PublicationVerificationCheck.Status.UNKNOWN).count()
    success_rate = round((published / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "published": published,
        "failed": failed,
        "unknown": unknown,
        "success_rate": success_rate,
    }


class SubjectPublicationVerificationView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        page = _positive_int(request.query_params.get("page"), 1, maximum=100000)
        page_size = _positive_int(request.query_params.get("page_size"), 10, maximum=50)
        requested_status = (request.query_params.get("status") or "").strip().lower()

        base_query = PublicationVerificationCheck.objects.filter(
            user=request.user,
            subject=subject,
        )
        query = base_query
        if requested_status in _ALLOWED_STATUSES:
            query = query.filter(status=requested_status)

        count = query.count()
        rows = query[(page - 1) * page_size : page * page_size]
        return _no_store(
            Response(
                {
                    "items": [publication_verification_payload(row) for row in rows],
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "count": count,
                        "total_pages": (count + page_size - 1) // page_size,
                    },
                    "stats": _stats(base_query),
                }
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = PublicationVerificationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = create_publication_verification(
            user=request.user,
            subject_id=subject_id,
            **serializer.validated_data,
        )
        return _no_store(Response(publication_verification_payload(row), status=HTTP_201_CREATED))


class PublicationVerificationDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def delete(self, request, subject_id, check_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        try:
            row = PublicationVerificationCheck.objects.get(
                pk=check_id,
                user=request.user,
                subject=subject,
            )
        except PublicationVerificationCheck.DoesNotExist as exc:
            raise Http404 from exc
        row.delete()
        return _no_store(Response({"deleted": True, "id": str(check_id)}))


class PublicationVerificationBulkDeleteView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        serializer = PublicationVerificationBulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        deleted, _ = PublicationVerificationCheck.objects.filter(
            pk__in=ids,
            user=request.user,
            subject=subject,
        ).delete()
        return _no_store(Response({"deleted": deleted}))
