import calendar
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
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
from .models import QuotaAccount, QuotaHold, QuotaLedgerEntry
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
def freeze_quota(
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


def _settle_hold(*, hold_id, amount, action: str, idempotency_key: str, request_id) -> QuotaHold:
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
