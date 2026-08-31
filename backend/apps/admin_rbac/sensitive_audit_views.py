from datetime import datetime, time, timedelta
from ipaddress import ip_address
from math import ceil
from uuid import UUID

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import HasAdminPermission
from .sensitive_audit_models import SensitiveAuditLog
from .sensitive_audit_serializers import (
    SensitiveAuditLogDetailSerializer,
    SensitiveAuditLogListSerializer,
)

MAX_QUERY_DAYS = 365
DEFAULT_QUERY_DAYS = 7


def _require_superuser(request) -> None:
    if not request.user.is_superuser:
        raise PermissionDenied("只有超级管理员可以查看全平台敏感审计日志。")


def _page(queryset, request):
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": ["分页参数不正确。"]}) from exc
    count = queryset.count()
    offset = (page - 1) * page_size
    return {
        "results": SensitiveAuditLogListSerializer(
            queryset[offset : offset + page_size], many=True
        ).data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "count": count,
            "total_pages": ceil(count / page_size) if count else 0,
        },
    }


def _aware_day_start(value: str, field_name: str):
    parsed = parse_date(value)
    if parsed is None:
        raise ValidationError({field_name: ["日期格式必须为 YYYY-MM-DD。"]})
    return timezone.make_aware(datetime.combine(parsed, time.min), timezone.get_current_timezone())


def _apply_time_filter(queryset, request):
    date_from = request.query_params.get("date_from", "").strip()
    date_to = request.query_params.get("date_to", "").strip()
    if date_from or date_to:
        if not date_from or not date_to:
            raise ValidationError({"date_from": ["自定义时间必须同时提供开始和结束日期。"]})
        start = _aware_day_start(date_from, "date_from")
        end = _aware_day_start(date_to, "date_to") + timedelta(days=1)
        if start >= end:
            raise ValidationError({"date_to": ["结束日期不能早于开始日期。"]})
        if end - start > timedelta(days=MAX_QUERY_DAYS):
            raise ValidationError({"date_to": ["单次最多查询 365 天。"]})
        if timezone.now() - start > timedelta(days=MAX_QUERY_DAYS + 1):
            raise ValidationError({"date_from": ["在线审计日志最多查询最近 365 天。"]})
        return queryset.filter(created_at__gte=start, created_at__lt=end)

    try:
        days = int(request.query_params.get("days", DEFAULT_QUERY_DAYS))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"days": ["查询天数不正确。"]}) from exc
    if not 1 <= days <= MAX_QUERY_DAYS:
        raise ValidationError({"days": ["查询天数必须在 1 到 365 之间。"]})
    return queryset.filter(created_at__gte=timezone.now() - timedelta(days=days))


def _apply_keyword_filter(queryset, keyword: str):
    keyword = keyword.strip()[:120]
    if not keyword:
        return queryset

    conditions = (
        Q(actor_name_snapshot__icontains=keyword)
        | Q(actor_role_snapshot__icontains=keyword)
        | Q(actor_tenant_name_snapshot__icontains=keyword)
        | Q(target_name_snapshot__icontains=keyword)
        | Q(target_owner_name_snapshot__icontains=keyword)
        | Q(target_tenant_name_snapshot__icontains=keyword)
    )
    try:
        parsed_ip = str(ip_address(keyword))
    except ValueError:
        parsed_ip = ""
    if parsed_ip:
        conditions |= Q(operation_ip=parsed_ip) | Q(login_ip_snapshot=parsed_ip)

    try:
        parsed_uuid = UUID(keyword)
    except ValueError:
        parsed_uuid = None
    if parsed_uuid:
        conditions |= (
            Q(pk=parsed_uuid)
            | Q(actor_user_id_snapshot=parsed_uuid)
            | Q(target_user_id_snapshot=parsed_uuid)
            | Q(target_owner_user_id_snapshot=parsed_uuid)
            | Q(ledger_entry_id=parsed_uuid)
            | Q(request_id=parsed_uuid)
        )
    return queryset.filter(conditions)


class SensitiveAuditLogListView(APIView):
    required_permission = "audit.list"
    permission_classes = [HasAdminPermission]

    def get(self, request):
        _require_superuser(request)
        queryset = SensitiveAuditLog.objects.all()
        queryset = _apply_time_filter(queryset, request)
        queryset = _apply_keyword_filter(queryset, request.query_params.get("q", ""))

        action_key = request.query_params.get("action_key", "").strip()
        if action_key:
            queryset = queryset.filter(action_key=action_key[:100])
        outcome = request.query_params.get("outcome", "").strip()
        if outcome:
            if outcome not in SensitiveAuditLog.Outcome.values:
                raise ValidationError({"outcome": ["审计结果不正确。"]})
            queryset = queryset.filter(outcome=outcome)
        return Response(_page(queryset, request))


class SensitiveAuditLogDetailView(APIView):
    required_permission = "audit.view"
    permission_classes = [HasAdminPermission]

    def get(self, request, log_id):
        _require_superuser(request)
        try:
            log = SensitiveAuditLog.objects.get(pk=log_id)
        except SensitiveAuditLog.DoesNotExist as exc:
            raise NotFound from exc
        return Response(SensitiveAuditLogDetailSerializer(log).data)
