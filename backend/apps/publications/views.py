from __future__ import annotations

from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_202_ACCEPTED
from rest_framework.views import APIView

from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .models import PublicationJob
from .serializers import (
    AccountParticipationSerializer,
    AuthorizationStartSerializer,
    AutoPublishPolicySerializer,
    PublicationJobCreateSerializer,
)
from .services import (
    PublicationInputError,
    account_payload,
    approve_publication_job,
    authorization_payload,
    authorization_session_for_user,
    begin_authorization,
    create_publication_job,
    dashboard_state,
    job_payload,
    platform_catalog,
    policy_payload,
    publication_job_for_user,
    revoke_account,
    set_account_participation,
    update_policy,
)


_SAFE_MESSAGES = {
    "PUBLICATION_PLATFORM_UNAVAILABLE": "该平台暂不可用",
    "PUBLICATION_PLATFORM_PAUSED": "该平台当前暂停自动发布",
    "PUBLICATION_PLATFORM_STILL_TESTING": "该平台正在适配验证中，暂未开放授权",
    "PUBLICATION_CREDENTIALS_REQUIRED": "请填写平台要求的授权信息",
    "PUBLICATION_POLICY_VERSION_CONFLICT": "设置已更新，请刷新后重试",
    "PUBLICATION_ACCOUNT_VERSION_CONFLICT": "账号状态已更新，请刷新后重试",
    "PUBLICATION_ACCOUNT_NOT_AUTHORIZED": "请先完成平台授权",
    "PUBLICATION_PLATFORM_SELECTION_INVALID": "所选发布平台中存在不可用平台",
    "PUBLICATION_ARTICLE_NOT_READY": "该文章尚未达到可发布状态",
    "PUBLICATION_NO_AUTHORIZED_PLATFORM": "请至少授权一个可用的发布平台",
    "PUBLICATION_IDEMPOTENCY_KEY_REQUIRED": "请求信息不完整，请重新尝试",
}


def _raise_publication_error(exc: PublicationInputError):
    raise ValidationError(
        {"auto_publish": [_SAFE_MESSAGES.get(exc.code, "当前操作暂时无法完成，请稍后再试")]}
    ) from exc


class SubjectAutoPublishView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        return Response(dashboard_state(user=request.user, subject_id=subject_id))

    def patch(self, request, subject_id):
        serializer = AutoPublishPolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        expected_version = data.pop("expected_version")
        try:
            policy = update_policy(
                user=request.user,
                subject_id=subject_id,
                data=data,
                expected_version=expected_version,
            )
        except PublicationInputError as exc:
            _raise_publication_error(exc)
        return Response({"policy": policy_payload(policy)})


class SubjectPlatformCatalogView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        return Response({"items": platform_catalog(user=request.user, subject_id=subject_id)})


class SubjectAuthorizationStartView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def post(self, request, subject_id):
        serializer = AuthorizationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session = begin_authorization(
                user=request.user,
                subject_id=subject_id,
                platform_key=serializer.validated_data["platform_key"],
                credentials=serializer.validated_data.get("credentials") or {},
            )
        except PublicationInputError as exc:
            _raise_publication_error(exc)
        session = authorization_session_for_user(user=request.user, session_id=session.pk)
        return Response(
            {"authorization": authorization_payload(session)}, status=HTTP_202_ACCEPTED
        )


class AuthorizationSessionView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, session_id):
        session = authorization_session_for_user(user=request.user, session_id=session_id)
        return Response({"authorization": authorization_payload(session)})


class SubjectPlatformAccountView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def delete(self, request, subject_id, platform_key):
        try:
            account = revoke_account(
                user=request.user, subject_id=subject_id, platform_key=platform_key
            )
        except PublicationInputError as exc:
            _raise_publication_error(exc)
        return Response({"account": account_payload(account)}, status=HTTP_200_OK)

    def patch(self, request, subject_id, platform_key):
        serializer = AccountParticipationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            account = set_account_participation(
                user=request.user,
                subject_id=subject_id,
                platform_key=platform_key,
                enabled=serializer.validated_data["enabled"],
                expected_version=serializer.validated_data["expected_version"],
            )
        except PublicationInputError as exc:
            _raise_publication_error(exc)
        return Response({"account": account_payload(account)})


class SubjectPublicationJobsView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        rows = (
            PublicationJob.objects.select_related("article", "subject", "policy")
            .filter(user=request.user, subject_id=subject_id)
            .order_by("-created_at")[:50]
        )
        return Response({"items": [job_payload(row) for row in rows]})

    def post(self, request, subject_id):
        serializer = PublicationJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            job, created = create_publication_job(
                user=request.user,
                article_id=serializer.validated_data["article_id"],
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
        except PublicationInputError as exc:
            _raise_publication_error(exc)
        if str(job.subject_id) != str(subject_id):
            raise ValidationError({"auto_publish": ["所选文章不属于当前主体"]})
        job = publication_job_for_user(user=request.user, job_id=job.pk)
        return Response(
            {"job": job_payload(job)},
            status=HTTP_201_CREATED if created else HTTP_200_OK,
        )


class PublicationJobView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, job_id):
        job = publication_job_for_user(user=request.user, job_id=job_id)
        return Response({"job": job_payload(job)})


class PublicationJobApproveView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def post(self, request, job_id):
        job = approve_publication_job(user=request.user, job_id=job_id)
        job = publication_job_for_user(user=request.user, job_id=job.pk)
        return Response({"job": job_payload(job)}, status=HTTP_202_ACCEPTED)
