from datetime import timedelta

from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_rbac.models import CustomerAssignment
from apps.admin_rbac.permissions import HasSuperuserAdminSession
from apps.admin_rbac.scopes import scoped_customer_or_404
from apps.admin_rbac.sensitive_audit_models import SensitiveAuditLog
from apps.admin_rbac.sensitive_audit_serializers import SensitiveAuditLogListSerializer
from apps.plans.models import PlanLimitDefinition, Subscription
from apps.quotas.catalog import QUOTA_BY_KEY
from apps.quotas.models import QuotaLedgerEntry
from apps.quotas.selectors import CUSTOMER_VISIBLE_QUOTA_TYPES, scoped_accounts, scoped_ledger
from apps.quotas.serializers import QUOTA_DISPLAY_NAMES, UNIT_DISPLAY_NAMES

from .models import LoginEvent
from .phone_numbers import mask_phone


RECENT_LOGIN_LIMIT = 10
RECENT_LEDGER_LIMIT = 20
RECENT_AUDIT_LIMIT = 20
SUBSCRIPTION_HISTORY_LIMIT = 20
USAGE_WINDOW_DAYS = 30
LEGACY_INTERNAL_TEST_SOURCE = "internal_test"

MANUAL_ADJUSTMENT_ACTIONS = (
    QuotaLedgerEntry.Action.GRANT,
    QuotaLedgerEntry.Action.COMPENSATE,
    QuotaLedgerEntry.Action.REFUND,
    QuotaLedgerEntry.Action.MANUAL_DEDUCT,
)


def _amount(value) -> str:
    """Serialize 64-bit quota facts without losing precision in JavaScript."""

    return str(int(value or 0))


def _active_subscription(user, moment):
    return (
        Subscription.objects.filter(
            user=user,
            status=Subscription.Status.ACTIVE,
            starts_at__lte=moment,
            ends_at__gt=moment,
        )
        .exclude(source_type=LEGACY_INTERNAL_TEST_SOURCE)
        .select_related("plan", "plan_version")
        .first()
    )


def _subscription_payload(subscription):
    if subscription is None:
        return None
    return {
        "id": str(subscription.pk),
        "plan_id": str(subscription.plan_id),
        "plan_name": subscription.plan.name,
        "plan_code": subscription.plan.code,
        "plan_version_id": str(subscription.plan_version_id),
        "plan_version_no": subscription.plan_version_no,
        "status": subscription.status,
        "source_type": subscription.source_type,
        "is_trial": subscription.is_trial,
        "starts_at": subscription.starts_at,
        "ends_at": subscription.ends_at,
        "activated_at": subscription.activated_at,
        "version": subscription.version,
        "opening_note": subscription.opening_note,
    }


def _assignment_payload(user):
    assignment = (
        CustomerAssignment.objects.filter(customer=user)
        .select_related("owner_admin", "owner_admin__user", "owner_admin__role")
        .first()
    )
    if assignment is None:
        return None
    owner = assignment.owner_admin
    return {
        "assignment_id": str(assignment.pk),
        "version": assignment.version,
        "assigned_at": assignment.assigned_at,
        "owner_admin_id": str(owner.pk) if owner else None,
        "owner_user_id": str(owner.user_id) if owner else None,
        "owner_name": owner.user.nickname if owner else "",
        "owner_role": owner.role.name if owner and owner.role_id else "",
    }


def _login_payload(user):
    events = list(
        LoginEvent.objects.filter(user=user).order_by("-created_at", "-id")[:RECENT_LOGIN_LIMIT]
    )
    last_success = next((event for event in events if event.success), None)
    if last_success is None:
        last_success = (
            LoginEvent.objects.filter(user=user, success=True)
            .order_by("-created_at", "-id")
            .first()
        )
    return {
        "last_success_at": last_success.created_at if last_success else None,
        "last_success_ip": (
            str(last_success.ip_address) if last_success and last_success.ip_address else None
        ),
        "last_success_user_agent": last_success.user_agent if last_success else "",
        "recent": [
            {
                "id": str(event.pk),
                "login_method": event.login_method,
                "success": event.success,
                "failure_reason": event.failure_reason,
                "ip_address": str(event.ip_address) if event.ip_address else None,
                "user_agent": event.user_agent,
                "request_id": str(event.request_id),
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


def _current_quota_rows(request, user, subscription, moment):
    if subscription is None:
        return []

    accounts = list(
        scoped_accounts(request.user, request.admin_context)
        .filter(
            user=user,
            subscription=subscription,
            subject__isnull=True,
            quota_type__in=CUSTOMER_VISIBLE_QUOTA_TYPES,
        )
        .filter(
            Q(cycle_started_at__isnull=True, cycle_ends_at__isnull=True)
            | Q(cycle_started_at__lte=moment, cycle_ends_at__gt=moment)
        )
        .filter(Q(spendable_until__isnull=True) | Q(spendable_until__gt=moment))
        .order_by("quota_type", "batch_type", "created_at", "id")
    )
    account_ids = [account.pk for account in accounts]

    used_rows = (
        scoped_ledger(request.user, request.admin_context)
        .filter(account_id__in=account_ids, action=QuotaLedgerEntry.Action.CONSUME)
        .values("account_id")
        .annotate(amount=Sum("frozen_delta"))
    )
    used_by_account = {
        row["account_id"]: max(-int(row["amount"] or 0), 0) for row in used_rows
    }

    manual_rows = (
        scoped_ledger(request.user, request.admin_context)
        .filter(
            user=user,
            subscription=subscription,
            quota_type__in=CUSTOMER_VISIBLE_QUOTA_TYPES,
            action__in=MANUAL_ADJUSTMENT_ACTIONS,
        )
        .values("quota_type")
        .annotate(amount=Sum("available_delta"))
    )
    manual_by_type = {row["quota_type"]: int(row["amount"] or 0) for row in manual_rows}

    grouped = {}
    for account in accounts:
        definition = QUOTA_BY_KEY.get(account.quota_type)
        if definition is None:
            continue
        row = grouped.setdefault(
            account.quota_type,
            {
                "quota_type": account.quota_type,
                "display_name": QUOTA_DISPLAY_NAMES.get(account.quota_type, account.quota_type),
                "unit": account.unit,
                "unit_display_name": UNIT_DISPLAY_NAMES.get(account.unit, "份"),
                "entitlement_amount": 0,
                "available": 0,
                "frozen": 0,
                "used_amount": 0,
                "accounts": [],
            },
        )
        used = used_by_account.get(account.pk, 0)
        row["entitlement_amount"] += int(account.entitlement_amount)
        row["available"] += int(account.available)
        row["frozen"] += int(account.frozen)
        row["used_amount"] += used
        row["accounts"].append(
            {
                "id": str(account.pk),
                "batch_type": account.batch_type,
                "scope": account.scope,
                "entitlement_amount": _amount(account.entitlement_amount),
                "available": _amount(account.available),
                "frozen": _amount(account.frozen),
                "used_amount": _amount(used),
                "version": account.version,
                "cycle_started_at": account.cycle_started_at,
                "cycle_ends_at": account.cycle_ends_at,
                "spendable_until": account.spendable_until,
                "adjustable": definition.accounting_mode == "consumable",
            }
        )

    rows = []
    for quota_type in CUSTOMER_VISIBLE_QUOTA_TYPES:
        row = grouped.get(quota_type)
        if row is None:
            continue
        total_amount = row["available"] + row["frozen"] + row["used_amount"]
        manual_adjustment = manual_by_type.get(quota_type, 0)
        rows.append(
            {
                "quota_type": row["quota_type"],
                "display_name": row["display_name"],
                "unit": row["unit"],
                "unit_display_name": row["unit_display_name"],
                "entitlement_amount": _amount(row["entitlement_amount"]),
                "manual_adjustment_amount": _amount(manual_adjustment),
                "total_amount": _amount(total_amount),
                "used_amount": _amount(row["used_amount"]),
                "frozen": _amount(row["frozen"]),
                "available": _amount(row["available"]),
                "accounts": row["accounts"],
            }
        )
    return rows


def _plan_limit_payload(subscription):
    if subscription is None or not isinstance(subscription.entitlement_snapshot, dict):
        return {"limits": [], "model_permissions": []}
    snapshot = subscription.entitlement_snapshot
    raw_limits = snapshot.get("limits")
    if not isinstance(raw_limits, dict):
        raw_limits = {}
    definitions = {
        item.key: item
        for item in PlanLimitDefinition.objects.filter(status=PlanLimitDefinition.Status.ACTIVE)
    }
    limits = []
    for key, value in raw_limits.items():
        definition = definitions.get(key)
        if definition is None:
            continue
        limits.append(
            {
                "key": key,
                "name": definition.name,
                "category": definition.category,
                "value_type": definition.value_type,
                "unit": definition.unit,
                "quota_type": definition.quota_type,
                "description": definition.description,
                "value": value,
            }
        )
    limits.sort(key=lambda item: (definitions[item["key"]].sort_order, item["key"]))
    model_permissions = snapshot.get("model_permissions")
    if not isinstance(model_permissions, list):
        model_permissions = []
    return {"limits": limits, "model_permissions": model_permissions}


def _usage_payload(request, user, moment):
    since = moment - timedelta(days=USAGE_WINDOW_DAYS)
    rows = (
        scoped_ledger(request.user, request.admin_context)
        .filter(
            user=user,
            quota_type__in=CUSTOMER_VISIBLE_QUOTA_TYPES,
            action=QuotaLedgerEntry.Action.CONSUME,
            created_at__gte=since,
        )
        .values("quota_type")
        .annotate(amount=Sum("frozen_delta"))
    )
    by_type = {row["quota_type"]: max(-int(row["amount"] or 0), 0) for row in rows}
    return {
        "window_days": USAGE_WINDOW_DAYS,
        "items": [
            {
                "quota_type": quota_type,
                "display_name": QUOTA_DISPLAY_NAMES.get(quota_type, quota_type),
                "amount": _amount(by_type.get(quota_type, 0)),
                "unit_display_name": UNIT_DISPLAY_NAMES.get(QUOTA_BY_KEY[quota_type].unit, "份"),
            }
            for quota_type in CUSTOMER_VISIBLE_QUOTA_TYPES
            if by_type.get(quota_type, 0) > 0
        ],
    }


def _recent_ledger_payload(request, user):
    entries = list(
        scoped_ledger(request.user, request.admin_context)
        .filter(user=user, quota_type__in=CUSTOMER_VISIBLE_QUOTA_TYPES)
        .select_related("actor")
        .order_by("-created_at", "-id")[:RECENT_LEDGER_LIMIT]
    )
    return [
        {
            "id": str(entry.pk),
            "account_id": str(entry.account_id),
            "quota_type": entry.quota_type,
            "display_name": QUOTA_DISPLAY_NAMES.get(entry.quota_type, entry.quota_type),
            "action": entry.action,
            "available_before": _amount(entry.available_before),
            "available_delta": _amount(entry.available_delta),
            "available_after": _amount(entry.available_after),
            "frozen_before": _amount(entry.frozen_before),
            "frozen_delta": _amount(entry.frozen_delta),
            "frozen_after": _amount(entry.frozen_after),
            "safe_reason": entry.safe_reason,
            "actor_id": str(entry.actor_id) if entry.actor_id else None,
            "actor_name": entry.actor.nickname if entry.actor_id and entry.actor else "系统",
            "request_id": str(entry.request_id),
            "created_at": entry.created_at,
        }
        for entry in entries
    ]


def _recent_audit_payload(user):
    logs = SensitiveAuditLog.objects.filter(target_user_id_snapshot=user.pk).order_by(
        "-created_at", "-id"
    )[:RECENT_AUDIT_LIMIT]
    return SensitiveAuditLogListSerializer(logs, many=True).data


def _subscription_history_payload(user):
    subscriptions = (
        Subscription.objects.filter(user=user)
        .exclude(source_type=LEGACY_INTERNAL_TEST_SOURCE)
        .select_related("plan", "plan_version")
        .order_by("-created_at", "-id")[:SUBSCRIPTION_HISTORY_LIMIT]
    )
    return [_subscription_payload(subscription) for subscription in subscriptions]


class AdminUserControlCenterView(APIView):
    """Super-admin read model for one user's real commercial and security state."""

    permission_classes = [HasSuperuserAdminSession]

    def get(self, request, user_id):
        user = scoped_customer_or_404(request.user, request.admin_context, user_id)
        moment = timezone.now()
        subscription = _active_subscription(user, moment)
        plan_payload = _plan_limit_payload(subscription)
        tenant = user.tenant
        return Response(
            {
                "user": {
                    "id": str(user.pk),
                    "nickname": user.nickname,
                    "phone_masked": mask_phone(user.phone),
                    "account_status": user.account_status,
                    "status_version": user.status_version,
                    "created_at": user.created_at,
                    "updated_at": user.updated_at,
                    "tenant": (
                        {
                            "id": str(tenant.pk),
                            "key": tenant.key,
                            "display_name": tenant.display_name,
                            "brand_name": tenant.brand_name,
                            "status": tenant.status,
                        }
                        if tenant
                        else None
                    ),
                    "assignment": _assignment_payload(user),
                    "login": _login_payload(user),
                },
                "subscription": _subscription_payload(subscription),
                "subscription_history": _subscription_history_payload(user),
                "quotas": _current_quota_rows(request, user, subscription, moment),
                "plan_limits": plan_payload["limits"],
                "model_permissions": plan_payload["model_permissions"],
                "usage": _usage_payload(request, user, moment),
                "recent_ledger": _recent_ledger_payload(request, user),
                "recent_audit": _recent_audit_payload(user),
            }
        )
