import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import (
    DatabaseError,
    OperationalError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.models import ApprovalRequest, AuditEvent, CustomerAssignment
from apps.admin_rbac.permissions import resolve_admin_context
from apps.plans import lifecycle as plan_lifecycle
from apps.plans.change_idempotency import derive_plan_change_digests
from apps.plans.change_services import cancel_scheduled_change
from apps.plans.lifecycle import (
    RENEWAL_CONFIRMATION_INVALID,
    RENEWAL_DIGEST_MISMATCH,
    RENEWAL_PLAN_ARCHIVED,
    execute_due_renewal,
    expire_subscription,
)
from apps.plans.models import (
    Plan,
    PlanVersion,
    Subscription,
    SubscriptionChange,
    SubscriptionChangeEvent,
    SubscriptionEvent,
)
from apps.plans.subscription_services import terminate_subscription
from apps.plans.tasks import execute_renewal, scan_due_renewals
from apps.quotas import services as quota_services
from apps.quotas.exceptions import QuotaStateConflict
from apps.quotas.lifecycle import (
    advance_cycle_account,
    due_cycle_account_ids,
    next_cycle_boundary,
)
from apps.quotas.models import (
    QuotaAccount,
    QuotaCycleReset,
    QuotaExpiryDisposition,
    QuotaLedgerEntry,
)
from apps.quotas.services import freeze_quota, release_hold
from apps.users.models import Notification
from tests.admin_session_helpers import authenticate_admin_client
from tests.test_cycle_reset import approved_renewal
from tests.test_cycle_reset_postgres import grant_one
from tests.test_plan_changes import activate_formal, admin, customer
from tests.test_subscriptions import PASSWORD

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


def parallel(*operations):
    barrier = threading.Barrier(len(operations))

    def run(operation):
        close_old_connections()
        barrier.wait()
        try:
            return operation()
        except Exception as exc:
            return exc
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        futures = [pool.submit(run, operation) for operation in operations]
        return [future.result(timeout=30) for future in futures]


def cancel_digests(actor, change, reason):
    return derive_plan_change_digests(
        f"cycle-cancel-{uuid.uuid4()}",
        operation="subscription.change.cancel",
        requester_id=actor.pk,
        target_id=change.pk,
        request_payload={"reason": reason},
    )


def _raise_late_failure(monkeypatch, failure_point):
    if failure_point == "ledger":
        monkeypatch.setattr(
            quota_services,
            "_append_ledger_locked",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("ledger failure")),
        )
    elif failure_point == "event":
        monkeypatch.setattr(
            plan_lifecycle,
            "_change_event",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("event failure")),
        )
    elif failure_point == "notification":
        original = Notification.objects.create

        def create_notification(**kwargs):
            if (
                kwargs.get("notification_type")
                == Notification.NotificationType.SUBSCRIPTION_RENEWED
            ):
                raise RuntimeError("notification failure")
            return original(**kwargs)

        monkeypatch.setattr(Notification.objects, "create", create_notification)
    else:
        original_audit = plan_lifecycle._audit

        def create_audit(**kwargs):
            if kwargs.get("action_key") == "subscription.renewal.execute":
                raise RuntimeError("audit failure")
            return original_audit(**kwargs)

        monkeypatch.setattr(plan_lifecycle, "_audit", create_audit)


@pytest.mark.parametrize("failure_point", ["ledger", "event", "notification", "audit"])
def test_renewal_late_failure_rolls_back_source_expiry_and_all_successor_facts(
    monkeypatch, failure_point
):
    source, change = approved_renewal(valid_days=180)
    baseline = {
        "subscriptions": Subscription.objects.filter(user=source.user).count(),
        "subscription_events": SubscriptionEvent.objects.count(),
        "change_events": SubscriptionChangeEvent.objects.count(),
        "notifications": Notification.objects.count(),
        "audits": AuditEvent.objects.count(),
        "accounts": QuotaAccount.objects.count(),
        "ledger": QuotaLedgerEntry.objects.count(),
        "resets": QuotaCycleReset.objects.count(),
    }
    _raise_late_failure(monkeypatch, failure_point)
    with pytest.raises(RuntimeError):
        execute_due_renewal(
            change_id=change.pk,
            request_id=uuid.uuid4(),
            now=change.effective_at + timedelta(days=65),
        )
    source.refresh_from_db()
    change.refresh_from_db()
    assert source.status == Subscription.Status.ACTIVE
    assert source.expired_at is None
    assert change.status == SubscriptionChange.Status.SCHEDULED
    assert not hasattr(change, "target_subscription")
    assert Subscription.objects.filter(user=source.user).count() == baseline["subscriptions"]
    assert SubscriptionEvent.objects.count() == baseline["subscription_events"]
    assert SubscriptionChangeEvent.objects.count() == baseline["change_events"]
    assert Notification.objects.count() == baseline["notifications"]
    assert AuditEvent.objects.count() == baseline["audits"]
    assert QuotaAccount.objects.count() == baseline["accounts"]
    assert QuotaLedgerEntry.objects.count() == baseline["ledger"]
    assert QuotaCycleReset.objects.count() == baseline["resets"]


def test_worker_redelivery_after_commit_is_exactly_once_for_all_renewal_facts():
    source, change = approved_renewal(valid_days=180)
    moment = change.effective_at + timedelta(days=65)
    execute_due_renewal(change_id=change.pk, request_id=uuid.uuid4(), now=moment)
    counts = {
        "subscriptions": Subscription.objects.filter(user=source.user).count(),
        "subscription_events": SubscriptionEvent.objects.count(),
        "change_events": SubscriptionChangeEvent.objects.count(),
        "notifications": Notification.objects.count(),
        "audits": AuditEvent.objects.count(),
        "accounts": QuotaAccount.objects.count(),
        "ledger": QuotaLedgerEntry.objects.count(),
        "resets": QuotaCycleReset.objects.count(),
    }
    execute_due_renewal(change_id=change.pk, request_id=uuid.uuid4(), now=moment)
    assert Subscription.objects.filter(user=source.user).count() == counts["subscriptions"]
    assert SubscriptionEvent.objects.count() == counts["subscription_events"]
    assert SubscriptionChangeEvent.objects.count() == counts["change_events"]
    assert Notification.objects.count() == counts["notifications"]
    assert AuditEvent.objects.count() == counts["audits"]
    assert QuotaAccount.objects.count() == counts["accounts"]
    assert QuotaLedgerEntry.objects.count() == counts["ledger"]
    assert QuotaCycleReset.objects.count() == counts["resets"]
    assert (
        SubscriptionEvent.objects.filter(
            subscription=source, event_type=SubscriptionEvent.EventType.EXPIRED
        ).count()
        == 1
    )


def test_renewal_and_expiry_race_is_exactly_once():
    source, change = approved_renewal(valid_days=180)
    moment = change.effective_at + timedelta(days=1)
    results = parallel(
        lambda: execute_due_renewal(change_id=change.pk, request_id=uuid.uuid4(), now=moment),
        lambda: expire_subscription(subscription_id=source.pk, request_id=uuid.uuid4(), now=moment),
    )
    assert not [result for result in results if isinstance(result, Exception)]
    source.refresh_from_db()
    change.refresh_from_db()
    assert source.status == Subscription.Status.EXPIRED
    assert change.status == SubscriptionChange.Status.EXECUTED
    assert (
        SubscriptionEvent.objects.filter(
            subscription=source, event_type=SubscriptionEvent.EventType.EXPIRED
        ).count()
        == 1
    )
    assert Subscription.objects.filter(source_change=change).count() == 1


def test_expiry_and_termination_race_has_one_terminal_winner():
    source, _change = approved_renewal()
    actor_id = source.opened_by_id
    expected_version = source.version
    moment = source.ends_at + timedelta(seconds=1)

    def terminate():
        actor = type(source.opened_by).objects.get(pk=actor_id)
        return terminate_subscription(
            requester=actor,
            admin_context=resolve_admin_context(actor),
            subscription_id=source.pk,
            expected_version=expected_version,
            reason="expiry terminate race",
            request_id=uuid.uuid4(),
        )

    results = parallel(
        lambda: expire_subscription(subscription_id=source.pk, request_id=uuid.uuid4(), now=moment),
        terminate,
    )
    source.refresh_from_db()
    assert source.status in {Subscription.Status.EXPIRED, Subscription.Status.TERMINATED}
    terminal_events = SubscriptionEvent.objects.filter(
        subscription=source,
        event_type__in=(
            SubscriptionEvent.EventType.EXPIRED,
            SubscriptionEvent.EventType.TERMINATED,
        ),
    )
    assert terminal_events.count() == 1
    assert len([result for result in results if not isinstance(result, Exception)]) == 1


def test_renewal_and_cancel_race_has_one_terminal_winner():
    source, change = approved_renewal()
    actor_id = source.opened_by_id
    expected_version = change.version
    reason = "renewal cancel race"
    digests = cancel_digests(source.opened_by, change, reason)

    def cancel():
        actor = type(source.opened_by).objects.get(pk=actor_id)
        return cancel_scheduled_change(
            requester=actor,
            admin_context=resolve_admin_context(actor),
            change_id=change.pk,
            expected_version=expected_version,
            reason=reason,
            digests=digests,
            request_id=uuid.uuid4(),
        )

    parallel(
        lambda: execute_due_renewal(
            change_id=change.pk,
            request_id=uuid.uuid4(),
            now=change.effective_at + timedelta(seconds=1),
        ),
        cancel,
    )
    change.refresh_from_db()
    assert change.status in {
        SubscriptionChange.Status.EXECUTED,
        SubscriptionChange.Status.CANCELLED,
    }
    assert (
        SubscriptionChangeEvent.objects.filter(
            change=change,
            event_type__in=(
                SubscriptionChangeEvent.EventType.EXECUTED,
                SubscriptionChangeEvent.EventType.CANCELLED,
            ),
        ).count()
        == 1
    )


@pytest.mark.parametrize(
    "anchor,boundary,expected",
    [
        (28, datetime(2024, 1, 28, 9, 30), datetime(2024, 2, 28, 9, 30)),
        (29, datetime(2024, 1, 29, 9, 30), datetime(2024, 2, 29, 9, 30)),
        (30, datetime(2024, 1, 30, 9, 30), datetime(2024, 2, 29, 9, 30)),
        (31, datetime(2024, 1, 31, 9, 30), datetime(2024, 2, 29, 9, 30)),
        (31, datetime(2024, 12, 31, 9, 30), datetime(2025, 1, 31, 9, 30)),
    ],
)
def test_month_end_anchor_leap_year_and_cross_year_are_deterministic(anchor, boundary, expected):
    shanghai = ZoneInfo("Asia/Shanghai")
    subscription = SimpleNamespace(
        cycle_anchor_day=anchor,
        cycle_anchor_time=time(9, 30),
        ends_at=datetime(2026, 1, 1, tzinfo=shanghai),
    )
    assert next_cycle_boundary(subscription, boundary.replace(tzinfo=shanghai)) == expected.replace(
        tzinfo=shanghai
    )


def test_broker_enqueue_failure_creates_no_postgresql_lifecycle_fact(monkeypatch):
    source, change = approved_renewal()
    before = (
        source.status,
        change.status,
        SubscriptionEvent.objects.count(),
        SubscriptionChangeEvent.objects.count(),
        QuotaCycleReset.objects.count(),
    )
    monkeypatch.setattr(
        "apps.plans.tasks.execute_renewal.apply_async",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OperationalError("broker unavailable")),
    )
    with patch("apps.plans.lifecycle.timezone.now", return_value=change.effective_at):
        with pytest.raises(OperationalError):
            scan_due_renewals()
    source.refresh_from_db()
    change.refresh_from_db()
    assert (
        source.status,
        change.status,
        SubscriptionEvent.objects.count(),
        SubscriptionChangeEvent.objects.count(),
        QuotaCycleReset.objects.count(),
    ) == before


def approved_unavailable_renewal(kind):
    requester = admin()
    approver = admin("13700137031")
    user = customer()
    source, plan, version = activate_formal(
        requester,
        user,
        code=f"renewal-confirmed-{kind}",
        valid_days=180,
    )
    if kind == "offline":
        Plan.objects.filter(pk=plan.pk).update(status=Plan.Status.OFFLINE)
    else:
        PlanVersion.objects.filter(pk=version.pk).update(status=PlanVersion.Status.RETIRED)
    submitted = authenticate_admin_client(APIClient(), requester).post(
        f"/api/v1/admin/subscriptions/{source.pk}/change",
        {
            "expected_version": source.version,
            "target_plan_version_id": str(version.pk),
            "change_type": "renewal",
            "quota_policy": "retain",
            "confirm_unavailable": True,
            "unavailable_reason": "approved unavailable target",
            "reason": "scheduled renewal with explicit confirmation",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"confirmed-{kind}-renewal-0115",
    )
    assert submitted.status_code == 202
    approval = ApprovalRequest.objects.get(pk=submitted.json()["data"]["approval_id"])
    approved = authenticate_admin_client(APIClient(), approver, "198.51.100.116").post(
        f"/api/v1/admin/approvals/{approval.pk}/approve",
        {"current_password": PASSWORD},
        format="json",
        REMOTE_ADDR="198.51.100.116",
    )
    assert approved.status_code == 200
    return source, SubscriptionChange.objects.get(source_approval=approval)


@pytest.mark.parametrize(
    "failure_kind,expected_code",
    [
        ("archived", RENEWAL_PLAN_ARCHIVED),
        ("offline", RENEWAL_CONFIRMATION_INVALID),
        ("retired", RENEWAL_CONFIRMATION_INVALID),
        ("digest", RENEWAL_DIGEST_MISMATCH),
    ],
)
def test_permanent_target_and_digest_failures_are_terminal_and_apply_final_expiry(
    monkeypatch, failure_kind, expected_code
):
    source, change = approved_renewal()
    if failure_kind == "archived":
        Plan.objects.filter(pk=change.target_plan_id).update(status=Plan.Status.ARCHIVED)
    elif failure_kind == "offline":
        Plan.objects.filter(pk=change.target_plan_id).update(status=Plan.Status.OFFLINE)
    elif failure_kind == "retired":
        PlanVersion.objects.filter(pk=change.target_plan_version_id).update(
            status=PlanVersion.Status.RETIRED
        )
    else:
        original = plan_lifecycle.canonical_payload

        def corrupt_digest(*args, **kwargs):
            payload, _digest = original(*args, **kwargs)
            return payload, "0" * 64

        monkeypatch.setattr(plan_lifecycle, "canonical_payload", corrupt_digest)
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=change.effective_at + timedelta(seconds=1),
    )
    source.refresh_from_db()
    change.refresh_from_db()
    assert source.status == Subscription.Status.EXPIRED
    assert change.status == SubscriptionChange.Status.FAILED
    assert change.stable_error_code == expected_code
    assert QuotaExpiryDisposition.objects.filter(subscription=source).exists()
    with pytest.raises(DatabaseError), transaction.atomic():
        SubscriptionChange.objects.filter(pk=change.pk).update(
            status=SubscriptionChange.Status.SCHEDULED,
            failed_at=None,
            stable_error_code="",
            next_attempt_at=change.effective_at,
        )


@pytest.mark.parametrize("kind", ["offline", "retired"])
def test_approved_unavailable_confirmation_survives_until_scheduled_execution(kind):
    source, change = approved_unavailable_renewal(kind)
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=change.effective_at + timedelta(seconds=1),
    )
    source.refresh_from_db()
    change.refresh_from_db()
    assert source.status == Subscription.Status.EXPIRED
    assert change.status == SubscriptionChange.Status.EXECUTED
    assert Subscription.objects.filter(source_change=change).count() == 1


def test_scheduled_execution_ignores_later_requester_approver_and_scope_changes():
    source, change = approved_renewal(valid_days=180)
    approval = change.source_approval
    CustomerAssignment.objects.create(
        customer=source.user,
        owner_admin=approval.requester.admin_profile,
        assigned_by=approval.requester,
        assigned_at=timezone.now(),
    )
    CustomerAssignment.objects.filter(customer=source.user).update(
        owner_admin=None,
        version=2,
    )
    type(approval.requester).objects.filter(
        pk__in=(approval.requester_id, approval.approved_by_id)
    ).update(is_staff=False, is_superuser=False)
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=change.effective_at + timedelta(seconds=1),
    )
    change.refresh_from_db()
    audit = AuditEvent.objects.get(
        action_key="subscription.renewal.execute",
        target_id=str(change.pk),
        outcome="executed",
    )
    assert change.status == SubscriptionChange.Status.EXECUTED
    assert audit.actor is None
    assert audit.approval_request_id == approval.pk
    assert audit.requester_id == approval.requester_id
    assert audit.approver_id == approval.approved_by_id


def test_cancelled_renewal_allows_final_expiry_disposition():
    source, change = approved_renewal()
    actor = source.opened_by
    reason = "cancel before effective boundary"
    cancel_scheduled_change(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        change_id=change.pk,
        expected_version=change.version,
        reason=reason,
        digests=cancel_digests(actor, change, reason),
        request_id=uuid.uuid4(),
    )
    expire_subscription(
        subscription_id=source.pk,
        request_id=uuid.uuid4(),
        now=source.ends_at + timedelta(seconds=1),
    )
    source.refresh_from_db()
    assert source.status == Subscription.Status.EXPIRED
    assert QuotaExpiryDisposition.objects.filter(subscription=source).count() == (
        source.quota_accounts.count()
    )


def test_scheduled_renewal_defers_final_expiry_disposition_while_blocked():
    source, change = approved_renewal()
    account = QuotaAccount.objects.get(subscription=source, quota_type="detection_points")
    grant_one(source.opened_by, account)
    freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="defer_expiry_policy",
        business_id=uuid.uuid4(),
        idempotency_key="defer-expiry-policy-hold-key-0115",
        request_id=uuid.uuid4(),
    )
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=change.effective_at + timedelta(seconds=1),
    )
    change.refresh_from_db()
    assert change.status == SubscriptionChange.Status.SCHEDULED
    assert not QuotaExpiryDisposition.objects.filter(subscription=source).exists()


def test_final_zero_expiry_late_release_uses_expiry_forfeit_not_cycle_forfeit():
    source, change = approved_renewal()
    actor = source.opened_by
    reason = "cancel before final expiry"
    cancel_scheduled_change(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        change_id=change.pk,
        expected_version=change.version,
        reason=reason,
        digests=cancel_digests(actor, change, reason),
        request_id=uuid.uuid4(),
    )
    account = QuotaAccount.objects.get(subscription=source, quota_type="detection_points")
    grant_one(actor, account)
    group = freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="expiry_late_release",
        business_id=uuid.uuid4(),
        idempotency_key="expiry-late-release-hold-key-0115",
        request_id=uuid.uuid4(),
    )
    expire_subscription(
        subscription_id=source.pk,
        request_id=uuid.uuid4(),
        now=source.ends_at + timedelta(seconds=1),
    )
    with patch(
        "apps.quotas.services.timezone.now",
        return_value=source.ends_at + timedelta(seconds=2),
    ):
        release_hold(
            hold_id=group.pk,
            amount=1,
            idempotency_key="expiry-late-release-settle-key-0115",
            request_id=uuid.uuid4(),
        )
    actions = list(account.ledger_entries.order_by("sequence").values_list("action", flat=True))
    assert actions[-2:] == [
        QuotaLedgerEntry.Action.RELEASE,
        QuotaLedgerEntry.Action.EXPIRY_LATE_RELEASE_FORFEIT,
    ]
    assert QuotaLedgerEntry.Action.CYCLE_LATE_RELEASE_FORFEIT not in actions[-2:]


def test_carryover_batch_is_never_selected_for_monthly_reset():
    _source, change = approved_renewal(valid_days=180)
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=change.effective_at + timedelta(seconds=1),
    )
    change.refresh_from_db()
    target = change.target_subscription
    source_account = QuotaAccount.objects.get(
        subscription=target,
        quota_type="assistant_messages",
        batch_type=QuotaAccount.BatchType.PRIMARY,
    )
    with transaction.atomic():
        carryover = quota_services._create_carryover_account(
            change=change,
            source_account=source_account,
            target_subscription=target,
            spendable_until=target.ends_at,
        )
    assert carryover.pk not in due_cycle_account_ids(now=carryover.cycle_ends_at)
    with pytest.raises(QuotaStateConflict):
        advance_cycle_account(
            account_id=carryover.pk,
            request_id=uuid.uuid4(),
            now=carryover.cycle_ends_at,
        )


def test_cycle_windows_use_half_open_boundaries():
    _source, change = approved_renewal(valid_days=180)
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=change.effective_at + timedelta(seconds=1),
    )
    target = SubscriptionChange.objects.get(pk=change.pk).target_subscription
    account = QuotaAccount.objects.get(
        subscription=target,
        quota_type="assistant_messages",
        batch_type=QuotaAccount.BatchType.PRIMARY,
    )
    assert account.cycle_started_at <= target.starts_at < account.cycle_ends_at
    reset = advance_cycle_account(
        account_id=account.pk,
        request_id=uuid.uuid4(),
        now=account.cycle_ends_at,
    )
    assert reset.previous_account.cycle_ends_at == reset.boundary
    assert reset.next_account.cycle_started_at == reset.boundary
    assert not (
        reset.previous_account.cycle_started_at
        <= reset.boundary
        < reset.previous_account.cycle_ends_at
    )
    assert reset.next_account.cycle_started_at <= reset.boundary < reset.next_account.cycle_ends_at


def test_permanent_domain_failure_does_not_request_celery_retry():
    _source, change = approved_renewal()
    Plan.objects.filter(pk=change.target_plan_id).update(status=Plan.Status.ARCHIVED)
    with (
        patch(
            "apps.plans.lifecycle.timezone.now",
            return_value=change.effective_at + timedelta(seconds=1),
        ),
        patch.object(execute_renewal, "retry") as retry,
    ):
        result = execute_renewal.apply(args=[str(change.pk)], throw=True)
    change.refresh_from_db()
    assert result.successful()
    assert result.get() == {"processed": True}
    assert change.status == SubscriptionChange.Status.FAILED
    assert change.stable_error_code == RENEWAL_PLAN_ARCHIVED
    retry.assert_not_called()
    assert execute_renewal.max_retries == 5
