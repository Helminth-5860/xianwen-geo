from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_403_FORBIDDEN,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.subjects.permissions import IsAvailableAuthenticatedUser
from apps.subjects.subject_services import subject_for_user_or_404

from .exceptions import KeywordError
from .serializers import KeywordCommitRequestSerializer, KeywordDraftSaveRequestSerializer
from .services import (
    commit_keyword_version,
    keyword_set_for_subject,
    keyword_version_for_user_or_404,
    keyword_versions_for_user,
    keyword_write_state,
    save_keyword_draft,
)

ERROR_STATUS = {
    "KEYWORD_STATE_CONFLICT": HTTP_409_CONFLICT,
    "KEYWORD_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "KEYWORD_SUBJECT_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "KEYWORD_VALUES_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "KEYWORD_VERSION_NO_CHANGES": HTTP_409_CONFLICT,
    "PLAN_REQUIRED": HTTP_403_FORBIDDEN,
    "ACCOUNT_UNAVAILABLE": HTTP_403_FORBIDDEN,
}


def _error(exc: KeywordError, request):
    return error_response(
        ErrorCode(exc.code),
        status_code=ERROR_STATUS[exc.code],
        request=request,
    )


def _item_payload(item) -> dict:
    base_keyword_text = getattr(item, "base_keyword_text", None)
    if base_keyword_text is None and getattr(item, "base_keyword_id", None):
        base_keyword_text = item.base_keyword.text
    return {
        "id": str(item.pk),
        "text": item.text,
        "structure_type": item.structure_type,
        "is_regional": item.is_regional,
        "region_level": item.region_level or None,
        "region_text": item.region_text or None,
        "base_keyword_text": base_keyword_text,
        "business_category": item.business_category,
        "search_intent": item.search_intent,
        "relevance_score": item.relevance_score,
        "priority": item.priority,
        "ai_reason": item.ai_reason,
        "sort_order": item.sort_order,
    }


def _subject_version_payload(version) -> dict | None:
    if version is None:
        return None
    return {
        "id": str(version.pk),
        "version_no": version.version_no,
        "official_name": version.official_name,
    }


def _draft_payload(*, user, subject) -> dict:
    keyword_set = keyword_set_for_subject(user=user, subject=subject)
    state = keyword_write_state(user=user, subject=subject)
    current_keyword_version_no = None
    if keyword_set is not None and keyword_set.current_version is not None:
        current_keyword_version_no = keyword_set.current_version.version_no
    return {
        "version": keyword_set.version if keyword_set else 0,
        "subject_version": _subject_version_payload(subject.current_version),
        "draft_subject_version": _subject_version_payload(
            keyword_set.draft_subject_version if keyword_set else None
        ),
        "current_keyword_version_no": current_keyword_version_no,
        "can_write": state.can_write,
        "read_only_reason": state.reason or None,
        "items": (
            [_item_payload(item) for item in keyword_set.draft_items.order_by("sort_order", "id")]
            if keyword_set
            else []
        ),
    }


def _version_payload(version, *, detail: bool) -> dict:
    payload = {
        "id": str(version.pk),
        "version_no": version.version_no,
        "subject_version": _subject_version_payload(version.subject_version),
        "item_count": version.item_count,
        "created_at": version.created_at.isoformat(),
    }
    if detail:
        payload["items"] = [
            _item_payload(item) for item in version.keywords.order_by("sort_order", "id")
        ]
    return payload


class KeywordDraftView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        return Response(_draft_payload(user=request.user, subject=subject))

    @method_decorator(csrf_protect)
    def patch(self, request, subject_id):
        serializer = KeywordDraftSaveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            keyword_set, _ = save_keyword_draft(
                user_id=request.user.pk,
                subject_id=subject_id,
                expected_version=serializer.validated_data["expected_version"],
                expected_subject_version_id=serializer.validated_data[
                    "expected_subject_version_id"
                ],
                items=serializer.validated_data["items"],
            )
        except KeywordError as exc:
            return _error(exc, request)
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        keyword_set.refresh_from_db()
        return Response(_draft_payload(user=request.user, subject=subject))


class KeywordCurrentView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        keyword_set = keyword_set_for_subject(user=request.user, subject=subject)
        if keyword_set is None or keyword_set.current_version_id is None:
            return Response({"version": None})
        version = keyword_version_for_user_or_404(
            user=request.user,
            subject_id=subject_id,
            version_id=keyword_set.current_version_id,
        )
        return Response({"version": _version_payload(version, detail=True)})


class KeywordCommitView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = KeywordCommitRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            _, version = commit_keyword_version(
                user_id=request.user.pk,
                subject_id=subject_id,
                expected_version=serializer.validated_data["expected_version"],
                expected_subject_version_id=serializer.validated_data[
                    "expected_subject_version_id"
                ],
            )
        except KeywordError as exc:
            return _error(exc, request)
        version = keyword_version_for_user_or_404(
            user=request.user,
            subject_id=subject_id,
            version_id=version.pk,
        )
        return Response(
            {"version": _version_payload(version, detail=True)},
            status=HTTP_201_CREATED,
        )


class KeywordVersionListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        rows = keyword_versions_for_user(user=request.user, subject_id=subject_id)
        return Response({"versions": [_version_payload(row, detail=False) for row in rows]})


class KeywordVersionDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id, version_id):
        row = keyword_version_for_user_or_404(
            user=request.user,
            subject_id=subject_id,
            version_id=version_id,
        )
        return Response(_version_payload(row, detail=True))
