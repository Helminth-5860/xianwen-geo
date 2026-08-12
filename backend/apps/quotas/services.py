import calendar
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.plans.models import Subscription
from apps.users.validators import validate_safe_plain_text

from .catalog import (
    CURRENT_ACCOUNT_DEFINITIONS,
    quota_definition,
    snapshot_quota_values,
    validate_quota_amount,
)
from .exceptions import (
    QuotaBusinessAlreadyHeld,
    QuotaHoldStateConflict,
    QuotaIdempotencyConflict,
    QuotaInsufficient,
    QuotaSnapshotInvalid,
    QuotaStateConflict,
    QuotaSubscriptionUnavailable,
    QuotaVersionConflict,
)
from .idempotency import (
    IdempotencyDigests,
    derive_idempotency_digests,
    system_idempotency_digests,
)
from .models import (
    QuotaAccount,
    QuotaExpiryDisposition,
    QuotaHold,
    QuotaHoldGroup,
    QuotaLedgerEntry,
    QuotaTransfer,
)
from .selectors import scoped_account_or_404

BUSINESS_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
BATCH_NAMESPACE = uuid.UUID("75b40c5c-b210-48a7-8805-a8f056e4eeac")


@dataclass(frozen=True)
class ReplayResult:
    account_id: uuid.UUID
    entries: int
    available: int
    frozen: int
    ledger_sequence: int


def _positive_amount(amount) -> int:
    try:
        value = validate_quota_amount(amount)
    except ValueError as exc:
        raise QuotaStateConflict from exc
    if value <= 0:
        raise QuotaStateConflict
    return value


def _business_type(value: str) -> str:
    normalized = (value or "").strip()
    if not BUSINESS_TYPE_PATTERN.fullmatch(normalized):
        raise QuotaStateConflict
    return normalized


def _safe_reason(reason: str, *, required: bool = False) -> str:
    try:
        return validate_safe_plain_text(
            reason,
            field_label="额度操作原因",
            max_length=500,
            required=required,
        )
    except Exception as exc:
        raise QuotaStateConflict from exc


def _first_cycle_window(subscription: Subscription):
    local_start = timezone.localtime(subscription.starts_at)
    year, month = local_start.year, local_start.month
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    day = min(subscription.cycle_anchor_day, calendar.monthrange(next_year, next_month)[1])
    local_boundary = datetime(
        next_year,
        next_month,
        day,
        local_start.hour,
        local_start.minute,
        local_start.second,
        local_start.microsecond,
        tzinfo=local_start.tzinfo,
    )
    boundary = local_boundary.astimezone(subscription.starts_at.tzinfo)
    return subscription.starts_at, min(boundary, subscription.ends_at)


def _batch_key(subscription_id, quota_type: str, cycle_started_at) -> uuid.UUID:
    cycle = cycle_started_at.isoformat() if cycle_started_at else "subscription"
    return uuid.uuid5(BATCH_NAMESPACE, f"{subscription_id}|{quota_type}|{cycle}")


def _subscription_effective(subscription: Subscription, account: QuotaAccount, moment) -> bool:
    if (
        subscription.status != Subscription.Status.ACTIVE
        or subscription.starts_at > moment
        or subscription.ends_at <= moment
    ):
        return False
    if account.spendable_until is not None and account.spendable_until <= moment:
        return False
    if account.cycle_started_at is None:
        return account.cycle_ends_at is None
    return account.cycle_started_at <= moment < account.cycle_ends_at


def _assert_idempotent_match(
    entry: QuotaLedgerEntry,
    *,
    account: QuotaAccount,
    action: str,
    digests: IdempotencyDigests,
) -> None:
    if (
        entry.account_id != account.pk
        or entry.action != action
        or entry.idempotency_key_version != digests.key_version
        or entry.idempotency_scope_digest != digests.scope_digest
        or entry.request_digest != digests.request_digest
    ):
        raise QuotaIdempotencyConflict


def _idempotent_entry(
    account: QuotaAccount, action: str, digests: IdempotencyDigests
) -> QuotaLedgerEntry | None:
    entry = QuotaLedgerEntry.objects.filter(idempotency_key_digest=digests.key_digest).first()
    if entry is not None:
        _assert_idempotent_match(entry, account=account, action=action, digests=digests)
    return entry


def _append_ledger_locked(
    *,
    account: QuotaAccount,
    action: str,
    available_delta: int,
    frozen_delta: int,
    digests: IdempotencyDigests,
    business_type: str,
    business_id,
    safe_reason: str,
    actor,
    request_id,
    hold: QuotaHold | None = None,
) -> tuple[QuotaLedgerEntry, bool]:
    existing = _idempotent_entry(account, action, digests)
    if existing is not None:
        return existing, True
    available_after = account.available + available_delta
    frozen_after = account.frozen + frozen_delta
    if available_after < 0:
        raise QuotaInsufficient
    if frozen_after < 0:
        raise QuotaHoldStateConflict
    try:
        entry = QuotaLedgerEntry.objects.create(
            account=account,
            hold=hold,
            user_id=account.user_id,
            subscription_id=account.subscription_id,
            quota_type=account.quota_type,
            sequence=account.ledger_sequence + 1,
            action=action,
            available_before=account.available,
            available_delta=available_delta,
            available_after=available_after,
            frozen_before=account.frozen,
            frozen_delta=frozen_delta,
            frozen_after=frozen_after,
            account_version_before=account.version,
            account_version_after=account.version + 1,
            business_type=business_type,
            business_id=business_id,
            safe_reason=safe_reason,
            actor=actor,
            request_id=request_id,
            idempotency_key_version=digests.key_version,
            idempotency_key_digest=digests.key_digest,
            idempotency_scope_digest=digests.scope_digest,
            request_digest=digests.request_digest,
        )
    except IntegrityError:
        existing = QuotaLedgerEntry.objects.filter(
            idempotency_key_digest=digests.key_digest
        ).first()
        if existing is None:
            raise
        _assert_idempotent_match(existing, account=account, action=action, digests=digests)
        return existing, True
    changed = QuotaAccount.objects.filter(pk=account.pk, version=account.version).update(
        available=available_after,
        frozen=frozen_after,
        ledger_sequence=entry.sequence,
        last_ledger_entry=entry,
        version=account.version + 1,
        updated_at=timezone.now(),
    )
    if changed != 1:
        raise QuotaVersionConflict
    account.available = available_after
    account.frozen = frozen_after
    account.ledger_sequence = entry.sequence
    account.last_ledger_entry = entry
    account.version += 1
    return entry, False


def _lock_account(account_id) -> tuple[Subscription, QuotaAccount]:
    try:
        binding = QuotaAccount.objects.only("subscription_id").get(pk=account_id)
    except QuotaAccount.DoesNotExist as exc:
        raise NotFound from exc
    subscription = Subscription.objects.select_for_update().get(pk=binding.subscription_id)
    account = QuotaAccount.objects.select_for_update().get(pk=account_id)
    return subscription, account


def _lock_hold(hold_id) -> tuple[Subscription, QuotaAccount, QuotaHold]:
    try:
        binding = QuotaHold.objects.only("subscription_id", "account_id").get(pk=hold_id)
    except QuotaHold.DoesNotExist as exc:
        raise NotFound from exc
    subscription = Subscription.objects.select_for_update().get(pk=binding.subscription_id)
    account = QuotaAccount.objects.select_for_update().get(pk=binding.account_id)
    hold = QuotaHold.objects.select_for_update().get(pk=hold_id)
    return subscription, account, hold


def _snapshot_values(subscription: Subscription) -> dict[str, int]:
    try:
        return snapshot_quota_values(subscription.entitlement_snapshot)
    except ValueError as exc:
        raise QuotaSnapshotInvalid from exc


def storage_usage_bytes(user_id) -> int:
    from apps.documents.models import FileStorageAllocation

    return int(
        FileStorageAllocation.objects.filter(user_id=user_id).aggregate(total=Sum("size_bytes"))[
            "total"
        ]
        or 0
    )


def _reconcile_storage_account_locked(*, account, request_id, actor=None):
    if account.quota_type != "storage_bytes" or account.frozen != 0:
        if account.quota_type == "storage_bytes" and account.frozen != 0:
            raise QuotaHoldStateConflict
        return None
    usage = storage_usage_bytes(account.user_id)
    target = max(account.entitlement_amount - usage, 0)
    delta = target - account.available
    if delta == 0:
        return None
    digests = system_idempotency_digests(
        operation="storage_capacity_reconcile",
        user_id=account.user_id,
        account_id=account.pk,
        business_type="storage_capacity",
        business_id=account.subscription_id,
        request_payload={"usage": usage, "target": target},
    )
    entry, _ = _append_ledger_locked(
        account=account,
        action=QuotaLedgerEntry.Action.STORAGE_CAPACITY_RECONCILE,
        available_delta=delta,
        frozen_delta=0,
        digests=digests,
        business_type="storage_capacity",
        business_id=account.subscription_id,
        safe_reason="Storage capacity reconciled against immutable allocation usage.",
        actor=actor,
        request_id=request_id,
    )
    return entry


@transaction.atomic
def reconcile_storage_capacity_for_user(*, user_id, request_id, apply: bool):
    from apps.users.models import User

    User.objects.select_for_update().get(pk=user_id)
    now = timezone.now()
    subscription = (
        Subscription.objects.select_for_update()
        .filter(
            user_id=user_id, status=Subscription.Status.ACTIVE, starts_at__lte=now, ends_at__gt=now
        )
        .order_by("starts_at", "id")
        .first()
    )
    if subscription is None:
        return None
    account = (
        QuotaAccount.objects.select_for_update()
        .filter(
            subscription=subscription,
            quota_type="storage_bytes",
            batch_type=QuotaAccount.BatchType.PRIMARY,
        )
        .order_by("id")
        .first()
    )
    if account is None:
        raise QuotaStateConflict
    usage = storage_usage_bytes(user_id)
    target = max(account.entitlement_amount - usage, 0)
    preview = {
        "user_id": str(user_id),
        "account_id": str(account.pk),
        "usage": usage,
        "target": target,
        "current": account.available,
    }
    if apply:
        _reconcile_storage_account_locked(account=account, request_id=request_id)
    else:
        transaction.set_rollback(True)
    return preview


def _create_initialized_account(
    *,
    subscription: Subscription,
    quota_type: str,
    amount: int,
    cycle_started_at,
    cycle_ends_at,
    request_id,
    actor,
) -> QuotaAccount:
    definition = quota_definition(quota_type)
    batch_key = _batch_key(subscription.pk, quota_type, cycle_started_at)
    existing = QuotaAccount.objects.filter(
        subscription=subscription, quota_type=quota_type, batch_key=batch_key
    ).first()
    if existing is not None:
        return existing
    account = QuotaAccount.objects.create(
        user_id=subscription.user_id,
        subscription=subscription,
        quota_type=quota_type,
        scope=definition.scope,
        unit=definition.unit,
        batch_key=batch_key,
        entitlement_amount=amount,
        cycle_started_at=cycle_started_at,
        cycle_ends_at=cycle_ends_at,
    )
    digests = system_idempotency_digests(
        operation="initialize",
        user_id=subscription.user_id,
        account_id=account.pk,
        business_type="subscription",
        business_id=subscription.pk,
        request_payload={
            "quota_type": quota_type,
            "amount": amount,
            "cycle_started_at": cycle_started_at.isoformat() if cycle_started_at else None,
            "cycle_ends_at": cycle_ends_at.isoformat() if cycle_ends_at else None,
        },
    )
    _append_ledger_locked(
        account=account,
        action=QuotaLedgerEntry.Action.INITIALIZE,
        available_delta=amount,
        frozen_delta=0,
        digests=digests,
        business_type="subscription",
        business_id=subscription.pk,
        safe_reason="订阅额度初始化。",
        actor=actor,
        request_id=request_id,
    )
    if definition.accounting_mode == "capacity_absolute":
        _reconcile_storage_account_locked(account=account, request_id=request_id, actor=actor)
    return account


@transaction.atomic
def initialize_subscription_accounts(*, subscription: Subscription, request_id, actor=None):
    locked = Subscription.objects.select_for_update().get(pk=subscription.pk)
    values = _snapshot_values(locked)
    accounts = []
    for definition in CURRENT_ACCOUNT_DEFINITIONS:
        cycle_started_at = cycle_ends_at = None
        if definition.scope == QuotaAccount.Scope.ACCOUNT_CYCLE:
            cycle_started_at, cycle_ends_at = _first_cycle_window(locked)
        accounts.append(
            _create_initialized_account(
                subscription=locked,
                quota_type=definition.key,
                amount=values[definition.key],
                cycle_started_at=cycle_started_at,
                cycle_ends_at=cycle_ends_at,
                request_id=request_id,
                actor=actor,
            )
        )
    return accounts


@transaction.atomic
def create_cycle_batch(
    *, subscription_id, quota_type: str, cycle_started_at, cycle_ends_at, request_id
):
    definition = quota_definition(quota_type)
    if definition.subject_level or definition.reset_type != "monthly":
        raise QuotaStateConflict
    subscription = Subscription.objects.select_for_update().get(pk=subscription_id)
    now = timezone.now()
    if (
        subscription.status != Subscription.Status.ACTIVE
        or not subscription.starts_at <= now < subscription.ends_at
        or not subscription.starts_at <= cycle_started_at < cycle_ends_at <= subscription.ends_at
    ):
        raise QuotaSubscriptionUnavailable
    values = _snapshot_values(subscription)
    return _create_initialized_account(
        subscription=subscription,
        quota_type=quota_type,
        amount=values[quota_type],
        cycle_started_at=cycle_started_at,
        cycle_ends_at=cycle_ends_at,
        request_id=request_id,
        actor=None,
    )


@transaction.atomic
def _legacy_freeze_quota(
    *,
    account_id,
    amount,
    business_type,
    business_id,
    idempotency_key,
    request_id,
):
    subscription, account = _lock_account(account_id)
    now = timezone.now()
    if not _subscription_effective(subscription, account, now):
        raise QuotaSubscriptionUnavailable
    amount = _positive_amount(amount)
    business_type = _business_type(business_type)
    digests = derive_idempotency_digests(
        idempotency_key,
        operation="freeze",
        user_id=account.user_id,
        account_id=account.pk,
        business_type=business_type,
        business_id=business_id,
        request_payload={"amount": amount},
    )
    existing_entry = _idempotent_entry(account, QuotaLedgerEntry.Action.FREEZE, digests)
    if existing_entry is not None:
        if existing_entry.hold_id is None:
            raise QuotaStateConflict
        return QuotaHold.objects.get(pk=existing_entry.hold_id)
    existing_hold = QuotaHold.objects.filter(
        account=account, business_type=business_type, business_id=business_id
    ).first()
    if existing_hold is not None:
        raise QuotaBusinessAlreadyHeld
    if account.available < amount:
        raise QuotaInsufficient
    try:
        hold = QuotaHold.objects.create(
            account=account,
            user_id=account.user_id,
            subscription=subscription,
            quota_type=account.quota_type,
            business_type=business_type,
            business_id=business_id,
            requested_amount=amount,
            freeze_idempotency_key_version=digests.key_version,
            freeze_idempotency_key_digest=digests.key_digest,
            freeze_idempotency_scope_digest=digests.scope_digest,
            freeze_request_digest=digests.request_digest,
        )
    except IntegrityError as exc:
        if QuotaHold.objects.filter(
            account=account, business_type=business_type, business_id=business_id
        ).exists():
            raise QuotaBusinessAlreadyHeld from exc
        raise
    _append_ledger_locked(
        account=account,
        hold=hold,
        action=QuotaLedgerEntry.Action.FREEZE,
        available_delta=-amount,
        frozen_delta=amount,
        digests=digests,
        business_type=business_type,
        business_id=business_id,
        safe_reason="业务额度冻结。",
        actor=None,
        request_id=request_id,
    )
    return hold


def _legacy_settle_hold(
    *, hold_id, amount, action: str, idempotency_key: str, request_id
) -> QuotaHold:
    subscription, account, hold = _lock_hold(hold_id)
    del subscription
    amount = _positive_amount(amount)
    digests = derive_idempotency_digests(
        idempotency_key,
        operation=action,
        user_id=hold.user_id,
        account_id=account.pk,
        business_type=hold.business_type,
        business_id=hold.business_id,
        request_payload={"hold_id": str(hold.pk), "amount": amount},
    )
    existing = _idempotent_entry(account, action, digests)
    if existing is not None:
        return QuotaHold.objects.get(pk=hold.pk)
    if hold.status == QuotaHold.Status.SETTLED:
        raise QuotaHoldStateConflict
    remaining = hold.requested_amount - hold.consumed_amount - hold.released_amount
    if amount > remaining:
        raise QuotaHoldStateConflict
    available_delta = amount if action == QuotaLedgerEntry.Action.RELEASE else 0
    _append_ledger_locked(
        account=account,
        hold=hold,
        action=action,
        available_delta=available_delta,
        frozen_delta=-amount,
        digests=digests,
        business_type=hold.business_type,
        business_id=hold.business_id,
        safe_reason="业务额度返还。" if action == "release" else "业务额度扣除。",
        actor=None,
        request_id=request_id,
    )
    if action == QuotaLedgerEntry.Action.CONSUME:
        hold.consumed_amount += amount
    else:
        hold.released_amount += amount
    total = hold.consumed_amount + hold.released_amount
    hold.status = (
        QuotaHold.Status.SETTLED
        if total == hold.requested_amount
        else QuotaHold.Status.PARTIALLY_SETTLED
    )
    hold.settled_at = timezone.now() if hold.status == QuotaHold.Status.SETTLED else None
    hold.version += 1
    hold.save(
        update_fields=[
            "consumed_amount",
            "released_amount",
            "status",
            "settled_at",
            "version",
            "updated_at",
        ]
    )
    return hold


@transaction.atomic
def consume_hold(*, hold_id, amount, idempotency_key, request_id):
    return _settle_hold(
        hold_id=hold_id,
        amount=amount,
        action=QuotaLedgerEntry.Action.CONSUME,
        idempotency_key=idempotency_key,
        request_id=request_id,
    )


@transaction.atomic
def release_hold(*, hold_id, amount, idempotency_key, request_id):
    return _settle_hold(
        hold_id=hold_id,
        amount=amount,
        action=QuotaLedgerEntry.Action.RELEASE,
        idempotency_key=idempotency_key,
        request_id=request_id,
    )


def lock_scoped_account(requester, context, account_id):
    visible = scoped_account_or_404(requester, context, account_id)
    subscription = Subscription.objects.select_for_update().get(pk=visible.subscription_id)
    account = QuotaAccount.objects.select_for_update().get(pk=visible.pk)
    return subscription, account


@transaction.atomic
def adjust_quota_account(
    *,
    requester,
    admin_context,
    account_id,
    expected_version,
    action,
    amount,
    reason,
    digests: IdempotencyDigests,
    request_id,
):
    subscription, account = lock_scoped_account(requester, admin_context, account_id)
    if quota_definition(account.quota_type).accounting_mode == "capacity_absolute":
        raise QuotaStateConflict
    if account.version != expected_version:
        raise QuotaVersionConflict
    if not _subscription_effective(subscription, account, timezone.now()):
        raise QuotaSubscriptionUnavailable
    amount = _positive_amount(amount)
    reason = _safe_reason(reason, required=True)
    allowed = {
        QuotaLedgerEntry.Action.GRANT,
        QuotaLedgerEntry.Action.COMPENSATE,
        QuotaLedgerEntry.Action.MANUAL_DEDUCT,
    }
    if action not in allowed:
        raise QuotaStateConflict
    delta = -amount if action == QuotaLedgerEntry.Action.MANUAL_DEDUCT else amount
    entry, _ = _append_ledger_locked(
        account=account,
        action=action,
        available_delta=delta,
        frozen_delta=0,
        digests=digests,
        business_type="quota_adjustment",
        business_id=account.pk,
        safe_reason=reason,
        actor=requester,
        request_id=request_id,
    )
    return account, entry


def replay_account(account: QuotaAccount) -> ReplayResult:
    available = frozen = sequence = 0
    version = 1
    entries = list(account.ledger_entries.order_by("sequence"))
    for entry in entries:
        if entry.sequence != sequence + 1:
            raise QuotaStateConflict("额度流水序号不连续。")
        if (
            entry.available_before != available
            or entry.frozen_before != frozen
            or entry.account_version_before != version
            or entry.available_after != available + entry.available_delta
            or entry.frozen_after != frozen + entry.frozen_delta
            or entry.account_version_after != version + 1
        ):
            raise QuotaStateConflict("额度流水前后余额不一致。")
        if entry.available_after < 0 or entry.frozen_after < 0:
            raise QuotaStateConflict("额度流水出现负余额。")
        available = entry.available_after
        frozen = entry.frozen_after
        sequence = entry.sequence
        version = entry.account_version_after
    if (
        account.available != available
        or account.frozen != frozen
        or account.ledger_sequence != sequence
        or account.version != version
        or (entries and account.last_ledger_entry_id != entries[-1].pk)
        or (not entries and account.last_ledger_entry_id is not None)
    ):
        raise QuotaStateConflict("额度账户与流水重放结果不一致。")
    return ReplayResult(account.pk, len(entries), available, frozen, sequence)


def verify_all_accounts():
    return [replay_account(account) for account in QuotaAccount.objects.order_by("id")]


def subscription_has_unsettled_holds(subscription: Subscription) -> bool:
    return QuotaHoldGroup.objects.filter(
        allocations__subscription=subscription,
        status__in=(
            QuotaHoldGroup.Status.OPEN,
            QuotaHoldGroup.Status.PARTIALLY_SETTLED,
        ),
    ).exists()


def _change_ledger_digests(*, change, account, action, amount):
    return system_idempotency_digests(
        operation=action,
        user_id=account.user_id,
        account_id=account.pk,
        business_type="subscription_change",
        business_id=change.pk,
        request_payload={
            "change_id": str(change.pk),
            "quota_type": account.quota_type,
            "amount": amount,
        },
    )


def _forfeit_for_change(*, change, account, actor, request_id):
    amount = account.available
    if amount <= 0:
        return None
    entry, _ = _append_ledger_locked(
        account=account,
        action=QuotaLedgerEntry.Action.PLAN_CHANGE_FORFEIT,
        available_delta=-amount,
        frozen_delta=0,
        digests=_change_ledger_digests(
            change=change,
            account=account,
            action=QuotaLedgerEntry.Action.PLAN_CHANGE_FORFEIT,
            amount=amount,
        ),
        business_type="subscription_change",
        business_id=change.pk,
        safe_reason="套餐变更旧额度清零。",
        actor=actor,
        request_id=request_id,
    )
    return entry


def _forfeit_for_expiry(*, change, account, actor, request_id):
    amount = account.available
    if amount <= 0:
        return None
    entry, _ = _append_ledger_locked(
        account=account,
        action=QuotaLedgerEntry.Action.EXPIRY_FORFEIT,
        available_delta=-amount,
        frozen_delta=0,
        digests=_change_ledger_digests(
            change=change,
            account=account,
            action=QuotaLedgerEntry.Action.EXPIRY_FORFEIT,
            amount=amount,
        ),
        business_type="subscription_expiry",
        business_id=account.subscription_id,
        safe_reason="Subscription expiry quota forfeit.",
        actor=actor,
        request_id=request_id,
    )
    return entry


def _create_carryover_account(*, change, source_account, target_subscription, spendable_until):
    definition = quota_definition(source_account.quota_type)
    batch_key = uuid.uuid5(
        BATCH_NAMESPACE,
        f"carryover|{change.pk}|{source_account.pk}|{target_subscription.pk}",
    )
    cycle_started_at = cycle_ends_at = None
    if definition.scope == QuotaAccount.Scope.ACCOUNT_CYCLE:
        cycle_started_at = change.executed_at
        cycle_ends_at = spendable_until
    account = QuotaAccount.objects.create(
        user_id=target_subscription.user_id,
        subscription=target_subscription,
        quota_type=source_account.quota_type,
        scope=definition.scope,
        unit=definition.unit,
        batch_key=batch_key,
        batch_type=QuotaAccount.BatchType.CARRYOVER,
        spendable_until=spendable_until,
        source_change=change,
        entitlement_amount=0,
        cycle_started_at=cycle_started_at,
        cycle_ends_at=cycle_ends_at,
    )
    digests = system_idempotency_digests(
        operation="initialize_carryover",
        user_id=account.user_id,
        account_id=account.pk,
        business_type="subscription_change",
        business_id=change.pk,
        request_payload={
            "source_account_id": str(source_account.pk),
            "spendable_until": spendable_until.isoformat(),
        },
    )
    _append_ledger_locked(
        account=account,
        action=QuotaLedgerEntry.Action.INITIALIZE,
        available_delta=0,
        frozen_delta=0,
        digests=digests,
        business_type="subscription_change",
        business_id=change.pk,
        safe_reason="套餐变更保留批次初始化。",
        actor=change.requested_by,
        request_id=change.request_id,
    )
    return account


def _transfer_for_change(*, change, source, target, actor, request_id):
    amount = source.available
    if amount <= 0:
        return None
    out_entry, _ = _append_ledger_locked(
        account=source,
        action=QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_OUT,
        available_delta=-amount,
        frozen_delta=0,
        digests=_change_ledger_digests(
            change=change,
            account=source,
            action=QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_OUT,
            amount=amount,
        ),
        business_type="subscription_change",
        business_id=change.pk,
        safe_reason="套餐变更额度转出。",
        actor=actor,
        request_id=request_id,
    )
    in_entry, _ = _append_ledger_locked(
        account=target,
        action=QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_IN,
        available_delta=amount,
        frozen_delta=0,
        digests=_change_ledger_digests(
            change=change,
            account=target,
            action=QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_IN,
            amount=amount,
        ),
        business_type="subscription_change",
        business_id=change.pk,
        safe_reason="套餐变更额度转入。",
        actor=actor,
        request_id=request_id,
    )
    return QuotaTransfer.objects.create(
        change=change,
        quota_type=source.quota_type,
        amount=amount,
        source_account=source,
        target_account=target,
        transfer_out_entry=out_entry,
        transfer_in_entry=in_entry,
        request_id=request_id,
    )


def apply_subscription_change_quotas(
    *,
    change,
    source_subscription: Subscription,
    target_subscription: Subscription,
    quota_policy: str,
    expiry_policies: dict[str, str] | None = None,
    actor,
    request_id,
    now,
):
    source_accounts = list(
        QuotaAccount.objects.filter(subscription=source_subscription).order_by("id")
    )
    target_primary = {
        account.quota_type: account
        for account in QuotaAccount.objects.filter(
            subscription=target_subscription,
            batch_type=QuotaAccount.BatchType.PRIMARY,
        )
    }
    account_ids = sorted(
        [account.pk for account in source_accounts]
        + [account.pk for account in target_primary.values()],
        key=str,
    )
    locked = {
        account.pk: account
        for account in QuotaAccount.objects.select_for_update()
        .filter(pk__in=account_ids)
        .order_by("id")
    }
    source_accounts = [locked[account.pk] for account in source_accounts]
    source_accounts = [
        account for account in source_accounts if account.quota_type != "storage_bytes"
    ]
    target_primary = {
        quota_type: locked[account.pk] for quota_type, account in target_primary.items()
    }
    group_ids = list(
        QuotaHold.objects.filter(subscription=source_subscription)
        .order_by()
        .values_list("group_id", flat=True)
        .distinct()
    )
    groups = list(
        QuotaHoldGroup.objects.select_for_update().filter(pk__in=group_ids).order_by("id")
    )
    _locked_holds = list(
        QuotaHold.objects.select_for_update().filter(group_id__in=group_ids).order_by("id")
    )
    if any(
        group.status in (QuotaHoldGroup.Status.OPEN, QuotaHoldGroup.Status.PARTIALLY_SETTLED)
        for group in groups
    ):
        raise QuotaHoldStateConflict
    if any(account.frozen != 0 for account in source_accounts):
        raise QuotaHoldStateConflict

    for source in source_accounts:
        if source.available <= 0:
            continue
        spendable_until = source.cycle_ends_at or source_subscription.ends_at
        expiry_policy = (
            expiry_policies.get(source.quota_type, "zero") if expiry_policies is not None else None
        )
        if expiry_policy == "zero":
            _forfeit_for_expiry(change=change, account=source, actor=actor, request_id=request_id)
            continue
        if expiry_policy == "freeze":
            continue
        expired_for_change = spendable_until <= now and expiry_policy != "retain"
        if expired_for_change or quota_policy == "overwrite":
            _forfeit_for_change(
                change=change,
                account=source,
                actor=actor,
                request_id=request_id,
            )
            continue
        if quota_policy == "accumulate":
            target = target_primary.get(source.quota_type)
            if target is None:
                _forfeit_for_change(
                    change=change,
                    account=source,
                    actor=actor,
                    request_id=request_id,
                )
                continue
        elif quota_policy == "retain":
            target = _create_carryover_account(
                change=change,
                source_account=source,
                target_subscription=target_subscription,
                spendable_until=spendable_until,
            )
        else:
            raise QuotaStateConflict
        _transfer_for_change(
            change=change,
            source=source,
            target=target,
            actor=actor,
            request_id=request_id,
        )

    if any(account.available != 0 or account.frozen != 0 for account in source_accounts):
        raise QuotaStateConflict


def _spend_order(account: QuotaAccount):
    deadline = account.spendable_until or account.cycle_ends_at
    return (
        deadline or datetime.max.replace(tzinfo=UTC),
        account.batch_type,
        str(account.pk),
    )


@transaction.atomic
def freeze_quota(
    *,
    account_id,
    amount,
    business_type,
    business_id,
    idempotency_key,
    request_id,
):
    try:
        binding = QuotaAccount.objects.only("subscription_id", "quota_type", "user_id").get(
            pk=account_id
        )
    except QuotaAccount.DoesNotExist as exc:
        raise NotFound from exc
    subscription = Subscription.objects.select_for_update().get(pk=binding.subscription_id)
    now = timezone.now()
    if (
        subscription.status != Subscription.Status.ACTIVE
        or not subscription.starts_at <= now < subscription.ends_at
    ):
        raise QuotaSubscriptionUnavailable
    accounts = list(
        QuotaAccount.objects.select_for_update()
        .filter(subscription=subscription, quota_type=binding.quota_type)
        .order_by("id")
    )
    if binding.quota_type == "storage_bytes":
        accounts = [
            account
            for account in accounts
            if account.pk == account_id
            and account.batch_type == QuotaAccount.BatchType.PRIMARY
            and account.cycle_started_at is None
        ]
    accounts = sorted(
        [account for account in accounts if _subscription_effective(subscription, account, now)],
        key=_spend_order,
    )
    amount = _positive_amount(amount)
    business_type = _business_type(business_type)
    digests = derive_idempotency_digests(
        idempotency_key,
        operation="freeze_group",
        user_id=binding.user_id,
        account_id=account_id,
        business_type=business_type,
        business_id=business_id,
        request_payload={"amount": amount, "quota_type": binding.quota_type},
    )
    existing = QuotaHoldGroup.objects.filter(
        freeze_idempotency_key_digest=digests.key_digest
    ).first()
    if existing is not None:
        if (
            existing.user_id != binding.user_id
            or existing.quota_type != binding.quota_type
            or existing.business_type != business_type
            or existing.business_id != business_id
            or existing.freeze_idempotency_scope_digest != digests.scope_digest
            or existing.freeze_request_digest != digests.request_digest
        ):
            raise QuotaIdempotencyConflict
        return existing
    if QuotaHoldGroup.objects.filter(
        user_id=binding.user_id,
        quota_type=binding.quota_type,
        business_type=business_type,
        business_id=business_id,
    ).exists():
        raise QuotaBusinessAlreadyHeld
    if sum(account.available for account in accounts) < amount:
        raise QuotaInsufficient
    group = QuotaHoldGroup.objects.create(
        user_id=binding.user_id,
        quota_type=binding.quota_type,
        business_type=business_type,
        business_id=business_id,
        requested_amount=amount,
        freeze_idempotency_key_version=digests.key_version,
        freeze_idempotency_key_digest=digests.key_digest,
        freeze_idempotency_scope_digest=digests.scope_digest,
        freeze_request_digest=digests.request_digest,
    )
    remaining = amount
    for account in accounts:
        allocated = min(account.available, remaining)
        if allocated <= 0:
            continue
        allocation_digests = system_idempotency_digests(
            operation="freeze_allocation",
            user_id=account.user_id,
            account_id=account.pk,
            business_type=business_type,
            business_id=business_id,
            request_payload={"group_id": str(group.pk), "amount": allocated},
        )
        hold = QuotaHold.objects.create(
            group=group,
            account=account,
            user_id=account.user_id,
            subscription=subscription,
            quota_type=account.quota_type,
            business_type=business_type,
            business_id=business_id,
            requested_amount=allocated,
            freeze_idempotency_key_version=allocation_digests.key_version,
            freeze_idempotency_key_digest=allocation_digests.key_digest,
            freeze_idempotency_scope_digest=allocation_digests.scope_digest,
            freeze_request_digest=allocation_digests.request_digest,
        )
        _append_ledger_locked(
            account=account,
            hold=hold,
            action=QuotaLedgerEntry.Action.FREEZE,
            available_delta=-allocated,
            frozen_delta=allocated,
            digests=allocation_digests,
            business_type=business_type,
            business_id=business_id,
            safe_reason="业务额度冻结。",
            actor=None,
            request_id=request_id,
        )
        remaining -= allocated
        if remaining == 0:
            break
    if remaining != 0:
        raise QuotaInsufficient
    return group


def _group_for_handle(hold_id):
    group = QuotaHoldGroup.objects.filter(pk=hold_id).first()
    if group is not None:
        return group
    allocation = QuotaHold.objects.only("group_id").filter(pk=hold_id).first()
    if allocation is None:
        raise NotFound
    return QuotaHoldGroup.objects.get(pk=allocation.group_id)


def _settle_hold(*, hold_id, amount, action: str, idempotency_key: str, request_id):
    group_binding = _group_for_handle(hold_id)
    allocation_bindings = list(
        QuotaHold.objects.filter(group=group_binding).values("id", "account_id", "subscription_id")
    )
    subscription_ids = sorted(
        {binding["subscription_id"] for binding in allocation_bindings}, key=str
    )
    list(Subscription.objects.select_for_update().filter(pk__in=subscription_ids).order_by("id"))
    account_ids = sorted({binding["account_id"] for binding in allocation_bindings}, key=str)
    accounts = {
        account.pk: account
        for account in QuotaAccount.objects.select_for_update()
        .filter(pk__in=account_ids)
        .order_by("id")
    }
    group = QuotaHoldGroup.objects.select_for_update().get(pk=group_binding.pk)
    allocations = list(
        QuotaHold.objects.select_for_update()
        .filter(group=group)
        .select_related("account")
        .order_by("id")
    )
    allocations.sort(key=lambda hold: _spend_order(accounts[hold.account_id]))
    amount = _positive_amount(amount)
    client_digests = derive_idempotency_digests(
        idempotency_key,
        operation=f"{action}_group",
        user_id=group.user_id,
        account_id=group.pk,
        business_type=group.business_type,
        business_id=group.business_id,
        request_payload={"group_id": str(group.pk), "amount": amount},
    )
    existing = QuotaLedgerEntry.objects.filter(
        idempotency_key_digest=client_digests.key_digest
    ).first()
    if existing is not None:
        if (
            existing.idempotency_scope_digest != client_digests.scope_digest
            or existing.request_digest != client_digests.request_digest
        ):
            raise QuotaIdempotencyConflict
        return group
    if group.status == QuotaHoldGroup.Status.SETTLED:
        raise QuotaHoldStateConflict
    remaining_group = group.requested_amount - group.consumed_amount - group.released_amount
    if amount > remaining_group:
        raise QuotaHoldStateConflict

    remaining = amount
    first = True
    for hold in allocations:
        allocation_remaining = hold.requested_amount - hold.consumed_amount - hold.released_amount
        settled = min(allocation_remaining, remaining)
        if settled <= 0:
            continue
        account = accounts[hold.account_id]
        if first:
            allocation_digests = client_digests
            first = False
        else:
            allocation_digests = system_idempotency_digests(
                operation=f"{action}_allocation",
                user_id=group.user_id,
                account_id=account.pk,
                business_type=group.business_type,
                business_id=group.business_id,
                request_payload={
                    "group_id": str(group.pk),
                    "hold_id": str(hold.pk),
                    "amount": settled,
                    "group_request_digest": client_digests.request_digest,
                },
            )
        settlement_entry, _ = _append_ledger_locked(
            account=account,
            hold=hold,
            action=action,
            available_delta=settled if action == QuotaLedgerEntry.Action.RELEASE else 0,
            frozen_delta=-settled,
            digests=allocation_digests,
            business_type=group.business_type,
            business_id=group.business_id,
            safe_reason="业务额度返还。" if action == "release" else "业务额度扣除。",
            actor=None,
            request_id=request_id,
        )
        if action == QuotaLedgerEntry.Action.RELEASE:
            late_action = None
            business_type = ""
            business_id = None
            moment = timezone.now()
            expiry_disposition = (
                QuotaExpiryDisposition.objects.filter(account=account).only("policy").first()
            )
            if (
                expiry_disposition is not None
                and expiry_disposition.policy == QuotaExpiryDisposition.Policy.ZERO
            ):
                late_action = QuotaLedgerEntry.Action.EXPIRY_LATE_RELEASE_FORFEIT
                business_type = "subscription_expiry"
                business_id = account.subscription_id
            elif expiry_disposition is None and (
                account.batch_type == QuotaAccount.BatchType.PRIMARY
                and account.cycle_ends_at is not None
                and account.cycle_ends_at <= moment
            ):
                late_action = QuotaLedgerEntry.Action.CYCLE_LATE_RELEASE_FORFEIT
                business_type = "quota_cycle_reset"
                business_id = account.pk
            if late_action is not None:
                late_digests = system_idempotency_digests(
                    operation=late_action,
                    user_id=account.user_id,
                    account_id=account.pk,
                    business_type=business_type,
                    business_id=business_id,
                    request_payload={
                        "settlement_entry_id": str(settlement_entry.pk),
                        "amount": settled,
                    },
                )
                _append_ledger_locked(
                    account=account,
                    action=late_action,
                    available_delta=-settled,
                    frozen_delta=0,
                    digests=late_digests,
                    business_type=business_type,
                    business_id=business_id,
                    safe_reason="Late release into an unavailable quota batch.",
                    actor=None,
                    request_id=request_id,
                )
        if action == QuotaLedgerEntry.Action.CONSUME:
            hold.consumed_amount += settled
        else:
            hold.released_amount += settled
        allocation_total = hold.consumed_amount + hold.released_amount
        hold.status = (
            QuotaHold.Status.SETTLED
            if allocation_total == hold.requested_amount
            else QuotaHold.Status.PARTIALLY_SETTLED
        )
        hold.settled_at = timezone.now() if hold.status == QuotaHold.Status.SETTLED else None
        hold.version += 1
        hold.save(
            update_fields=[
                "consumed_amount",
                "released_amount",
                "status",
                "settled_at",
                "version",
                "updated_at",
            ]
        )
        remaining -= settled
        if remaining == 0:
            break
    if remaining != 0:
        raise QuotaHoldStateConflict
    if action == QuotaLedgerEntry.Action.CONSUME:
        group.consumed_amount += amount
    else:
        group.released_amount += amount
    group_total = group.consumed_amount + group.released_amount
    group.status = (
        QuotaHoldGroup.Status.SETTLED
        if group_total == group.requested_amount
        else QuotaHoldGroup.Status.PARTIALLY_SETTLED
    )
    group.settled_at = timezone.now() if group.status == QuotaHoldGroup.Status.SETTLED else None
    group.version += 1
    group.save(
        update_fields=[
            "consumed_amount",
            "released_amount",
            "status",
            "settled_at",
            "version",
            "updated_at",
        ]
    )
    return group
