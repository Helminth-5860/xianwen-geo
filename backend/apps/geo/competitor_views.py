from __future__ import annotations

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_204_NO_CONTENT
from rest_framework.views import APIView

from apps.core.responses import error_response
from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .competitor_comparison import competitor_comparison_payload
from .competitor_management import (
    CompetitorBusinessError,
    competitor_list_payload,
    competitor_payload,
    create_competitor,
    remove_competitor,
    update_competitor,
)
from .serializers import (
    SubjectCompetitorCreateSerializer,
    SubjectCompetitorUpdateSerializer,
)


def _no_store(response: Response) -> Response:
    response["Cache-Control"] = "no-store"
    return response


def _competitor_error(exc: CompetitorBusinessError, request) -> Response:
    return _no_store(
        error_response(
            exc.code,
            status_code=exc.status,
            request=request,
        )
    )


class SubjectCompetitorListCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        return _no_store(
            Response(competitor_list_payload(user=request.user, subject_id=subject_id))
        )

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = SubjectCompetitorCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            competitor = create_competitor(
                user=request.user,
                subject_id=subject_id,
                name=serializer.validated_data["name"],
                website=serializer.validated_data["website"],
            )
        except CompetitorBusinessError as exc:
            return _competitor_error(exc, request)
        return _no_store(
            Response(
                {"competitor": competitor_payload(competitor)},
                status=HTTP_201_CREATED,
            )
        )


class SubjectCompetitorDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def patch(self, request, subject_id, competitor_id):
        serializer = SubjectCompetitorUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            competitor = update_competitor(
                user=request.user,
                subject_id=subject_id,
                competitor_id=competitor_id,
                name=serializer.validated_data.get("name"),
                website=serializer.validated_data.get("website"),
                expected_version=serializer.validated_data["expected_version"],
            )
        except CompetitorBusinessError as exc:
            return _competitor_error(exc, request)
        return _no_store(Response({"competitor": competitor_payload(competitor)}))

    @method_decorator(csrf_protect)
    def delete(self, request, subject_id, competitor_id):
        try:
            remove_competitor(
                user=request.user,
                subject_id=subject_id,
                competitor_id=competitor_id,
            )
        except CompetitorBusinessError as exc:
            return _competitor_error(exc, request)
        return _no_store(Response(status=HTTP_204_NO_CONTENT))


class SubjectCompetitorComparisonView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        return _no_store(
            Response(
                competitor_comparison_payload(
                    user=request.user,
                    subject_id=subject_id,
                )
            )
        )
