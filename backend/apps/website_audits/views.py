from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT
from rest_framework.views import APIView

from apps.subjects.subject_services import subject_for_user_or_404, workspace_subject_filter

from .models import WebsiteAudit
from .serializers import (
    WebsiteAuditCreateSerializer,
    WebsiteAuditDetailSerializer,
    WebsiteAuditSummarySerializer,
)
from .services import (
    WebsiteAuditBusy,
    WebsiteAuditNotFound,
    create_website_audit,
    recover_stale_website_audits,
)
from .tasks import execute_website_audit_task


class WebsiteAuditCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, subject_id):
        serializer = WebsiteAuditCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                audit = create_website_audit(
                    user=request.user,
                    subject_id=subject_id,
                    url=serializer.validated_data["url"],
                    request_id=getattr(request, "request_id", None),
                )
                transaction.on_commit(
                    lambda: execute_website_audit_task.apply_async(
                        args=[str(audit.id)],
                        queue="web_fetch",
                    )
                )
        except WebsiteAuditNotFound:
            return Response({"detail": "主体不存在。"}, status=HTTP_404_NOT_FOUND)
        except WebsiteAuditBusy:
            return Response(
                {"detail": "当前主体已有官网检测正在进行。"},
                status=HTTP_409_CONFLICT,
            )
        return Response(WebsiteAuditSummarySerializer(audit).data, status=HTTP_201_CREATED)


class WebsiteAuditDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, audit_id):
        audit = (
            WebsiteAudit.objects.filter(
                workspace_subject_filter(request.user, prefix="subject__"),
                pk=audit_id,
            )
            .prefetch_related("pages", "browser_snapshots", "findings")
            .first()
        )
        if audit is None:
            return Response({"detail": "检测记录不存在。"}, status=HTTP_404_NOT_FOUND)
        recover_stale_website_audits(subject_id=audit.subject_id)
        audit.refresh_from_db()
        return Response(WebsiteAuditDetailSerializer(audit).data)


class SubjectWebsiteAuditListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        recover_stale_website_audits(subject_id=subject.pk)
        audits = WebsiteAudit.objects.filter(subject=subject).order_by("-created_at")[:20]
        return Response(WebsiteAuditSummarySerializer(audits, many=True).data)
