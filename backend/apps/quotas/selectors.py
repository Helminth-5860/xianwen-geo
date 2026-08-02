from typing import Any

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.admin_rbac.scopes import scoped_customers

from .models import QuotaAccount, QuotaLedgerEntry


def current_accounts(user, *, now=None):
    from apps.plans.subscription_services import current_subscription

    moment = now or timezone.now()
    subscription = current_subscription(user, now=moment)
    if subscription is None:
        return QuotaAccount.objects.none()
    return QuotaAccount.objects.filter(subscription=subscription).filter(
        Q(cycle_started_at__isnull=True, cycle_ends_at__isnull=True)
        | Q(cycle_started_at__lte=moment, cycle_ends_at__gt=moment)
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
            },
        )
        item["entitlement_amount"] += account.entitlement_amount
        item["available"] += account.available
        item["frozen"] += account.frozen
    return list(grouped.values())


def user_ledger(user):
    return (
        QuotaLedgerEntry.objects.filter(user=user)
        .exclude(
            action__in=(
                QuotaLedgerEntry.Action.PLAN_CHANGE_FORFEIT,
                QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_OUT,
                QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_IN,
            )
        )
        .select_related("account")
    )


def scoped_accounts(user, context):
    customer_ids = scoped_customers(user, context).values("pk")
    return QuotaAccount.objects.filter(user_id__in=customer_ids).select_related(
        "user", "subscription"
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
