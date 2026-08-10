import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import (
    DatabaseError,
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.models import ApprovalRequest, AuditEvent, RiskAction
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.risk_services import canonical_payload
from apps.plans.change_idempotency import derive_plan_change_digests
from apps.plans.change_services import (
    SubscriptionChangeAlreadyExists,
    SubscriptionChangeIdempotencyConflict,
    SubscriptionChangeStateConflict,
    cancel_scheduled_change,
    execute_subscription_change,
)
from apps.plans.models import (
    PlanLimit,
    PlanVersion,
    Subscription,
    SubscriptionChange,
    SubscriptionChangeEvent,
)
from apps.plans.services import create_plan_version, publish_plan_version
from apps.plans.subscription_services import activate_application, grant_trial
from apps.quotas import services as quota_services
from apps.quotas.idempotency import derive_idempotency_digests
from apps.quotas.models import (
    QuotaAccount,
    QuotaHold,
    QuotaHoldGroup,
    QuotaLedgerEntry,
    QuotaTransfer,
)
from apps.quotas.services import (
    adjust_quota_account,
    consume_hold,
    freeze_quota,
    release_hold,
)
from apps.users.models import Notification, User
from tests.admin_session_helpers import authenticate_admin_client
from tests.test_plan_changes import activate_formal, admin, customer
from tests.test_subscriptions import PASSWORD, application_for, published_plan

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_services():
    if connection.vendor != "postgresql":
        pytest.skip("仅通过 scripts/test-plan-changes.* 在真实 PostgreSQL/Redis 执行。")
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


@transaction.atomic
def change_operation(
    actor_id,
    source_id,
    target_plan_id,
    target_version_id,
    key,
    policy="overwrite",
    change_type="replacement",
    reason="专属套餐变更",
):
    actor = User.objects.get(pk=actor_id)
    source = Subscription.objects.get(pk=source_id)
    payload = {
        "target_plan_version_id": str(target_version_id),
        "change_type": change_type,
        "quota_policy": policy,
        "confirm_unavailable": False,
        "unavailable_reason": "",
        "reason": reason,
    }
    digests = derive_plan_change_digests(
        key,
        operation="subscription.change",
        requester_id=actor.pk,
        target_id=source.pk,
        request_payload=payload,
    )
    existing = SubscriptionChange.objects.filter(idempotency_key_digest=digests.key_digest).first()
    source_approval = existing.source_approval if existing is not None else None
    if change_type == "renewal" and source_approval is None:
        action = RiskAction.objects.get(pk="subscription.change")
        approver = (
            User.objects.filter(is_superuser=True).exclude(pk=actor.pk).order_by("pk").first()
        )
        if approver is None:
            approver = admin("13700137989")
        approval_payload = {
            **payload,
            "idempotency_key_version": digests.key_version,
            "idempotency_key_digest": digests.key_digest,
            "idempotency_scope_digest": digests.scope_digest,
            "request_digest": digests.request_digest,
        }
        safe_payload, payload_digest = canonical_payload(
            action.key,
            action.target_type,
            source.pk,
            source.version,
            approval_payload,
        )
        approved_at = timezone.now()
        source_approval = ApprovalRequest.objects.create(
            action=action,
            action_key=action.key,
            policy_version=action.policy.version,
            requester=actor,
            target_type=action.target_type,
            target_id=source.pk,
            target_version=source.version,
            sanitized_payload=safe_payload,
            payload_digest=payload_digest,
            safe_summary="Scheduled renewal test approval.",
            status=ApprovalRequest.Status.EXECUTED,
            expires_at=approved_at + timedelta(hours=1),
            approved_by=approver,
            approved_at=approved_at,
            executed_at=approved_at,
            request_id=uuid.uuid4(),
        )

    change = execute_subscription_change(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        source_subscription_id=source.pk,
        expected_version=source.version,
        target_plan_id=target_plan_id,
        target_plan_version_id=target_version_id,
        requested_type=change_type,
        quota_policy=policy,
        confirm_unavailable=False,
        unavailable_reason="",
        reason=payload["reason"],
        digests=digests,
        request_id=uuid.uuid4(),
        source_approval=source_approval,
    )
    if source_approval is not None and not source_approval.execution_result:
        source_approval.execution_result = {"change_id": str(change.pk)}
        source_approval.save(update_fields=["execution_result", "updated_at"])
    return change


def fund(actor, account, amount):
    digests = derive_idempotency_digests(
        f"postgres-plan-change-fund-{account.pk}",
        operation="grant",
        user_id=account.user_id,
        account_id=account.pk,
        business_type="quota_adjustment",
        business_id=account.pk,
        request_payload={"amount": amount, "reason": "专属测试"},
    )
    adjust_quota_account(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        account_id=account.pk,
        expected_version=account.version,
        action="grant",
        amount=amount,
        reason="专属测试",
        digests=digests,
        request_id=uuid.uuid4(),
    )


def test_postgresql_concurrent_change_is_exactly_once_and_single_successor():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="pg-concurrent-source")
    target_plan, target_version = published_plan(actor, code="pg-concurrent-target")
    results = parallel(
        lambda: change_operation(
            actor.pk, source.pk, target_plan.pk, target_version.pk, "pg-change-key-00000001"
        ),
        lambda: change_operation(
            actor.pk, source.pk, target_plan.pk, target_version.pk, "pg-change-key-00000002"
        ),
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert SubscriptionChange.objects.filter(from_subscription=source).count() == 1
    assert Subscription.objects.filter(user=user, source_type="plan_change").count() == 1


def test_postgresql_same_idempotency_key_concurrent_replay_is_one_change():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="pg-idem-source")
    target_plan, target_version = published_plan(actor, code="pg-idem-target")

    def operation():
        return change_operation(
            actor.pk, source.pk, target_plan.pk, target_version.pk, "pg-same-key-000000001"
        )

    results = parallel(operation, operation)
    assert all(not isinstance(result, Exception) for result in results)
    assert results[0].pk == results[1].pk
    assert SubscriptionChange.objects.filter(from_subscription=source).count() == 1


def test_postgresql_raw_sql_guards_change_source_terminal_and_events():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="pg-guard-source")
    target_plan, target_version = published_plan(actor, code="pg-guard-target")
    change = change_operation(
        actor.pk, source.pk, target_plan.pk, target_version.pk, "pg-guard-key-000000001"
    )
    event = SubscriptionChangeEvent.objects.get(change=change, event_type="executed")
    target = change.target_subscription
    statements = (
        ("DELETE FROM subscription_changes WHERE id = %s", [change.pk]),
        ("UPDATE subscription_changes SET status = 'scheduled' WHERE id = %s", [change.pk]),
        ("DELETE FROM subscription_change_events WHERE id = %s", [event.pk]),
        ("UPDATE subscriptions SET source_change_id = NULL WHERE id = %s", [target.pk]),
    )
    for sql, params in statements:
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)


def test_postgresql_retain_transfer_pair_and_hold_group_aggregate_are_guarded():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="pg-transfer-source")
    account = QuotaAccount.objects.get(subscription=source, quota_type="detection_points")
    fund(actor, account, 3)
    target_plan, target_version = published_plan(actor, code="pg-transfer-target")
    change = change_operation(
        actor.pk,
        source.pk,
        target_plan.pk,
        target_version.pk,
        "pg-transfer-key-0000001",
        policy="retain",
    )
    transfer = QuotaTransfer.objects.get(change=change)
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quota_transfers SET amount = amount + 1 WHERE id = %s",
                [transfer.pk],
            )
    carryover = transfer.target_account
    group = freeze_quota(
        account_id=carryover.pk,
        amount=1,
        business_type="pg_group_guard",
        business_id=uuid.uuid4(),
        idempotency_key="pg-group-freeze-000001",
        request_id=uuid.uuid4(),
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quota_hold_groups SET consumed_amount = 1 WHERE id = %s",
                [group.pk],
            )


def test_postgresql_retain_freeze_uses_earliest_expiry_batch_first():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="pg-earliest-source")
    old = QuotaAccount.objects.get(subscription=source, quota_type="detection_points")
    fund(actor, old, 2)
    target_plan, target_version = published_plan(actor, code="pg-earliest-target")
    change = change_operation(
        actor.pk,
        source.pk,
        target_plan.pk,
        target_version.pk,
        "pg-earliest-key-0000001",
        policy="retain",
    )
    target = change.target_subscription
    carryover = QuotaAccount.objects.get(
        subscription=target,
        quota_type="detection_points",
        batch_type="carryover",
    )
    primary = QuotaAccount.objects.get(
        subscription=target,
        quota_type="detection_points",
        batch_type="primary",
    )
    fund(actor, primary, 2)
    group = freeze_quota(
        account_id=primary.pk,
        amount=3,
        business_type="pg_earliest",
        business_id=uuid.uuid4(),
        idempotency_key="pg-earliest-freeze-0001",
        request_id=uuid.uuid4(),
    )
    allocations = list(group.allocations.order_by("account__spendable_until", "account_id"))
    assert allocations[0].account_id == carryover.pk
    assert allocations[0].requested_amount == 2
    assert sum(item.requested_amount for item in allocations) == 3


def test_postgresql_change_and_hold_race_cannot_bypass_frozen_check():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="pg-race-source")
    account = QuotaAccount.objects.get(subscription=source, quota_type="detection_points")
    fund(actor, account, 1)
    target_plan, target_version = published_plan(actor, code="pg-race-target")

    def freeze():
        return freeze_quota(
            account_id=account.pk,
            amount=1,
            business_type="pg_change_race",
            business_id=uuid.uuid4(),
            idempotency_key="pg-race-freeze-000001",
            request_id=uuid.uuid4(),
        )

    results = parallel(
        freeze,
        lambda: change_operation(
            actor.pk, source.pk, target_plan.pk, target_version.pk, "pg-race-change-000001"
        ),
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    source.refresh_from_db()
    if source.status == Subscription.Status.ACTIVE:
        assert QuotaHoldGroup.objects.filter(user=user, status="open").count() == 1
    else:
        assert not QuotaHoldGroup.objects.filter(user=user).exists()


def test_postgresql_notification_failure_rolls_back_entire_immediate_change():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="pg-rollback-source")
    target_plan, target_version = published_plan(actor, code="pg-rollback-target")
    with patch.object(Notification.objects, "create", side_effect=RuntimeError("injected")):
        with pytest.raises(RuntimeError):
            change_operation(
                actor.pk,
                source.pk,
                target_plan.pk,
                target_version.pk,
                "pg-rollback-key-000001",
            )
    source.refresh_from_db()
    assert source.status == Subscription.Status.ACTIVE
    assert not SubscriptionChange.objects.filter(from_subscription=source).exists()
    assert not Subscription.objects.filter(user=user, source_type="plan_change").exists()


def test_postgresql_two_users_change_same_plans_without_deadlock():
    actor = admin()
    first, second = customer("13800138001"), customer("13800138002")
    first_source, _, _ = activate_formal(actor, first, code="pg-lock-source-1")
    second_source, _, _ = activate_formal(actor, second, code="pg-lock-source-2")
    target_plan, target_version = published_plan(actor, code="pg-lock-target")
    results = parallel(
        lambda: change_operation(
            actor.pk,
            first_source.pk,
            target_plan.pk,
            target_version.pk,
            "pg-lock-key-0000000001",
        ),
        lambda: change_operation(
            actor.pk,
            second_source.pk,
            target_plan.pk,
            target_version.pk,
            "pg-lock-key-0000000002",
        ),
    )
    assert all(not isinstance(result, Exception) for result in results)


def published_plan_variant(actor, *, code, valid_days=30, limits=None):
    plan, _ = published_plan(actor, code=f"{code}-seed")
    plan.refresh_from_db()
    draft = create_plan_version(
        plan_id=plan.pk,
        actor=actor,
        expected_plan_version=plan.version,
    )
    PlanVersion.objects.filter(pk=draft.pk).update(valid_days=valid_days)
    for key, value in (limits or {}).items():
        assert (
            PlanLimit.objects.filter(plan_version=draft, limit_key=key).update(integer_value=value)
            == 1
        )
    draft.refresh_from_db()
    version = publish_plan_version(
        version_id=draft.pk,
        actor=actor,
        expected_version=draft.version,
        confirm_informal_composite=True,
    )
    plan.refresh_from_db()
    return plan, version


def activate_existing_plan(actor, user, plan, version):
    application = application_for(user, plan, version)
    subscription, _, _ = activate_application(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        application_id=application.pk,
        expected_version=application.version,
        selected_plan_version_id=None,
        confirm_unavailable=False,
        unavailable_reason="",
        confirm_version_override=False,
        override_reason="",
        opening_note="PostgreSQL 专属测试",
        request_id=uuid.uuid4(),
    )
    return subscription


def cancel_digests(actor, change, key, reason):
    return derive_plan_change_digests(
        key,
        operation="subscription.change.cancel",
        requester_id=actor.pk,
        target_id=change.pk,
        request_payload={"reason": reason},
    )


def assert_change_rolled_back(source, user, source_account, expected_available):
    source.refresh_from_db()
    source_account.refresh_from_db()
    assert source.status == Subscription.Status.ACTIVE
    assert source_account.available == expected_available
    assert not SubscriptionChange.objects.filter(from_subscription=source).exists()
    assert not Subscription.objects.filter(user=user, source_type="plan_change").exists()
    assert not QuotaTransfer.objects.filter(change__from_subscription=source).exists()


def test_postgresql_renewal_is_scheduled_without_future_facts_and_cancel_is_safe():
    actor, user = admin(), customer()
    source, plan, version = activate_formal(actor, user, code="pg-renewal-source")
    before = {
        "subscriptions": Subscription.objects.filter(user=user).count(),
        "accounts": QuotaAccount.objects.filter(user=user).count(),
        "ledger": QuotaLedgerEntry.objects.filter(user=user).count(),
    }
    change = change_operation(
        actor.pk,
        source.pk,
        plan.pk,
        version.pk,
        "pg-renewal-key-000001",
        change_type="renewal",
    )
    assert change.status == SubscriptionChange.Status.SCHEDULED
    assert change.effective_at == source.ends_at
    assert not hasattr(change, "target_subscription")
    assert Subscription.objects.filter(user=user).count() == before["subscriptions"]
    assert QuotaAccount.objects.filter(user=user).count() == before["accounts"]
    assert QuotaLedgerEntry.objects.filter(user=user).count() == before["ledger"]

    reason = "取消续费排期"
    cancelled = cancel_scheduled_change(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        change_id=change.pk,
        expected_version=change.version,
        reason=reason,
        digests=cancel_digests(actor, change, "pg-renewal-cancel-key-0001", reason),
        request_id=uuid.uuid4(),
    )
    source.refresh_from_db()
    assert cancelled.status == SubscriptionChange.Status.CANCELLED
    assert source.status == Subscription.Status.ACTIVE
    assert Subscription.objects.filter(user=user).count() == before["subscriptions"]
    assert QuotaAccount.objects.filter(user=user).count() == before["accounts"]
    assert QuotaLedgerEntry.objects.filter(user=user).count() == before["ledger"]


def test_postgresql_mixed_entitlements_are_replacement_and_invalid_source_is_rejected():
    actor, user = admin(), customer()
    source_plan, source_version = published_plan_variant(
        actor,
        code="pg-mixed-source",
        limits={"detection_points": 10, "article_credits": 1},
    )
    source = activate_existing_plan(actor, user, source_plan, source_version)
    target_plan, target_version = published_plan_variant(
        actor,
        code="pg-mixed-target",
        limits={"detection_points": 1, "article_credits": 10},
    )
    change = change_operation(
        actor.pk,
        source.pk,
        target_plan.pk,
        target_version.pk,
        "pg-mixed-key-00000001",
        change_type="replacement",
    )
    assert change.change_type == SubscriptionChange.ChangeType.REPLACEMENT

    invalid_user = customer("13800138199")
    now = timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        Subscription.objects.create(
            user=invalid_user,
            source_type=Subscription.SourceType.PLAN_CHANGE,
            source_application=None,
            source_change=None,
            plan=target_plan,
            plan_version=target_version,
            plan_version_no=target_version.version_no,
            entitlement_snapshot=target_version.effective_config,
            entitlement_digest=target_version.config_digest,
            status=Subscription.Status.ACTIVE,
            starts_at=now,
            ends_at=now + timedelta(days=30),
            cycle_anchor_day=timezone.localtime(now).day,
            cycle_anchor_time=timezone.localtime(now).timetz().replace(tzinfo=None),
            is_trial=False,
            opened_by=actor,
            activated_at=now,
            request_id=uuid.uuid4(),
        )


@pytest.mark.parametrize("policy", ["overwrite", "accumulate", "retain"])
def test_postgresql_quota_policy_preserves_entitlement_and_uses_explicit_evidence(policy):
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code=f"pg-policy-{policy}-source")
    source_account = QuotaAccount.objects.get(
        subscription=source,
        quota_type="detection_points",
    )
    fund(actor, source_account, 3)
    target_plan, target_version = published_plan(actor, code=f"pg-policy-{policy}-target")
    change = change_operation(
        actor.pk,
        source.pk,
        target_plan.pk,
        target_version.pk,
        f"pg-policy-{policy}-key-0001",
        policy=policy,
    )
    source_account.refresh_from_db()
    assert source_account.available == source_account.frozen == 0
    target_primary = QuotaAccount.objects.get(
        subscription=change.target_subscription,
        quota_type="detection_points",
        batch_type=QuotaAccount.BatchType.PRIMARY,
    )
    assert (
        target_primary.entitlement_amount
        == target_version.effective_config["limits"]["detection_points"]
    )
    if policy == "overwrite":
        assert not QuotaTransfer.objects.filter(change=change).exists()
        assert QuotaLedgerEntry.objects.filter(
            account=source_account,
            action=QuotaLedgerEntry.Action.PLAN_CHANGE_FORFEIT,
        ).exists()
    elif policy == "accumulate":
        transfer = QuotaTransfer.objects.get(change=change, source_account=source_account)
        assert transfer.target_account_id == target_primary.pk
        target_primary.refresh_from_db()
        assert target_primary.available == target_primary.entitlement_amount + 3
    else:
        carryover = QuotaAccount.objects.get(
            subscription=change.target_subscription,
            quota_type="detection_points",
            batch_type=QuotaAccount.BatchType.CARRYOVER,
        )
        assert carryover.entitlement_amount == 0
        assert carryover.available == 3
        assert QuotaTransfer.objects.get(change=change).target_account_id == carryover.pk


def test_postgresql_expired_cycle_balance_is_forfeited_instead_of_transferred():
    actor, user = admin(), customer()
    source_plan, source_version = published_plan_variant(
        actor,
        code="pg-expired-balance-source",
        valid_days=90,
    )
    source = activate_existing_plan(actor, user, source_plan, source_version)
    source_account = QuotaAccount.objects.get(
        subscription=source,
        quota_type="assistant_messages",
    )
    assert source_account.cycle_ends_at is not None
    assert source_account.cycle_ends_at < source.ends_at
    fund(actor, source_account, 2)
    target_plan, target_version = published_plan(actor, code="pg-expired-balance-target")
    after_cycle = source_account.cycle_ends_at + timedelta(seconds=1)
    with patch("apps.plans.change_services.timezone.now", return_value=after_cycle):
        change = change_operation(
            actor.pk,
            source.pk,
            target_plan.pk,
            target_version.pk,
            "pg-expired-balance-key-01",
            policy="retain",
        )
    source_account.refresh_from_db()
    assert source_account.available == 0
    assert QuotaLedgerEntry.objects.filter(
        account=source_account,
        action=QuotaLedgerEntry.Action.PLAN_CHANGE_FORFEIT,
    ).exists()
    assert not QuotaTransfer.objects.filter(change=change, source_account=source_account).exists()


def test_postgresql_change_and_cancel_idempotency_conflict_matrix():
    actor, user = admin(), customer()
    source, plan, version = activate_formal(actor, user, code="pg-idem-matrix")
    key = "pg-change-idem-matrix-key-01"
    change = change_operation(
        actor.pk,
        source.pk,
        plan.pk,
        version.pk,
        key,
        change_type="renewal",
        reason="相同请求",
    )
    replay = change_operation(
        actor.pk,
        source.pk,
        plan.pk,
        version.pk,
        key,
        change_type="renewal",
        reason="相同请求",
    )
    assert replay.pk == change.pk
    with pytest.raises(SubscriptionChangeIdempotencyConflict):
        change_operation(
            actor.pk,
            source.pk,
            plan.pk,
            version.pk,
            key,
            change_type="renewal",
            reason="不同请求",
        )
    with pytest.raises(SubscriptionChangeAlreadyExists):
        change_operation(
            actor.pk,
            source.pk,
            plan.pk,
            version.pk,
            "pg-change-idem-matrix-key-02",
            change_type="renewal",
            reason="相同请求",
        )

    cancel_key = "pg-cancel-idem-matrix-key-01"
    cancel_reason = "相同取消请求"
    cancel_kwargs = {
        "requester": actor,
        "admin_context": resolve_admin_context(actor),
        "change_id": change.pk,
        "expected_version": change.version,
        "reason": cancel_reason,
        "digests": cancel_digests(actor, change, cancel_key, cancel_reason),
    }
    cancelled = cancel_scheduled_change(**cancel_kwargs, request_id=uuid.uuid4())
    replayed = cancel_scheduled_change(**cancel_kwargs, request_id=uuid.uuid4())
    assert replayed.pk == cancelled.pk
    with pytest.raises(SubscriptionChangeIdempotencyConflict):
        cancel_scheduled_change(
            requester=actor,
            admin_context=resolve_admin_context(actor),
            change_id=change.pk,
            expected_version=change.version,
            reason="不同取消请求",
            digests=cancel_digests(actor, change, cancel_key, "不同取消请求"),
            request_id=uuid.uuid4(),
        )
    with pytest.raises(SubscriptionChangeStateConflict):
        cancel_scheduled_change(
            requester=actor,
            admin_context=resolve_admin_context(actor),
            change_id=change.pk,
            expected_version=cancelled.version,
            reason=cancel_reason,
            digests=cancel_digests(
                actor,
                change,
                "pg-cancel-idem-matrix-key-02",
                cancel_reason,
            ),
            request_id=uuid.uuid4(),
        )


def test_postgresql_preview_submit_and_concurrent_two_person_approval_are_exactly_once():
    requester, approver, user = admin(), admin("13700137991"), customer()
    source, _, _ = activate_formal(requester, user, code="pg-two-person-source")
    target_plan, target_version = published_plan(requester, code="pg-two-person-target")
    body = {
        "expected_version": source.version,
        "target_plan_version_id": str(target_version.pk),
        "change_type": "replacement",
        "quota_policy": "overwrite",
        "reason": "双人审批套餐变更",
    }
    requester_client = authenticate_admin_client(APIClient(), requester)
    before = {
        "changes": SubscriptionChange.objects.count(),
        "subscriptions": Subscription.objects.filter(user=user).count(),
        "accounts": QuotaAccount.objects.filter(user=user).count(),
        "ledger": QuotaLedgerEntry.objects.filter(user=user).count(),
        "approvals": ApprovalRequest.objects.count(),
    }
    preview = requester_client.post(
        f"/api/v1/admin/subscriptions/{source.pk}/change/preview",
        {
            "expected_version": body["expected_version"],
            "target_plan_version_id": body["target_plan_version_id"],
            "change_type": body["change_type"],
            "quota_policy": body["quota_policy"],
        },
        format="json",
    )
    assert preview.status_code == 200
    assert SubscriptionChange.objects.count() == before["changes"]
    assert Subscription.objects.filter(user=user).count() == before["subscriptions"]
    assert QuotaAccount.objects.filter(user=user).count() == before["accounts"]
    assert QuotaLedgerEntry.objects.filter(user=user).count() == before["ledger"]
    assert ApprovalRequest.objects.count() == before["approvals"]

    submitted = requester_client.post(
        f"/api/v1/admin/subscriptions/{source.pk}/change",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="pg-two-person-submit-key-01",
    )
    assert submitted.status_code == 202
    approval = ApprovalRequest.objects.get(pk=submitted.json()["data"]["approval_id"])
    assert SubscriptionChange.objects.count() == before["changes"]
    assert Subscription.objects.filter(user=user).count() == before["subscriptions"]
    assert QuotaAccount.objects.filter(user=user).count() == before["accounts"]
    assert QuotaLedgerEntry.objects.filter(user=user).count() == before["ledger"]

    first = authenticate_admin_client(APIClient(), approver)
    second = authenticate_admin_client(APIClient(), approver)
    responses = parallel(
        lambda: first.post(
            f"/api/v1/admin/approvals/{approval.pk}/approve",
            {"current_password": PASSWORD},
            format="json",
        ),
        lambda: second.post(
            f"/api/v1/admin/approvals/{approval.pk}/approve",
            {"current_password": PASSWORD},
            format="json",
        ),
    )
    assert all(not isinstance(response, Exception) for response in responses)
    assert sorted(response.status_code for response in responses) == [200, 409]
    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.EXECUTED
    assert SubscriptionChange.objects.filter(from_subscription=source).count() == 1
    assert Subscription.objects.filter(user=user, source_type="plan_change").count() == 1
    assert (
        AuditEvent.objects.filter(
            approval_request=approval,
            action_key="subscription.change",
            outcome="executed",
        ).count()
        == 1
    )


@pytest.mark.parametrize(
    "failure_point",
    ["ledger", "subscription_event", "change_event", "notification"],
)
def test_postgresql_immediate_change_domain_failure_rolls_back_all_facts(failure_point):
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code=f"pg-fail-{failure_point}-source")
    source_account = QuotaAccount.objects.get(
        subscription=source,
        quota_type="detection_points",
    )
    fund(actor, source_account, 3)
    target_plan, target_version = published_plan(actor, code=f"pg-fail-{failure_point}-target")
    if failure_point == "ledger":
        context = patch(
            "apps.quotas.services._append_ledger_locked",
            side_effect=RuntimeError("injected ledger failure"),
        )
    elif failure_point == "subscription_event":
        context = patch(
            "apps.plans.change_services._subscription_event",
            side_effect=RuntimeError("injected subscription event failure"),
        )
    elif failure_point == "change_event":
        context = patch.object(
            SubscriptionChangeEvent.objects,
            "create",
            side_effect=RuntimeError("injected change event failure"),
        )
    else:
        context = patch.object(
            Notification.objects,
            "create",
            side_effect=RuntimeError("injected notification failure"),
        )
    with context, pytest.raises(RuntimeError):
        change_operation(
            actor.pk,
            source.pk,
            target_plan.pk,
            target_version.pk,
            f"pg-fail-{failure_point}-key-01",
            policy="retain",
        )
    assert_change_rolled_back(source, user, source_account, 3)


@pytest.mark.parametrize("corruption", ["missing_transfer", "amount_mismatch"])
def test_postgresql_transfer_ledger_pair_is_deferred_complete_and_atomic(corruption):
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code=f"pg-pair-{corruption}-source")
    source_account = QuotaAccount.objects.get(
        subscription=source,
        quota_type="detection_points",
    )
    fund(actor, source_account, 3)
    target_plan, target_version = published_plan(actor, code=f"pg-pair-{corruption}-target")
    if corruption == "missing_transfer":
        context = patch.object(QuotaTransfer.objects, "create", return_value=None)
    else:
        original_create = QuotaTransfer.objects.create

        def corrupt_amount(**kwargs):
            kwargs["amount"] += 1
            return original_create(**kwargs)

        context = patch.object(QuotaTransfer.objects, "create", side_effect=corrupt_amount)
    with context, pytest.raises(DatabaseError):
        change_operation(
            actor.pk,
            source.pk,
            target_plan.pk,
            target_version.pk,
            f"pg-pair-{corruption}-key-01",
            policy="retain",
        )
    assert_change_rolled_back(source, user, source_account, 3)


def test_postgresql_audit_failure_rolls_back_approved_plan_change():
    requester, approver, user = admin(), admin("13700137992"), customer()
    source, _, _ = activate_formal(requester, user, code="pg-audit-fail-source")
    source_account = QuotaAccount.objects.get(
        subscription=source,
        quota_type="detection_points",
    )
    target_plan, target_version = published_plan(requester, code="pg-audit-fail-target")
    requester_client = authenticate_admin_client(APIClient(), requester)
    submitted = requester_client.post(
        f"/api/v1/admin/subscriptions/{source.pk}/change",
        {
            "expected_version": source.version,
            "target_plan_version_id": str(target_version.pk),
            "change_type": "replacement",
            "quota_policy": "overwrite",
            "reason": "审计失败回滚",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="pg-audit-failure-key-0001",
    )
    assert submitted.status_code == 202
    approval = ApprovalRequest.objects.get(pk=submitted.json()["data"]["approval_id"])
    approver_client = authenticate_admin_client(APIClient(), approver)
    approver_client.raise_request_exception = False
    with patch(
        "apps.admin_rbac.risk_services.record_audit_event",
        side_effect=RuntimeError("injected audit failure"),
    ):
        response = approver_client.post(
            f"/api/v1/admin/approvals/{approval.pk}/approve",
            {"current_password": PASSWORD},
            format="json",
        )
    assert response.status_code == 500
    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING
    assert_change_rolled_back(
        source,
        user,
        source_account,
        source_account.entitlement_amount,
    )


def test_postgresql_hold_group_allocations_settle_and_raw_mismatch_cannot_commit():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="pg-group-settle-source")
    old = QuotaAccount.objects.get(subscription=source, quota_type="detection_points")
    fund(actor, old, 2)
    target_plan, target_version = published_plan(actor, code="pg-group-settle-target")
    change = change_operation(
        actor.pk,
        source.pk,
        target_plan.pk,
        target_version.pk,
        "pg-group-settle-change-key",
        policy="retain",
    )
    target = change.target_subscription
    carryover = QuotaAccount.objects.get(
        subscription=target,
        quota_type="detection_points",
        batch_type=QuotaAccount.BatchType.CARRYOVER,
    )
    primary = QuotaAccount.objects.get(
        subscription=target,
        quota_type="detection_points",
        batch_type=QuotaAccount.BatchType.PRIMARY,
    )
    fund(actor, primary, 2)
    group = freeze_quota(
        account_id=primary.pk,
        amount=3,
        business_type="pg_group_settlement",
        business_id=uuid.uuid4(),
        idempotency_key="pg-group-settlement-freeze-key",
        request_id=uuid.uuid4(),
    )
    allocations = list(group.allocations.select_related("account"))
    assert {item.account_id for item in allocations} == {carryover.pk, primary.pk}
    assert sum(item.requested_amount for item in allocations) == group.requested_amount == 3

    consume_hold(
        hold_id=group.pk,
        amount=1,
        idempotency_key="pg-group-settlement-consume-key",
        request_id=uuid.uuid4(),
    )
    release_hold(
        hold_id=group.pk,
        amount=2,
        idempotency_key="pg-group-settlement-release-key",
        request_id=uuid.uuid4(),
    )
    group.refresh_from_db()
    allocations = list(group.allocations.all())
    assert group.status == QuotaHoldGroup.Status.SETTLED
    assert group.consumed_amount == sum(item.consumed_amount for item in allocations) == 1
    assert group.released_amount == sum(item.released_amount for item in allocations) == 2

    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quota_hold_groups SET status = 'open' WHERE id = %s",
                [group.pk],
            )

    with pytest.raises(DatabaseError), transaction.atomic():
        QuotaHoldGroup.objects.create(
            user=user,
            quota_type="detection_points",
            business_type="pg_orphan_group",
            business_id=uuid.uuid4(),
            requested_amount=1,
            freeze_idempotency_key_digest=uuid.uuid4().hex * 2,
            freeze_idempotency_scope_digest=uuid.uuid4().hex * 2,
            freeze_request_digest=uuid.uuid4().hex * 2,
        )

    with pytest.raises(DatabaseError), transaction.atomic():
        mismatched = QuotaHoldGroup.objects.create(
            user=user,
            quota_type="detection_points",
            business_type="pg_mismatch_group",
            business_id=uuid.uuid4(),
            requested_amount=2,
            freeze_idempotency_key_digest=uuid.uuid4().hex * 2,
            freeze_idempotency_scope_digest=uuid.uuid4().hex * 2,
            freeze_request_digest=uuid.uuid4().hex * 2,
        )
        QuotaHold.objects.create(
            group=mismatched,
            account=primary,
            user=user,
            subscription=target,
            quota_type="detection_points",
            business_type=mismatched.business_type,
            business_id=mismatched.business_id,
            requested_amount=1,
            freeze_idempotency_key_digest=uuid.uuid4().hex * 2,
            freeze_idempotency_scope_digest=uuid.uuid4().hex * 2,
            freeze_request_digest=uuid.uuid4().hex * 2,
        )


def test_postgresql_submission_recomputes_and_rejects_untrusted_preview_fields():
    requester, approver, user = admin(), admin("13700137993"), customer()
    del approver
    source, _, _ = activate_formal(requester, user, code="pg-submit-recompute-source")
    _, target_version = published_plan(requester, code="pg-submit-recompute-target")
    client = authenticate_admin_client(APIClient(), requester)
    url = f"/api/v1/admin/subscriptions/{source.pk}/change"
    base = {
        "expected_version": source.version,
        "target_plan_version_id": str(target_version.pk),
        "change_type": "upgrade",
        "quota_policy": "overwrite",
        "reason": "server must recompute classification",
    }
    before = {
        "approvals": ApprovalRequest.objects.count(),
        "changes": SubscriptionChange.objects.count(),
        "subscriptions": Subscription.objects.filter(user=user).count(),
        "accounts": QuotaAccount.objects.filter(user=user).count(),
        "ledger": QuotaLedgerEntry.objects.filter(user=user).count(),
        "transfers": QuotaTransfer.objects.count(),
        "notifications": Notification.objects.filter(recipient=user).count(),
    }
    response = client.post(
        url,
        base,
        format="json",
        HTTP_IDEMPOTENCY_KEY="pg-submit-recompute-key-01",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SUBSCRIPTION_CHANGE_CLASSIFICATION_INVALID"

    for index, untrusted in enumerate(
        (
            {"classification": "upgrade"},
            {"before_snapshot": {"limits": {"detection_points": 999999}}},
            {"effective_at": timezone.now().isoformat()},
            {"quota_migration_result": {"available": 999999}},
        ),
        start=2,
    ):
        response = client.post(
            url,
            {
                **base,
                "change_type": "replacement",
                **untrusted,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"pg-submit-recompute-key-{index:02d}",
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    assert ApprovalRequest.objects.count() == before["approvals"]
    assert SubscriptionChange.objects.count() == before["changes"]
    assert Subscription.objects.filter(user=user).count() == before["subscriptions"]
    assert QuotaAccount.objects.filter(user=user).count() == before["accounts"]
    assert QuotaLedgerEntry.objects.filter(user=user).count() == before["ledger"]
    assert QuotaTransfer.objects.count() == before["transfers"]
    assert Notification.objects.filter(recipient=user).count() == before["notifications"]


def test_postgresql_trial_conversion_boundaries_are_server_enforced():
    requester, approver = admin(), admin("13700137994")
    del approver
    client = authenticate_admin_client(APIClient(), requester)
    trial_plan, trial_version = published_plan(requester, code="pg-trial-target", trial=True)
    paid_user = customer()
    paid_source, _, _ = activate_formal(requester, paid_user, code="pg-paid-source")
    paid_response = client.post(
        f"/api/v1/admin/subscriptions/{paid_source.pk}/change",
        {
            "expected_version": paid_source.version,
            "target_plan_version_id": str(trial_version.pk),
            "change_type": "trial_conversion",
            "quota_policy": "overwrite",
            "reason": "paid subscriptions cannot convert to trial",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="test-test-test-test-0001",
    )
    assert paid_response.status_code == 409
    assert paid_response.json()["error"]["code"] == "SUBSCRIPTION_PLAN_UNAVAILABLE"

    trial_user = customer("13800138201")
    trial_source = grant_trial(
        requester=requester,
        admin_context=resolve_admin_context(requester),
        user_id=trial_user.pk,
        expected_status_version=trial_user.status_version,
        plan_id=trial_plan.pk,
        opening_note="trial boundary",
        request_id=uuid.uuid4(),
    )
    trial_response = client.post(
        f"/api/v1/admin/subscriptions/{trial_source.pk}/change",
        {
            "expected_version": trial_source.version,
            "target_plan_version_id": str(trial_version.pk),
            "change_type": "trial_conversion",
            "quota_policy": "overwrite",
            "reason": "trial cannot convert to trial",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="test-test-test-test-0002",
    )
    assert trial_response.status_code == 409
    assert trial_response.json()["error"]["code"] == "SUBSCRIPTION_PLAN_UNAVAILABLE"

    formal_plan, formal_version = published_plan(requester, code="pg-trial-formal-target")
    del formal_plan
    wrong_type = client.post(
        f"/api/v1/admin/subscriptions/{trial_source.pk}/change",
        {
            "expected_version": trial_source.version,
            "target_plan_version_id": str(formal_version.pk),
            "change_type": "replacement",
            "quota_policy": "overwrite",
            "reason": "client cannot choose a non-conversion classification",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="pg-trial-wrong-type-key-01",
    )
    assert wrong_type.status_code == 422
    assert wrong_type.json()["error"]["code"] == "SUBSCRIPTION_CHANGE_CLASSIFICATION_INVALID"

    valid = client.post(
        f"/api/v1/admin/subscriptions/{trial_source.pk}/change",
        {
            "expected_version": trial_source.version,
            "target_plan_version_id": str(formal_version.pk),
            "change_type": "trial_conversion",
            "quota_policy": "overwrite",
            "reason": "valid trial conversion",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="test-test-test-test-0003",
    )
    assert valid.status_code == 202
    approval = ApprovalRequest.objects.get(pk=valid.json()["data"]["approval_id"])
    assert approval.sanitized_payload["change_type"] == "trial_conversion"
    assert not SubscriptionChange.objects.filter(from_subscription=trial_source).exists()


def test_postgresql_http_change_and_cancel_idempotency_matrix():
    requester, approver, user = admin(), admin("13700137995"), customer()
    del approver
    client = authenticate_admin_client(APIClient(), requester)
    source, plan, version = activate_formal(requester, user, code="pg-http-change-idem")
    change_url = f"/api/v1/admin/subscriptions/{source.pk}/change"
    change_body = {
        "expected_version": source.version,
        "target_plan_version_id": str(version.pk),
        "change_type": "renewal",
        "quota_policy": "overwrite",
        "reason": "canonical renewal",
    }
    missing = client.post(change_url, change_body, format="json")
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "PLAN_CHANGE_IDEMPOTENCY_REQUIRED"

    raw_change_key = "pg-http-shared-idempotency-key-01"
    first = client.post(
        change_url,
        change_body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=raw_change_key,
    )
    replay = client.post(
        change_url,
        change_body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=raw_change_key,
    )
    assert first.status_code == replay.status_code == 202
    assert first.json()["data"]["approval_id"] == replay.json()["data"]["approval_id"]
    change_approval = ApprovalRequest.objects.get(pk=first.json()["data"]["approval_id"])

    conflicts = (
        (raw_change_key, {**change_body, "reason": "different payload"}),
        ("pg-http-change-idem-key-0002", change_body),
        (
            "pg-http-change-idem-key-0003",
            {**change_body, "quota_policy": "retain", "reason": "different canonical change"},
        ),
    )
    for key, body in conflicts:
        response = client.post(
            change_url,
            body,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "APPROVAL_STATE_CONFLICT"

    cancel_user = customer("13800138202")
    cancel_source, cancel_plan, cancel_version = activate_formal(
        requester,
        cancel_user,
        code="pg-http-cancel-idem",
    )
    scheduled = change_operation(
        requester.pk,
        cancel_source.pk,
        cancel_plan.pk,
        cancel_version.pk,
        "pg-http-cancel-scheduled-key-01",
        change_type="renewal",
    )
    cancel_url = f"/api/v1/admin/subscription-changes/{scheduled.pk}/cancel"
    cancel_body = {
        "expected_version": scheduled.version,
        "reason": "canonical cancellation",
    }
    missing = client.post(cancel_url, cancel_body, format="json")
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "PLAN_CHANGE_IDEMPOTENCY_REQUIRED"

    raw_cancel_key = raw_change_key
    first_cancel = client.post(
        cancel_url,
        cancel_body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=raw_cancel_key,
    )
    replay_cancel = client.post(
        cancel_url,
        cancel_body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=raw_cancel_key,
    )
    assert first_cancel.status_code == replay_cancel.status_code == 202
    assert first_cancel.json()["data"]["approval_id"] == replay_cancel.json()["data"]["approval_id"]
    cancel_approval = ApprovalRequest.objects.get(pk=first_cancel.json()["data"]["approval_id"])

    cancel_conflicts = (
        (raw_cancel_key, {**cancel_body, "reason": "different cancellation"}),
        ("pg-http-cancel-idem-key-0002", cancel_body),
        (
            "pg-http-cancel-idem-key-0003",
            {**cancel_body, "reason": "different cancellation and key"},
        ),
    )
    for key, body in cancel_conflicts:
        response = client.post(
            cancel_url,
            body,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "APPROVAL_STATE_CONFLICT"

    assert (
        change_approval.sanitized_payload["idempotency_scope_digest"]
        != cancel_approval.sanitized_payload["idempotency_scope_digest"]
    )
    serialized_records = " ".join(
        (
            str(list(ApprovalRequest.objects.values("sanitized_payload", "safe_summary"))),
            str(list(AuditEvent.objects.values("safe_before", "safe_after", "stable_error_code"))),
            str(list(Notification.objects.values("title", "safe_summary"))),
            str(first.json()),
            str(first_cancel.json()),
        )
    )
    for raw_key in (
        raw_change_key,
        "pg-http-change-idem-key-0002",
        "pg-http-change-idem-key-0003",
        "pg-http-cancel-idem-key-0002",
        "pg-http-cancel-idem-key-0003",
    ):
        assert raw_key not in serialized_records


@pytest.mark.parametrize(
    "corruption",
    ["reversed_accounts", "quota_type_mismatch", "wrong_change"],
)
def test_postgresql_transfer_is_bound_to_change_accounts_direction_and_quota_type(corruption):
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code=f"pg-binding-{corruption}-source")
    source_account = QuotaAccount.objects.get(
        subscription=source,
        quota_type="detection_points",
    )
    fund(actor, source_account, 3)
    target_plan, target_version = published_plan(actor, code=f"pg-binding-{corruption}-target")
    wrong_change = None
    if corruption == "wrong_change":
        other_user = customer("13800138203")
        other_source, _, _ = activate_formal(actor, other_user, code="pg-binding-other-source")
        other_plan, other_version = published_plan(actor, code="pg-binding-other-target")
        wrong_change = change_operation(
            actor.pk,
            other_source.pk,
            other_plan.pk,
            other_version.pk,
            "pg-binding-other-change-key-01",
        )

    original_create = QuotaTransfer.objects.create

    def corrupt_transfer(**kwargs):
        if corruption == "reversed_accounts":
            kwargs["source_account"], kwargs["target_account"] = (
                kwargs["target_account"],
                kwargs["source_account"],
            )
        elif corruption == "quota_type_mismatch":
            kwargs["quota_type"] = "assistant_messages"
        else:
            kwargs["change"] = wrong_change
        return original_create(**kwargs)

    with (
        patch.object(
            QuotaTransfer.objects,
            "create",
            side_effect=corrupt_transfer,
        ),
        pytest.raises(DatabaseError),
    ):
        change_operation(
            actor.pk,
            source.pk,
            target_plan.pk,
            target_version.pk,
            f"pg-binding-{corruption}-key-01",
            policy="retain",
        )
    assert_change_rolled_back(source, user, source_account, 3)


@pytest.mark.parametrize(
    ("action", "failure_name"),
    (
        (QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_OUT, "transfer_out"),
        (QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_IN, "transfer_in"),
    ),
)
def test_postgresql_transfer_ledger_side_failure_rolls_back_entire_change(
    action,
    failure_name,
):
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code=f"pg-ledger-{failure_name}-source")
    source_account = QuotaAccount.objects.get(
        subscription=source,
        quota_type="detection_points",
    )
    fund(actor, source_account, 3)
    target_plan, target_version = published_plan(actor, code=f"pg-ledger-{failure_name}-target")
    original_append = quota_services._append_ledger_locked

    def fail_selected_side(*args, **kwargs):
        if kwargs.get("action") == action:
            raise RuntimeError(f"injected {failure_name} ledger failure")
        return original_append(*args, **kwargs)

    with (
        patch(
            "apps.quotas.services._append_ledger_locked",
            side_effect=fail_selected_side,
        ),
        pytest.raises(RuntimeError),
    ):
        change_operation(
            actor.pk,
            source.pk,
            target_plan.pk,
            target_version.pk,
            f"pg-ledger-{failure_name}-key-01",
            policy="retain",
        )
    assert_change_rolled_back(source, user, source_account, 3)
