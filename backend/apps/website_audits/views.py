from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT
from rest_framework.views import APIView

from .models import WebsiteAudit
from .serializers import WebsiteAuditCreateSerializer, WebsiteAuditSerializer
from .services import WebsiteAuditBusy, WebsiteAuditNotFound, create_website_audit
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
        return Response(WebsiteAuditSerializer(audit).data, status=HTTP_201_CREATED)


class WebsiteAuditDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, audit_id):
        audit = (
            WebsiteAudit.objects.filter(pk=audit_id, user=request.user)
            .prefetch_related("pages")
            .first()
        )
        if audit is None:
            return Response({"detail": "检测记录不存在。"}, status=HTTP_404_NOT_FOUND)
        return Response(WebsiteAuditSerializer(audit).data)


class SubjectWebsiteAuditListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, subject_id):
        audits = WebsiteAudit.objects.filter(user=request.user, subject_id=subject_id).order_by(
            "-created_at"
        )[:20]
        return Response(WebsiteAuditSerializer(audits, many=True).data)
