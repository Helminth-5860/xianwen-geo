from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import (
    NotificationSerializer,
    PaginationSerializer,
)
from .status_services import mark_notification_read


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
