import importlib
import uuid
from unittest.mock import patch

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django_redis import get_redis_connection

from apps.admin_rbac.models import ApprovalRequest
from apps.admin_rbac.permissions import resolve_admin_context
from apps.plans.models import Subscription
from apps.plans.subscription_services import terminate_subscription
from apps.quotas.models import QuotaAccount, QuotaHold, QuotaLedgerEntry
from apps.quotas.services import consume_hold, freeze_quota, release_hold, replay_account
from apps.users.models import User
from tests.test_quotas import fund
from tests.test_subscriptions import PASSWORD, published_plan
from tests.test_subscriptions_postgres import parallel

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_services():
    if connection.vendor != "postgresql":
        pytest.skip("??? scripts/test-quotas.* ??? PostgreSQL/Redis ???")
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


def provision():
    admin = User.objects.create_superuser(phone="13900139000", nickname="?????", password=PASSWORD)
    user = User.objects.create_user(
        phone="13800138000",
        nickname="????",
        password=PASSWORD,
        approval_status=User.ApprovalStatus.APPROVED,
    )
    plan, _ = published_plan(admin, code=f"quota-pg-{uuid.uuid4().hex[:8]}", trial=True)
    from apps.plans.subscription_services import grant_trial

    subscription = grant_trial(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=plan.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="detection_points")
    return admin, user, subscription, fund(account, admin, amount=20)


def test_postgresql_concurrent_freezes_have_contiguous_ledger_sequences():
    _, _, _, account = provision()
    results = parallel(
        lambda: freeze_quota(
            account_id=account.pk,
            amount=2,
            business_type="concurrent_task",
            business_id=uuid.uuid4(),
            idempotency_key="concurrent-freeze-key-0001",
            request_id=uuid.uuid4(),
        ),
        lambda: freeze_quota(
            account_id=account.pk,
            amount=3,
            business_type="concurrent_task",
            business_id=uuid.uuid4(),
            idempotency_key="concurrent-freeze-key-0002",
            request_id=uuid.uuid4(),
        ),
    )
    assert all(isinstance(item, QuotaHold) for item in results)
    account.refresh_from_db()
    sequences = list(account.ledger_entries.values_list("sequence", flat=True))
    assert sequences == list(range(1, len(sequences) + 1))
    assert replay_account(account).ledger_sequence == account.ledger_sequence


def test_postgresql_different_keys_cannot_freeze_same_business_target():
    _, _, _, account = provision()
    business_id = uuid.uuid4()
    results = parallel(
        lambda: freeze_quota(
            account_id=account.pk,
            amount=1,
            business_type="same_task",
            business_id=business_id,
            idempotency_key="same-target-freeze-key-0001",
            request_id=uuid.uuid4(),
        ),
        lambda: freeze_quota(
            account_id=account.pk,
            amount=1,
            business_type="same_task",
            business_id=business_id,
            idempotency_key="same-target-freeze-key-0002",
            request_id=uuid.uuid4(),
        ),
    )
    assert sum(isinstance(item, QuotaHold) for item in results) == 1
    assert (
        QuotaHold.objects.filter(
            account=account, business_type="same_task", business_id=business_id
        ).count()
        == 1
    )


LEDGER_COLUMNS = (
    "id,account_id,hold_id,user_id,subscription_id,quota_type,sequence,action,"
    "available_before,available_delta,available_after,frozen_before,frozen_delta,"
    "frozen_after,account_version_before,account_version_after,business_type,"
    "business_id,safe_reason,actor_id,request_id,idempotency_key_version,"
    "idempotency_key_digest,idempotency_scope_digest,request_digest,created_at"
)


def raw_clone_ledger(entry, *, sequence_offset=0, before_offset=0, after_offset=0):
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO quota_ledger_entries ({LEDGER_COLUMNS}) "
            "SELECT %s,account_id,hold_id,user_id,subscription_id,quota_type,"
            "sequence+%s,action,available_before+%s,available_delta,"
            "available_after+%s,frozen_before,frozen_delta,frozen_after,"
            "account_version_before,account_version_after,business_type,business_id,"
            "safe_reason,actor_id,%s,idempotency_key_version,%s,%s,%s,NOW() "
            "FROM quota_ledger_entries WHERE id=%s",
            [
                uuid.uuid4(),
                sequence_offset,
                before_offset,
                after_offset,
                uuid.uuid4(),
                uuid.uuid4().hex + uuid.uuid4().hex,
                uuid.uuid4().hex + uuid.uuid4().hex,
                uuid.uuid4().hex + uuid.uuid4().hex,
                entry.pk,
            ],
        )


def test_postgresql_raw_sql_rejects_sequence_gap_reuse_and_before_after_mismatch():
    _, _, _, account = provision()
    entry = account.last_ledger_entry
    for kwargs in (
        {"sequence_offset": 2},
        {"sequence_offset": 0},
        {"sequence_offset": 1, "before_offset": 1, "after_offset": 1},
        {"sequence_offset": 1, "after_offset": 1},
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            raw_clone_ledger(entry, **kwargs)


def test_postgresql_raw_sql_guards_account_hold_and_ledger_evidence():
    _, _, _, account = provision()
    hold = freeze_quota(
        account_id=account.pk,
        amount=2,
        business_type="guard_task",
        business_id=uuid.uuid4(),
        idempotency_key="guard-freeze-key-0001",
        request_id=uuid.uuid4(),
    )
    entry = account.ledger_entries.order_by("-sequence").first()
    statements = (
        ("UPDATE quota_accounts SET available=available+1 WHERE id=%s", account.pk),
        (
            "UPDATE quota_accounts SET entitlement_amount=entitlement_amount+1 WHERE id=%s",
            account.pk,
        ),
        ("DELETE FROM quota_accounts WHERE id=%s", account.pk),
        ("UPDATE quota_ledger_entries SET safe_reason='tampered' WHERE id=%s", entry.pk),
        ("DELETE FROM quota_ledger_entries WHERE id=%s", entry.pk),
        ("DELETE FROM quota_holds WHERE id=%s", hold.pk),
    )
    for sql, identifier in statements:
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, [identifier])


def test_postgresql_settled_hold_cannot_be_restored():
    _, _, _, account = provision()
    hold = freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="terminal_task",
        business_id=uuid.uuid4(),
        idempotency_key="terminal-freeze-key-0001",
        request_id=uuid.uuid4(),
    )
    release_hold(
        hold_id=hold.pk,
        amount=1,
        idempotency_key="terminal-release-key-0001",
        request_id=uuid.uuid4(),
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quota_holds SET status='open', released_amount=0,"
                "settled_at=NULL,version=version+1 WHERE id=%s",
                [hold.pk],
            )


def test_postgresql_hold_can_consume_and_release_after_subscription_termination():
    admin, _, subscription, account = provision()
    first = freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="post_termination",
        business_id=uuid.uuid4(),
        idempotency_key="post-termination-freeze-0001",
        request_id=uuid.uuid4(),
    )
    second = freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="post_termination",
        business_id=uuid.uuid4(),
        idempotency_key="post-termination-freeze-0002",
        request_id=uuid.uuid4(),
    )
    terminate_subscription(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        subscription_id=subscription.pk,
        expected_version=subscription.version,
        reason="???????",
        request_id=uuid.uuid4(),
    )
    consume_hold(
        hold_id=first.pk,
        amount=1,
        idempotency_key="post-termination-consume-0001",
        request_id=uuid.uuid4(),
    )
    release_hold(
        hold_id=second.pk,
        amount=1,
        idempotency_key="post-termination-release-0001",
        request_id=uuid.uuid4(),
    )
    assert QuotaHold.objects.filter(pk__in=(first.pk, second.pk), status="settled").count() == 2


def test_postgresql_quota_initialization_failure_rolls_back_subscription():
    admin = User.objects.create_superuser(phone="13900139000", nickname="?????", password=PASSWORD)
    user = User.objects.create_user(
        phone="13800138000",
        nickname="????",
        password=PASSWORD,
        approval_status=User.ApprovalStatus.APPROVED,
    )
    plan, _ = published_plan(admin, code="quota-rollback", trial=True)
    from apps.plans.subscription_services import grant_trial

    with (
        patch(
            "apps.quotas.services.QuotaLedgerEntry.objects.create",
            side_effect=RuntimeError("quota ledger failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        grant_trial(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            user_id=user.pk,
            expected_status_version=user.status_version,
            plan_id=plan.pk,
            opening_note="",
            request_id=uuid.uuid4(),
        )
    assert not Subscription.objects.filter(user=user).exists()
    assert not QuotaAccount.objects.filter(user=user).exists()


def test_postgresql_backfill_is_idempotent():
    _, _, subscription, _ = provision()
    migration = importlib.import_module(
        "apps.quotas.migrations.0003_backfill_subscription_accounts"
    )
    with connection.schema_editor(atomic=False) as schema_editor:
        migration.backfill_accounts(django_apps, schema_editor)
        migration.backfill_accounts(django_apps, schema_editor)
    assert QuotaAccount.objects.filter(subscription=subscription).count() == 5
    assert QuotaLedgerEntry.objects.filter(subscription=subscription).count() >= 5


def test_postgresql_quota_adjustment_two_person_executes_exactly_once():
    from rest_framework.test import APIClient

    from tests.admin_session_helpers import authenticate_admin_client

    requester, _, _, account = provision()
    approver = User.objects.create_superuser(
        phone="13700137000", nickname="?????", password=PASSWORD
    )
    response = authenticate_admin_client(APIClient(), requester).post(
        f"/api/v1/admin/quota-accounts/{account.pk}/adjust/compensate",
        {"expected_version": account.version, "amount": 2, "reason": "????"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="approval-compensate-" + "key-0001",
    )
    assert response.status_code == 202
    approval = ApprovalRequest.objects.get(pk=response.json()["data"]["approval_id"])
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
    assert sorted(item.status_code for item in responses) == [200, 409]
    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.EXECUTED
    assert QuotaLedgerEntry.objects.filter(account=account, action="compensate").count() == 1
