import copy
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from django_redis import get_redis_connection

from apps.admin_rbac.permissions import resolve_admin_context
from apps.plans.lifecycle import (
    RENEWAL_BLOCKED_BY_HOLD,
    RENEWAL_SOURCE_TERMINATED,
    RENEWAL_WINDOW_ELAPSED,
    execute_due_renewal,
    expire_subscription,
)
from apps.plans.models import Subscription, SubscriptionChange, SubscriptionEvent
from apps.plans.subscription_services import (
    _create_active_subscription,
    terminate_subscription,
)
from apps.quotas.idempotency import derive_idempotency_digests
from apps.quotas.lifecycle import advance_cycle_account
from apps.quotas.models import (
    QuotaAccount,
    QuotaCycleReset,
    QuotaExpiryDisposition,
    QuotaLedgerEntry,
)
from apps.quotas.services import adjust_quota_account, freeze_quota, release_hold
from tests.test_cycle_reset import approved_renewal
from tests.test_plan_changes import activate_formal, admin, customer
from tests.test_subscriptions import application_for, published_plan

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_services():
    if connection.vendor != "postgresql":
        pytest.skip("Run through scripts/test-cycle-reset.* with PostgreSQL and Redis.")
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


def grant_one(actor, account):
    digests = derive_idempotency_digests(
        f"cycle-grant-{uuid.uuid4()}",
        operation="grant",
        user_id=account.user_id,
        account_id=account.pk,
        business_type="quota_adjustment",
        business_id=account.pk,
        request_payload={"amount": 1, "reason": "lifecycle test funding"},
    )
    return adjust_quota_account(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        account_id=account.pk,
        expected_version=account.version,
        action="grant",
        amount=1,
        reason="lifecycle test funding",
        digests=digests,
        request_id=uuid.uuid4(),
    )


def cycle_subscription():
    actor, user = admin(), customer()
    started = datetime(2026, 1, 31, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    with patch("apps.plans.subscription_services.timezone.now", return_value=started):
        source, _, _ = activate_formal(actor, user, code=f"cycle-{uuid.uuid4().hex[:8]}")
    account = QuotaAccount.objects.get(subscription=source, quota_type="assistant_messages")
    return actor, source, account


@pytest.mark.django_db(transaction=True)
def test_lifecycle_triggers_are_installed():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(%s)",
            [
                [
                    "plans_renewal_approval_binding",
                    "quota_cycle_reset_append_only",
                    "quota_expiry_disposition_append_only",
                    "quota_cycle_reset_consistency",
                    "quota_expiry_disposition_consistency",
                ]
            ],
        )
        names = {row[0] for row in cursor.fetchall()}
    assert names == {
        "plans_renewal_approval_binding",
        "quota_cycle_reset_append_only",
        "quota_expiry_disposition_append_only",
        "quota_cycle_reset_consistency",
        "quota_expiry_disposition_consistency",
    }


def test_blocked_expired_source_executes_after_hold_settlement_and_admin_change():
    source, change = approved_renewal()
    actor = source.opened_by
    account = QuotaAccount.objects.get(subscription=source, quota_type="detection_points")
    grant_one(actor, account)
    group = freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="renewal_pg",
        business_id=uuid.uuid4(),
        idempotency_key="renewal-pg-hold-key-0001",
        request_id=uuid.uuid4(),
    )
    due = source.ends_at + timedelta(seconds=1)
    execute_due_renewal(change_id=change.pk, request_id=uuid.uuid4(), now=due)
    source.refresh_from_db()
    change.refresh_from_db()
    assert source.status == Subscription.Status.EXPIRED
    assert change.status == SubscriptionChange.Status.SCHEDULED
    assert change.stable_error_code == RENEWAL_BLOCKED_BY_HOLD
    approval = change.source_approval
    approval.requester.is_staff = False
    approval.requester.save(update_fields=["is_staff"])
    release_hold(
        hold_id=group.pk,
        amount=1,
        idempotency_key="renewal-pg-release-key-0001",
        request_id=uuid.uuid4(),
    )
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=change.next_attempt_at + timedelta(seconds=1),
    )
    change.refresh_from_db()
    source.refresh_from_db()
    target = change.target_subscription
    assert change.status == SubscriptionChange.Status.EXECUTED
    assert source.status == Subscription.Status.EXPIRED
    assert target.starts_at == change.effective_at
    assert target.cycle_anchor_time == source.cycle_anchor_time
    assert SubscriptionEvent.objects.filter(subscription=source, event_type="expired").count() == 1


def test_terminated_source_fails_without_creating_successor():
    source, change = approved_renewal()
    terminate_subscription(
        requester=source.opened_by,
        admin_context=resolve_admin_context(source.opened_by),
        subscription_id=source.pk,
        expected_version=source.version,
        reason="terminate before renewal",
        request_id=uuid.uuid4(),
    )
    execute_due_renewal(
        change_id=change.pk, request_id=uuid.uuid4(), now=source.ends_at + timedelta(seconds=1)
    )
    change.refresh_from_db()
    assert change.status == SubscriptionChange.Status.FAILED
    assert change.stable_error_code == RENEWAL_SOURCE_TERMINATED
    assert not hasattr(change, "target_subscription")


def test_elapsed_renewal_window_is_permanent_and_terminal():
    source, change = approved_renewal()
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=change.effective_at + timedelta(days=4000),
    )
    change.refresh_from_db()
    assert change.status == SubscriptionChange.Status.FAILED
    assert change.stable_error_code == RENEWAL_WINDOW_ELAPSED
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subscription_changes SET status='scheduled', failed_at=NULL, "
                "stable_error_code='', next_attempt_at=effective_at WHERE id=%s",
                [change.pk],
            )


def test_delayed_renewal_catches_up_monthly_cycles_before_execution_completes():
    source, change = approved_renewal(valid_days=180)
    executed_at = change.effective_at + timedelta(days=95)
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=executed_at,
    )
    change.refresh_from_db()
    target = change.target_subscription
    current = (
        QuotaAccount.objects.filter(
            subscription=target,
            quota_type="assistant_messages",
            batch_type=QuotaAccount.BatchType.PRIMARY,
            cycle_started_at__lte=executed_at,
            cycle_ends_at__gt=executed_at,
        )
        .order_by("cycle_started_at")
        .get()
    )
    resets = list(
        QuotaCycleReset.objects.filter(
            subscription=target,
            quota_type="assistant_messages",
        ).order_by("boundary")
    )
    assert change.status == SubscriptionChange.Status.EXECUTED
    assert len(resets) >= 3
    assert resets[0].previous_account.cycle_started_at == target.starts_at
    assert all(
        previous.next_account_id == following.previous_account_id
        for previous, following in zip(resets, resets[1:], strict=False)
    )
    assert resets[-1].next_account_id == current.pk
    assert current.cycle_started_at <= executed_at < current.cycle_ends_at


def test_cycle_reset_is_exactly_once_contiguous_and_immutable():
    _, source, account = cycle_subscription()
    due = account.cycle_ends_at + timedelta(seconds=1)
    first = advance_cycle_account(account_id=account.pk, request_id=uuid.uuid4(), now=due)
    second = advance_cycle_account(account_id=account.pk, request_id=uuid.uuid4(), now=due)
    assert first.pk == second.pk
    assert QuotaCycleReset.objects.filter(previous_account=account).count() == 1
    assert first.next_account.cycle_started_at == account.cycle_ends_at
    assert first.next_account.cycle_ends_at <= source.ends_at
    assert first.initialize_entry.account_id == first.next_account_id
    assert first.initialize_entry.sequence == 1
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quota_cycle_resets SET boundary=boundary + interval '1 second' WHERE id=%s",
                [first.pk],
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM quota_cycle_resets WHERE id=%s", [first.pk])


def test_late_release_is_forfeited_in_same_cycle_account():
    actor, _, account = cycle_subscription()
    active_time = account.cycle_started_at + timedelta(days=1)
    with patch("apps.quotas.services.timezone.now", return_value=active_time):
        grant_one(actor, account)
        group = freeze_quota(
            account_id=account.pk,
            amount=1,
            business_type="cycle_late_release",
            business_id=uuid.uuid4(),
            idempotency_key="cycle-late-hold-key-0001",
            request_id=uuid.uuid4(),
        )
    due = account.cycle_ends_at + timedelta(seconds=1)
    advance_cycle_account(account_id=account.pk, request_id=uuid.uuid4(), now=due)
    with patch("apps.quotas.services.timezone.now", return_value=due):
        release_hold(
            hold_id=group.pk,
            amount=1,
            idempotency_key="cycle-late-release-key-0001",
            request_id=uuid.uuid4(),
        )
    account.refresh_from_db()
    assert account.available == 0
    assert account.frozen == 0
    actions = list(account.ledger_entries.order_by("sequence").values_list("action", flat=True))
    assert actions[-2:] == ["release", "cycle_late_release_forfeit"]


@pytest.mark.parametrize("policy,expected_available", [("zero", 0), ("freeze", 1), ("retain", 1)])
def test_final_expiry_policy_is_evidenced(policy, expected_available):
    actor, user = admin(), customer()
    plan, version = published_plan(actor, code=f"expiry-{policy}")
    application = application_for(user, plan, version)
    now = timezone.now()
    snapshot = copy.deepcopy(version.effective_config)
    snapshot["limits"]["expiry_quota_policy"] = {"detection_points": policy}
    source = Subscription.objects.create(
        user=user,
        source_application=application,
        source_type=Subscription.SourceType.APPLICATION,
        plan=plan,
        plan_version=version,
        plan_version_no=version.version_no,
        entitlement_snapshot=snapshot,
        entitlement_digest=version.config_digest,
        status=Subscription.Status.ACTIVE,
        starts_at=now,
        ends_at=now + timedelta(days=1),
        cycle_anchor_day=timezone.localtime(now).day,
        cycle_anchor_time=timezone.localtime(now).timetz().replace(tzinfo=None),
        is_trial=False,
        opened_by=actor,
        opening_note="expiry policy test",
        activated_at=now,
        request_id=uuid.uuid4(),
    )
    from apps.quotas.services import initialize_subscription_accounts

    initialize_subscription_accounts(subscription=source, request_id=uuid.uuid4(), actor=actor)
    account = QuotaAccount.objects.get(subscription=source, quota_type="detection_points")
    grant_one(actor, account)
    expire_subscription(
        subscription_id=source.pk,
        request_id=uuid.uuid4(),
        now=source.ends_at + timedelta(seconds=1),
    )
    account.refresh_from_db()
    disposition = QuotaExpiryDisposition.objects.get(account=account)
    assert disposition.policy == policy
    assert account.available == expected_available
    if policy == "zero":
        assert disposition.ledger_entry.action == QuotaLedgerEntry.Action.EXPIRY_FORFEIT


def test_boundary_equal_subscription_end_does_not_create_next_batch():
    actor, user = admin(), customer()
    plan, version = published_plan(actor, code="boundary-end")
    application = application_for(user, plan, version)
    start = datetime(2026, 1, 31, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    end = datetime(2026, 2, 28, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    source = _create_active_subscription(
        user=user,
        application=application,
        plan=plan,
        version=version,
        actor=actor,
        opening_note="boundary test",
        request_id=uuid.uuid4(),
        now=start,
        ends_at=end,
        cycle_anchor_day=31,
        cycle_anchor_time=start.timetz().replace(tzinfo=None),
    )
    account = QuotaAccount.objects.get(subscription=source, quota_type="assistant_messages")
    assert account.cycle_ends_at == source.ends_at
    assert (
        advance_cycle_account(
            account_id=account.pk, request_id=uuid.uuid4(), now=end + timedelta(seconds=1)
        )
        is None
    )
    assert not QuotaCycleReset.objects.filter(previous_account=account).exists()
