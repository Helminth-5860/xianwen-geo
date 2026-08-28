from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_202_ACCEPTED, HTTP_204_NO_CONTENT
from rest_framework.views import APIView

from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .models import PlatformAccount, PlatformAuthorizationSession
from .serializers import (
    AuthorizationStartSerializer,
    PlatformToggleSerializer,
    PublicationCreateSerializer,
    PublishingPreferenceSerializer,
)
from .services import (
    PublishingInputError,
    account_payload,
    auth_session_payload,
    create_authorization_session,
    create_publication,
    disconnect_platform_account,
    preference_payload,
    publication_payload,
    publishing_state,
    subject_for_user,
    update_preference,
)


class SubjectPublishingStateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        return Response(publishing_state(user=request.user, subject_id=subject_id))


class SubjectPublishingPreferenceView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def patch(self, request, subject_id):
        serializer = PublishingPreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            preference = update_preference(
                user=request.user,
                subject_id=subject_id,
                values=dict(serializer.validated_data),
            )
        except PublishingInputError as exc:
            raise ValidationError({"publishing": [str(exc)]}) from exc
        return Response({"preference": preference_payload(preference)})


class SubjectPublishingAuthorizationStartView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def post(self, request, subject_id):
        serializer = AuthorizationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session, one_time_token = create_authorization_session(
                user=request.user,
                subject_id=subject_id,
                platform_key=serializer.validated_data["platform_key"],
            )
        except PublishingInputError as exc:
            raise ValidationError({"authorization": [str(exc)]}) from exc
        return Response(
            {"authorization": auth_session_payload(session, one_time_token=one_time_token)},
            status=HTTP_202_ACCEPTED,
        )


class PublishingAuthorizationSessionView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, session_id):
        session = get_object_or_404(
            PlatformAuthorizationSession,
            id=session_id,
            user=request.user,
        )
        return Response({"authorization": auth_session_payload(session)})


class SubjectPlatformAccountView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def patch(self, request, subject_id, platform_key):
        serializer = PlatformToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subject = subject_for_user(user=request.user, subject_id=subject_id)
        account = get_object_or_404(
            PlatformAccount,
            user=request.user,
            subject=subject,
            platform_key=platform_key,
        )
        account.enabled_for_auto = serializer.validated_data["enabled_for_auto"]
        account.save(update_fields=("enabled_for_auto", "updated_at"))
        return Response({"account": account_payload(account)})

    def delete(self, request, subject_id, platform_key):
        disconnect_platform_account(
            user=request.user,
            subject_id=subject_id,
            platform_key=platform_key,
        )
        return Response(status=HTTP_204_NO_CONTENT)


class SubjectPublicationCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def post(self, request, subject_id):
        serializer = PublicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            publication = create_publication(
                user=request.user,
                subject_id=subject_id,
                article_id=serializer.validated_data["article_id"],
                platform_keys=list(serializer.validated_data.get("platform_keys") or []),
                scheduled_at=serializer.validated_data.get("scheduled_at"),
            )
        except PublishingInputError as exc:
            raise ValidationError({"publication": [str(exc)]}) from exc
        publication = publication.__class__.objects.prefetch_related("targets").get(id=publication.id)
        return Response({"publication": publication_payload(publication)}, status=HTTP_201_CREATED)
