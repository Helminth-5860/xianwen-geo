from typing import Any

from django.db.models import (
    BigIntegerField,
    CharField,
    DateTimeField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.admin_rbac.scopes import scoped_customers

from .catalog import QUOTA_BY_KEY
from .models import QuotaAccount, QuotaLedgerEntry

CUSTOMER_VISIBLE_QUOTA_TYPES = tuple(
    key for key, definition in QUOTA_BY_KEY.items() if definition.customer_visible
)
MANUAL_ADJUSTMENT_ACTIONS = (
    QuotaLedgerEntry.Action.GRANT,
    QuotaLedgerEntry.Action.COMPENSATE,
    QuotaLedgerEntry.Action.REFUND,
    QuotaLedgerEntry.Action.MANUAL_DEDUCT,
)


def _with_account_activity(queryset):
    consumed = (
        QuotaLedgerEntry.objects.filter(
            account_id=OuterRef("pk"),
            action=QuotaLedgerEntry.Action.CONSUME,
        )
        .values("account_id")
        .annotate(amount=Sum("frozen_delta"))
        .values("amount")[:1]
    )
    latest_adjustment = QuotaLedgerEntry.objects.filter(
        account_id=OuterRef("pk"), action__in=MANUAL_ADJUSTMENT_ACTIONS
    ).order_by("-created_at", "-id")
    return queryset.annotate(
        consumed_frozen_delta=Coalesce(
            Subquery(consumed, output_field=BigIntegerField()),
            Value(0),
            output_field=BigIntegerField(),
        ),
        last_adjustment_action=Subquery(
            latest_adjustment.values("action")[:1], output_field=CharField()
        ),
        last_adjustment_reason=Subquery(
            latest_adjustment.values("safe_reason")[:1], output_field=CharField()
        ),
        last_adjustment_at=Subquery(
            latest_adjustment.values("created_at")[:1], output_field=DateTimeField()
        ),
        last_adjustment_actor_nickname=Subquery(
            latest_adjustment.values("actor__nickname")[:1], output_field=CharField()
        ),
    )


def current_accounts(user, *, now=None):
    from apps.plans.subscription_services import current_subscription

    moment = now or timezone.now()
    subscription = current_subscription(user, now=moment)
    if subscription is None:
        return QuotaAccount.objects.none()
    return _with_account_activity(
        QuotaAccount.objects.filter(
            subscription=subscription,
            subject__isnull=True,
            quota_type__in=CUSTOMER_VISIBLE_QUOTA_TYPES,
        ).filter(
            Q(cycle_started_at__isnull=True, cycle_ends_at__isnull=True)
            | Q(cycle_started_at__lte=moment, cycle_ends_at__gt=moment)
        )
    )


def current_account_summaries(user, *, now=None):
    grouped: dict[str, dict[str, Any]] = {}
    for account in current_accounts(user, now=now).order_by("quota_type", "id"):
        item = grouped.setdefault(
            account.quota_type,
            {
                "quota_type": account.quota_type,
                "unit": account.unit,
                "scope": account.scope,
                "entitlement_amount": 0,
                "available": 0,
                "frozen": 0,
                "used_amount": 0,
            },
        )
        item["entitlement_amount"] += account.entitlement_amount
        item["available"] += account.available
        item["frozen"] += account.frozen
        item["used_amount"] += max(-account.consumed_frozen_delta, 0)
    for item in grouped.values():
        item["total_amount"] = item["available"] + item["frozen"] + item["used_amount"]
        item["remaining_amount"] = item["available"]
    return list(grouped.values())


def user_ledger(user):
    return (
        QuotaLedgerEntry.objects.filter(
            user=user,
            quota_type__in=CUSTOMER_VISIBLE_QUOTA_TYPES,
        )
        .exclude(
            action__in=(
                QuotaLedgerEntry.Action.PLAN_CHANGE_FORFEIT,
                QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_OUT,
                QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_IN,
            )
        )
        .select_related("account")
        .order_by("-created_at", "-id")
    )


def scoped_accounts(user, context):
    customer_ids = scoped_customers(user, context).values("pk")
    return _with_account_activity(
        QuotaAccount.objects.filter(user_id__in=customer_ids).select_related(
            "user", "subscription", "subscription__plan", "subscription__plan_version"
        )
    )


def scoped_account_or_404(user, context, account_id):
    try:
        return scoped_accounts(user, context).get(pk=account_id)
    except QuotaAccount.DoesNotExist as exc:
        raise NotFound from exc


def scoped_ledger(user, context):
    customer_ids = scoped_customers(user, context).values("pk")
    return QuotaLedgerEntry.objects.filter(user_id__in=customer_ids).select_related(
        "account", "user", "subscription", "actor"
    )
