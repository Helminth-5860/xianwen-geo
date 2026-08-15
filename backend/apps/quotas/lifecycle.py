import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.plans.models import Subscription, SubscriptionChange

from .catalog import QUOTA_CATALOG, quota_definition, snapshot_quota_values
from .exceptions import QuotaSnapshotInvalid, QuotaStateConflict
from .idempotency import system_idempotency_digests
from .models import (
    QuotaAccount,
    QuotaCycleReset,
    QuotaExpiryDisposition,
    QuotaLedgerEntry,
)
from .services import _append_ledger_locked, _create_initialized_account

SHANGHAI = ZoneInfo("Asia/Shanghai")
EXPIRY_POLICIES = {"zero", "freeze", "retain"}
MONTHLY_ACCOUNT_KEYS = tuple(
    item.key for item in QUOTA_CATALOG if item.reset_type == "monthly" and not item.subject_level
)


class QuotaLifecycleIntegrityError(QuotaStateConflict):
    code = "QUOTA_LIFECYCLE_INTEGRITY_ERROR"


def next_cycle_boundary(subscription: Subscription, boundary) -> datetime:
    local = timezone.localtime(boundary, SHANGHAI)
    year, month = local.year, local.month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    day = min(subscription.cycle_anchor_day, calendar.monthrange(year, month)[1])
    anchor = subscription.cycle_anchor_time
    local_boundary = datetime(
        year,
        month,
        day,
        anchor.hour,
        anchor.minute,
        anchor.second,
        anchor.microsecond,
        tzinfo=SHANGHAI,
    )
    return local_boundary.astimezone(subscription.ends_at.tzinfo)


def expiry_policy_map(subscription: Subscription) -> dict[str, str]:
    limits = subscription.entitlement_snapshot.get("limits")
    if not isinstance(limits, dict):
        raise QuotaSnapshotInvalid
    configured = limits.get("expiry_quota_policy", {})
    if configured is None:
        configured = {}
    if not isinstance(configured, dict):
        raise QuotaLifecycleIntegrityError
    policies: dict[str, str] = {}
    for account in subscription.quota_accounts.all():
        policy = configured.get(account.quota_type, "zero")
        if policy not in EXPIRY_POLICIES:
            raise QuotaLifecycleIntegrityError
        policies[account.quota_type] = policy
    return policies


def _forfeit(*, account, action, operation, request_id, business_type, business_id):
    amount = account.available
    if amount <= 0:
        return None
    digests = system_idempotency_digests(
        operation=operation,
        user_id=account.user_id,
        account_id=account.pk,
        business_type=business_type,
        business_id=business_id,
        request_payload={"account_id": str(account.pk), "amount": amount},
    )
    entry, _ = _append_ledger_locked(
        account=account,
        action=action,
        available_delta=-amount,
        frozen_delta=0,
        digests=digests,
        business_type=business_type,
        business_id=business_id,
        safe_reason="Lifecycle quota forfeit.",
        actor=None,
        request_id=request_id,
    )
    return entry


@transaction.atomic
def advance_cycle_account(*, account_id, request_id, now=None):
    moment = now or timezone.now()
    binding = QuotaAccount.objects.only("subscription_id").get(pk=account_id)
    subscription = Subscription.objects.select_for_update().get(pk=binding.subscription_id)
    previous = QuotaAccount.objects.select_for_update().get(pk=account_id)
    definition = quota_definition(previous.quota_type)
    if (
        previous.batch_type != QuotaAccount.BatchType.PRIMARY
        or definition.reset_type != "monthly"
        or previous.cycle_ends_at is None
    ):
        raise QuotaStateConflict
    if previous.cycle_ends_at > moment:
        return None
    existing = QuotaCycleReset.objects.filter(previous_account=previous).first()
    if existing is not None:
        return existing
    boundary = previous.cycle_ends_at
    if boundary >= subscription.ends_at:
        return None
    if subscription.status != Subscription.Status.ACTIVE:
        return None
    next_end = min(next_cycle_boundary(subscription, boundary), subscription.ends_at)
    if next_end <= boundary:
        return None
    forfeit = _forfeit(
        account=previous,
        action=QuotaLedgerEntry.Action.CYCLE_FORFEIT,
        operation="cycle_forfeit",
        request_id=request_id,
        business_type="quota_cycle_reset",
        business_id=previous.pk,
    )
    try:
        values = snapshot_quota_values(subscription.entitlement_snapshot)
    except ValueError as exc:
        raise QuotaSnapshotInvalid from exc
    next_account = _create_initialized_account(
        subscription=subscription,
        quota_type=previous.quota_type,
        amount=values[previous.quota_type],
        cycle_started_at=boundary,
        cycle_ends_at=next_end,
        request_id=request_id,
        actor=None,
        subject=previous.subject,
    )
    next_account.refresh_from_db(fields=("last_ledger_entry",))
    assert next_account.last_ledger_entry is not None
    return QuotaCycleReset.objects.create(
        subscription=subscription,
        quota_type=previous.quota_type,
        subject=previous.subject,
        boundary=boundary,
        previous_account=previous,
        next_account=next_account,
        forfeit_entry=forfeit,
        initialize_entry=next_account.last_ledger_entry,
        request_id=request_id,
    )


def catch_up_subscription_cycles(*, subscription_id, request_id, now=None, max_cycles=240):
    """Advance every elapsed monthly boundary in order.

    Each call to advance_cycle_account is independently atomic for normal
    worker catch-up. A caller that already owns an outer transaction (notably
    scheduled renewal execution) gets all-or-nothing catch-up instead.
    """
    moment = now or timezone.now()
    resets: list[QuotaCycleReset] = []
    for _ in range(max_cycles):
        account_id = (
            QuotaAccount.objects.filter(
                subscription_id=subscription_id,
                quota_type__in=MONTHLY_ACCOUNT_KEYS,
                batch_type=QuotaAccount.BatchType.PRIMARY,
                cycle_ends_at__isnull=False,
                cycle_ends_at__lte=moment,
                outgoing_cycle_reset__isnull=True,
            )
            .order_by("cycle_ends_at", "id")
            .values_list("id", flat=True)
            .first()
        )
        if account_id is None:
            return resets
        reset = advance_cycle_account(
            account_id=account_id,
            request_id=request_id,
            now=moment,
        )
        if reset is None:
            raise QuotaLifecycleIntegrityError
        resets.append(reset)
    if QuotaAccount.objects.filter(
        subscription_id=subscription_id,
        quota_type__in=MONTHLY_ACCOUNT_KEYS,
        batch_type=QuotaAccount.BatchType.PRIMARY,
        cycle_ends_at__isnull=False,
        cycle_ends_at__lte=moment,
        outgoing_cycle_reset__isnull=True,
    ).exists():
        raise QuotaLifecycleIntegrityError
    return resets


@transaction.atomic
def apply_expiry_dispositions(*, subscription_id, request_id, renewal_change_id=None):
    subscription = Subscription.objects.select_for_update().get(pk=subscription_id)
    renewal = None
    if renewal_change_id is not None:
        renewal = SubscriptionChange.objects.select_for_update().get(pk=renewal_change_id)
    accounts = list(
        QuotaAccount.objects.select_for_update().filter(subscription=subscription).order_by("id")
    )
    policies = expiry_policy_map(subscription)
    results = []
    for account in accounts:
        existing = QuotaExpiryDisposition.objects.filter(account=account).first()
        if existing is not None:
            results.append(existing)
            continue
        policy = policies[account.quota_type]
        ledger = None
        linked_change = None
        if policy == QuotaExpiryDisposition.Policy.ZERO:
            ledger = _forfeit(
                account=account,
                action=QuotaLedgerEntry.Action.EXPIRY_FORFEIT,
                operation="expiry_forfeit",
                request_id=request_id,
                business_type="subscription_expiry",
                business_id=subscription.pk,
            )
            if ledger is None:
                ledger = (
                    QuotaLedgerEntry.objects.filter(
                        account=account,
                        action=QuotaLedgerEntry.Action.EXPIRY_FORFEIT,
                        business_id=subscription.pk,
                    )
                    .order_by("-sequence")
                    .first()
                )
        elif policy == QuotaExpiryDisposition.Policy.RETAIN and renewal is not None:
            linked_change = renewal
        results.append(
            QuotaExpiryDisposition.objects.create(
                account=account,
                subscription=subscription,
                policy=policy,
                ledger_entry=ledger,
                renewal_change=linked_change,
                request_id=request_id,
            )
        )
    return results


def due_cycle_account_ids(*, now=None, limit=100):
    moment = now or timezone.now()
    return list(
        QuotaAccount.objects.filter(
            subscription__status=Subscription.Status.ACTIVE,
            batch_type=QuotaAccount.BatchType.PRIMARY,
            cycle_ends_at__isnull=False,
            cycle_ends_at__lte=moment,
            outgoing_cycle_reset__isnull=True,
        )
        .order_by("cycle_ends_at", "id")
        .values_list("id", flat=True)[:limit]
    )
