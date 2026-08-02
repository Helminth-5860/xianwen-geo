import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django_redis import get_redis_connection

from apps.admin_rbac.permissions import resolve_admin_context
from apps.plans.change_idempotency import derive_plan_change_digests
from apps.plans.change_services import execute_subscription_change
from apps.plans.models import Subscription, SubscriptionChange, SubscriptionChangeEvent
from apps.quotas.idempotency import derive_idempotency_digests
from apps.quotas.models import QuotaAccount, QuotaHoldGroup, QuotaTransfer
from apps.quotas.services import adjust_quota_account, freeze_quota
from apps.users.models import Notification, User
from tests.test_plan_changes import activate_formal, admin, customer
from tests.test_subscriptions import published_plan

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


def change_operation(
    actor_id, source_id, target_plan_id, target_version_id, key, policy="overwrite"
):
    actor = User.objects.get(pk=actor_id)
    source = Subscription.objects.get(pk=source_id)
    payload = {
        "target_plan_version_id": str(target_version_id),
        "change_type": "replacement",
        "quota_policy": policy,
        "confirm_unavailable": False,
        "unavailable_reason": "",
        "reason": "并发套餐变更",
    }
    return execute_subscription_change(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        source_subscription_id=source.pk,
        expected_version=source.version,
        target_plan_id=target_plan_id,
        target_plan_version_id=target_version_id,
        requested_type="replacement",
        quota_policy=policy,
        confirm_unavailable=False,
        unavailable_reason="",
        reason=payload["reason"],
        digests=derive_plan_change_digests(
            key,
            operation="subscription.change",
            requester_id=actor.pk,
            target_id=source.pk,
            request_payload=payload,
        ),
        request_id=uuid.uuid4(),
    )


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
