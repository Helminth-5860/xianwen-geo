import re
from math import ceil

from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_202_ACCEPTED
from rest_framework.views import APIView

from apps.admin_rbac.permissions import HasAdminPermission
from apps.admin_rbac.risk_services import RiskError, perform_risk_action
from apps.admin_rbac.risk_views import risk_error_response
from apps.admin_rbac.security import (
    AdminReauthFailed,
    AdminReauthRateLimited,
    AdminSecurityUnavailable,
)
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .exceptions import QuotaError, QuotaIdempotencyConflict
from .idempotency import derive_idempotency_digests
from .models import QuotaLedgerEntry
from .selectors import (
    current_account_summaries,
    scoped_account_or_404,
    scoped_accounts,
    scoped_ledger,
    user_ledger,
)
from .serializers import (
    AdminQuotaAccountSerializer,
    AdminQuotaLedgerSerializer,
    QuotaAdjustmentRequestSerializer,
    UserQuotaLedgerSerializer,
    UserQuotaSummarySerializer,
    validate_quota_type,
)
from .services import _assert_idempotent_match

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[\x21-\x7e]{16,128}$")
QUOTA_ERROR_STATUS = {
    "QUOTA_STATE_CONFLICT": 409,
    "QUOTA_SNAPSHOT_INVALID": 409,
    "QUOTA_INSUFFICIENT": 409,
    "QUOTA_VERSION_CONFLICT": 409,
    "QUOTA_HOLD_STATE_CONFLICT": 409,
    "QUOTA_BUSINESS_ALREADY_HELD": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "SUBSCRIPTION_UNAVAILABLE": 409,
}


def _page(queryset, serializer, request):
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {"page": ["\u5206\u9875\u53c2\u6570\u4e0d\u6b63\u786e\u3002"]}
        ) from exc
    count = queryset.count()
    offset = (page - 1) * page_size
    return {
        "results": serializer(queryset[offset : offset + page_size], many=True).data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "count": count,
            "total_pages": ceil(count / page_size) if count else 0,
        },
    }


def quota_error_response(exc, request):
    code = ErrorCode(exc.code)
    return error_response(code, status_code=QUOTA_ERROR_STATUS[exc.code], request=request)


class CurrentQuotaAccountsView(APIView):
    def get(self, request):
        return Response(
            {
                "accounts": UserQuotaSummarySerializer(
                    current_account_summaries(request.user), many=True
                ).data
            }
        )


class UserQuotaLedgerView(APIView):
    def get(self, request):
        return Response(_page(user_ledger(request.user), UserQuotaLedgerSerializer, request))


class AdminQuotaAccountListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "quotas.list"

    def get(self, request):
        queryset = scoped_accounts(request.user, request.admin_context)
        quota_type = request.query_params.get("quota_type")
        if quota_type:
            queryset = queryset.filter(quota_type=validate_quota_type(quota_type))
        user_id = request.query_params.get("user_id")
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        keyword = request.query_params.get("keyword", "").strip()
        if keyword:
            queryset = queryset.filter(Q(user__nickname__icontains=keyword))
        return Response(_page(queryset, AdminQuotaAccountSerializer, request))


class AdminQuotaLedgerListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "quotas.ledger.view"

    def get(self, request):
        queryset = scoped_ledger(request.user, request.admin_context)
        account_id = request.query_params.get("account_id")
        if account_id:
            queryset = queryset.filter(account_id=account_id)
        quota_type = request.query_params.get("quota_type")
        if quota_type:
            queryset = queryset.filter(quota_type=validate_quota_type(quota_type))
        action = request.query_params.get("action")
        if action:
            if action not in QuotaLedgerEntry.Action.values:
                raise ValidationError(
                    {"action": ["\u989d\u5ea6\u6d41\u6c34\u52a8\u4f5c\u4e0d\u6b63\u786e\u3002"]}
                )
            queryset = queryset.filter(action=action)
        return Response(_page(queryset, AdminQuotaLedgerSerializer, request))


class AdminQuotaAdjustmentView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "quotas.adjust"

    @method_decorator(csrf_protect)
    def post(self, request, account_id, action):
        action_map = {
            "grant": ("quota.grant", QuotaLedgerEntry.Action.GRANT),
            "compensate": ("quota.compensate", QuotaLedgerEntry.Action.COMPENSATE),
            "manual-deduct": ("quota.manual_deduct", QuotaLedgerEntry.Action.MANUAL_DEDUCT),
        }
        if action not in action_map:
            raise ValidationError(
                {"action": ["\u989d\u5ea6\u8c03\u6574\u52a8\u4f5c\u4e0d\u6b63\u786e\u3002"]}
            )
        serializer = QuotaAdjustmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop("expected_version")
        confirmed = payload.pop("confirmed", False)
        current_password = payload.pop("current_password", "")
        raw_key = request.headers.get("Idempotency-Key", "")
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(raw_key):
            return error_response(
                ErrorCode.IDEMPOTENCY_KEY_REQUIRED, status_code=422, request=request
            )
        account = scoped_account_or_404(request.user, request.admin_context, account_id)
        action_key, ledger_action = action_map[action]
        digests = derive_idempotency_digests(
            raw_key,
            operation=ledger_action,
            user_id=account.user_id,
            account_id=account.pk,
            business_type="quota_adjustment",
            business_id=account.pk,
            request_payload=payload,
        )
        existing = QuotaLedgerEntry.objects.filter(
            idempotency_key_digest=digests.key_digest
        ).first()
        if existing is not None:
            try:
                _assert_idempotent_match(
                    existing, account=account, action=ledger_action, digests=digests
                )
            except QuotaIdempotencyConflict as exc:
                return quota_error_response(exc, request)
            return Response(
                {
                    "account_id": str(account.pk),
                    "ledger_entry_id": str(existing.pk),
                    "available": existing.available_after,
                    "frozen": existing.frozen_after,
                    "version": existing.account_version_after,
                    "replayed": True,
                }
            )
        risk_payload = {
            **payload,
            "idempotency_key_version": digests.key_version,
            "idempotency_key_digest": digests.key_digest,
            "idempotency_scope_digest": digests.scope_digest,
            "request_digest": digests.request_digest,
        }
        try:
            result = perform_risk_action(
                request=request,
                action_key=action_key,
                target_id=account_id,
                target_version=expected_version,
                raw_payload=risk_payload,
                confirmed=confirmed,
                current_password=current_password,
            )
        except QuotaError as exc:
            return quota_error_response(exc, request)
        except (
            RiskError,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
        ) as exc:
            return risk_error_response(exc, request)
        return Response(
            result.data,
            status=HTTP_202_ACCEPTED if result.approval_required else HTTP_200_OK,
        )
