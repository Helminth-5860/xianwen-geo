from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_202_ACCEPTED, HTTP_204_NO_CONTENT
from rest_framework.views import APIView

from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .authorization import begin_browser_authorization, sync_authorization_session
from .models import PlatformAccount, PlatformAuthorizationSession, Publication, PublishingPreference
from .pause_control import (
    pause_platform_publications,
    pause_subject_publications,
    resume_platform_publications,
    resume_subject_publications,
)
from .review import approve_publication, is_waiting_review
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
    create_publication,
    disconnect_platform_account,
    ensure_platform_auto_publish_ready,
    preference_payload,
    publication_payload,
    publishing_state,
    subject_for_user,
    update_preference,
)
from .tasks import adopt_ready_articles_task, prepare_publication_task


def _sync_custom_platform(preference: PublishingPreference | None, platform_key: str, enabled: bool) -> None:
    if preference is None or preference.distribution_strategy != PublishingPreference.DistributionStrategy.CUSTOM:
        return
    keys = list(dict.fromkeys(preference.custom_platform_keys or []))
    if enabled and platform_key not in keys:
        keys.append(platform_key)
    if not enabled:
        keys = [item for item in keys if item != platform_key]
    if keys == list(preference.custom_platform_keys or []):
        return
    preference.custom_platform_keys = keys
    preference.version += 1
    preference.save(update_fields=("custom_platform_keys", "version", "updated_at"))


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
        if preference.distribution_strategy == PublishingPreference.DistributionStrategy.CUSTOM and not preference.custom_platform_keys:
            enabled_keys = list(
                PlatformAccount.objects.filter(
                    user=request.user,
                    subject_id=subject_id,
                    status=PlatformAccount.Status.CONNECTED,
                    enabled_for_auto=True,
                ).values_list("platform_key", flat=True)
            )
            if enabled_keys:
                preference.custom_platform_keys = enabled_keys
                preference.version += 1
                preference.save(update_fields=("custom_platform_keys", "version", "updated_at"))

        if preference.is_enabled:
            resume_subject_publications(user_id=request.user.pk, subject_id=subject_id)
            if preference.mode in {
                PublishingPreference.Mode.MANAGED,
                PublishingPreference.Mode.REVIEW,
            }:
                adopt_ready_articles_task.delay(str(request.user.pk), str(subject_id))
        else:
            pause_subject_publications(user_id=request.user.pk, subject_id=subject_id)
        return Response({"preference": preference_payload(preference)})


class SubjectPublishingAuthorizationStartView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def post(self, request, subject_id):
        serializer = AuthorizationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session = begin_browser_authorization(
                user=request.user,
                subject_id=subject_id,
                platform_key=serializer.validated_data["platform_key"],
            )
        except PublishingInputError as exc:
            raise ValidationError({"authorization": [str(exc)]}) from exc
        return Response(
            {"authorization": auth_session_payload(session)},
            status=HTTP_202_ACCEPTED,
        )


class PublishingAuthorizationSessionView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, session_id):
        session = get_object_or_404(
            PlatformAuthorizationSession.objects.select_related("account"),
            id=session_id,
            user=request.user,
        )
        session = sync_authorization_session(session)
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
        enabled = serializer.validated_data["enabled_for_auto"]
        if enabled:
            try:
                ensure_platform_auto_publish_ready(
                    user=request.user,
                    platform_key=platform_key,
                )
            except PublishingInputError as exc:
                raise ValidationError({"publishing": [str(exc)]}) from exc
        account.enabled_for_auto = enabled
        account.save(update_fields=("enabled_for_auto", "updated_at"))
        preference = PublishingPreference.objects.filter(user=request.user, subject=subject).first()
        _sync_custom_platform(preference, platform_key, enabled)

        if enabled:
            resume_platform_publications(
                user_id=request.user.pk,
                subject_id=subject_id,
                platform_key=platform_key,
                automation_enabled=bool(preference and preference.is_enabled),
            )
        else:
            pause_platform_publications(
                user_id=request.user.pk,
                subject_id=subject_id,
                platform_key=platform_key,
            )
        return Response({"account": account_payload(account)})

    def delete(self, request, subject_id, platform_key):
        subject = subject_for_user(user=request.user, subject_id=subject_id)
        pause_platform_publications(
            user_id=request.user.pk,
            subject_id=subject_id,
            platform_key=platform_key,
        )
        disconnect_platform_account(
            user=request.user,
            subject_id=subject_id,
            platform_key=platform_key,
        )
        preference = PublishingPreference.objects.filter(user=request.user, subject=subject).first()
        _sync_custom_platform(preference, platform_key, False)
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
        prepare_publication_task.delay(str(publication.id))
        return Response({"publication": publication_payload(publication)}, status=HTTP_201_CREATED)


class PublicationApproveView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def post(self, request, publication_id):
        publication = get_object_or_404(
            Publication.objects.prefetch_related("targets"),
            pk=publication_id,
            user=request.user,
        )
        if not is_waiting_review(publication):
            raise ValidationError({"publication": ["当前内容不需要确认，或已进入发布流程"]})
        publication = approve_publication(user=request.user, publication_id=publication_id)
        publication = Publication.objects.prefetch_related("targets").get(pk=publication.pk)
        return Response({"publication": publication_payload(publication)}, status=HTTP_200_OK)
