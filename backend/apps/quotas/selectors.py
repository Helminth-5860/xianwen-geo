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


def user_ledger(user):
    return QuotaLedgerEntry.objects.filter(user=user).select_related("account")


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
