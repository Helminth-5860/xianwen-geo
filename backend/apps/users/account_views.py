from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_409_CONFLICT
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .models import Notification
from .serializers import (
    ApprovalResubmitSerializer,
    CurrentUserSerializer,
    NotificationSerializer,
    PaginationSerializer,
)
from .status_services import ApprovalStateConflict, mark_notification_read, resubmit_approval


@method_decorator(csrf_protect, name="dispatch")
class ApprovalResubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ApprovalResubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = resubmit_approval(
                user_id=request.user.pk,
                nickname=serializer.validated_data.get("nickname"),
                request_id=request.request_id,
            )
        except ApprovalStateConflict:
            return error_response(
                ErrorCode.APPROVAL_STATE_CONFLICT,
                status_code=HTTP_409_CONFLICT,
                request=request,
            )
        return Response(CurrentUserSerializer(result.user).data)


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query_serializer = PaginationSerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        query = query_serializer.validated_data
        notifications = Notification.objects.filter(recipient=request.user).order_by(
            "-created_at", "-id"
        )
        count = notifications.count()
        offset = (query["page"] - 1) * query["page_size"]
        items = notifications[offset : offset + query["page_size"]]
        return Response(
            {
                "results": NotificationSerializer(items, many=True).data,
                "pagination": {
                    "page": query["page"],
                    "page_size": query["page_size"],
                    "count": count,
                    "total_pages": (count + query["page_size"] - 1) // query["page_size"],
                },
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        notification = mark_notification_read(
            user_id=request.user.pk,
            notification_id=notification_id,
        )
        return Response(NotificationSerializer(notification).data)
