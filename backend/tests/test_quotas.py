import uuid
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.admin_rbac.models import AuditEvent, RiskAction, RiskPolicy
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.risk_catalog import CONFIRM, RISK_ACTION_BY_KEY
from apps.plans.subscription_services import grant_trial, terminate_subscription
from apps.quotas.catalog import CURRENT_ACCOUNT_DEFINITIONS, snapshot_quota_values
from apps.quotas.exceptions import (
    QuotaBusinessAlreadyHeld,
    QuotaHoldStateConflict,
)
from apps.quotas.idempotency import derive_idempotency_digests
from apps.quotas.models import QuotaAccount, QuotaHold, QuotaLedgerEntry
from apps.quotas.services import (
    adjust_quota_account,
    consume_hold,
    freeze_quota,
    initialize_subscription_accounts,
    release_hold,
    replay_account,
)
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client
from tests.test_subscriptions import PASSWORD, published_plan


@pytest.fixture(autouse=True)
def seed_catalogs(db):
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def provision(*, phone="13800138000"):
    admin = User.objects.create_superuser(phone="13900139000", nickname="?????", password=PASSWORD)
    user = User.objects.create_user(
        phone=phone,
        nickname="????",
        password=PASSWORD,
    )
    plan, _ = published_plan(admin, code=f"quota-{uuid.uuid4().hex[:8]}", trial=True)
    subscription = grant_trial(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=plan.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    return admin, user, subscription


def fund(account, admin, *, amount=5):
    digests = derive_idempotency_digests(
        f"test-fund-{account.pk}",
        operation="grant",
        user_id=account.user_id,
        account_id=account.pk,
        business_type="quota_adjustment",
        business_id=account.pk,
        request_payload={"amount": amount, "reason": "??????"},
    )
    adjust_quota_account(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        account_id=account.pk,
        expected_version=account.version,
        action="grant",
        amount=amount,
        reason="??????",
        digests=digests,
        request_id=uuid.uuid4(),
    )
    account.refresh_from_db()
    return account


def add_customer_quota(subscription, admin, *, quota_type, amount):
    snapshot = deepcopy(subscription.entitlement_snapshot)
    snapshot.setdefault("limits", {})[quota_type] = amount
    type(subscription).objects.filter(pk=subscription.pk).update(entitlement_snapshot=snapshot)
    subscription.refresh_from_db()
    initialize_subscription_accounts(
        subscription=subscription,
        request_id=uuid.uuid4(),
        actor=admin,
    )
    account = QuotaAccount.objects.get(
        subscription=subscription,
        quota_type=quota_type,
    )
    if account.available < amount:
        grant_amount = amount - account.available
        reason = "测试补充自然单位额度"
        digests = derive_idempotency_digests(
            f"test-natural-quota-{account.pk}",
            operation="grant",
            user_id=account.user_id,
            account_id=account.pk,
            business_type="quota_adjustment",
            business_id=account.pk,
            request_payload={"amount": grant_amount, "reason": reason},
        )
        adjust_quota_account(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            account_id=account.pk,
            expected_version=account.version,
            action=QuotaLedgerEntry.Action.GRANT,
            amount=grant_amount,
            reason=reason,
            digests=digests,
            request_id=uuid.uuid4(),
        )
        account.refresh_from_db()
    return account


@pytest.mark.django_db
def test_subscription_initializes_all_current_accounts_even_zero():
    _, _, subscription = provision()
    accounts = QuotaAccount.objects.filter(subscription=subscription)
    expected_types = {
        item.key
        for item in CURRENT_ACCOUNT_DEFINITIONS
        if item.source_limit_key in subscription.entitlement_snapshot["limits"]
    }
    assert set(accounts.values_list("quota_type", flat=True)) == expected_types
    assert accounts.count() == len(expected_types)
    for account in accounts:
        assert account.ledger_sequence == 1
        assert account.last_ledger_entry.sequence == 1
        assert account.last_ledger_entry.action == "initialize"
        assert replay_account(account).available == account.entitlement_amount


@pytest.mark.parametrize(
    "bad_value",
    [True, -1, 2**63],
)
def test_snapshot_rejects_bool_negative_and_overflow(bad_value):
    limits = {item.source_limit_key: 0 for item in CURRENT_ACCOUNT_DEFINITIONS}
    limits.update(
        {
            "keyword_regenerations_per_cycle": 0,
            "distillation_regenerations_per_cycle": 0,
            "question_bank_regenerations_per_cycle": 0,
            "strategy_regenerations_per_cycle": 0,
            "outline_regenerations_per_cycle": 0,
            "local_ai_edits_per_cycle": 0,
            "quality_rechecks_per_cycle": 0,
        }
    )
    limits["detection_points"] = bad_value
    with pytest.raises(ValueError):
        snapshot_quota_values({"limits": limits})


def test_snapshot_rejects_unknown_or_missing_catalog_key():
    with pytest.raises(ValueError):
        snapshot_quota_values({"limits": {"unknown": 1}})


def test_immutable_snapshot_keeps_only_quota_keys_present_at_publish_time():
    limits = {item.source_limit_key: 0 for item in CURRENT_ACCOUNT_DEFINITIONS}
    limits.pop("video_credits")
    limits.update(
        {
            "keyword_regenerations_per_cycle": 0,
            "distillation_regenerations_per_cycle": 0,
            "question_bank_regenerations_per_cycle": 0,
            "strategy_regenerations_per_cycle": 0,
            "outline_regenerations_per_cycle": 0,
            "local_ai_edits_per_cycle": 0,
            "quality_rechecks_per_cycle": 0,
        }
    )

    values = snapshot_quota_values({"limits": limits})

    assert "video_credits" not in values
    limits.pop("image_credits")
    assert "image_credits" not in snapshot_quota_values({"limits": limits})


@pytest.mark.django_db
def test_initialization_is_idempotent():
    admin, _, subscription = provision()
    before = (QuotaAccount.objects.count(), QuotaLedgerEntry.objects.count())
    initialize_subscription_accounts(
        subscription=subscription, request_id=uuid.uuid4(), actor=admin
    )
    assert (QuotaAccount.objects.count(), QuotaLedgerEntry.objects.count()) == before


@pytest.mark.django_db
def test_freeze_consume_release_and_replay():
    admin, _, subscription = provision()
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="geo_detection_runs")
    account = fund(account, admin)
    amount = min(account.available, 2)
    hold = freeze_quota(
        account_id=account.pk,
        amount=amount,
        business_type="test_task",
        business_id=uuid.uuid4(),
        idempotency_key="freeze-key-unique-0001",
        request_id=uuid.uuid4(),
    )
    consume_hold(
        hold_id=hold.pk,
        amount=1,
        idempotency_key="consume-key-" + "unique-0001",
        request_id=uuid.uuid4(),
    )
    if amount > 1:
        release_hold(
            hold_id=hold.pk,
            amount=amount - 1,
            idempotency_key="release-key-unique-0001",
            request_id=uuid.uuid4(),
        )
    hold.refresh_from_db()
    account.refresh_from_db()
    assert hold.status == QuotaHold.Status.SETTLED
    assert replay_account(account).frozen == 0
    with pytest.raises(QuotaHoldStateConflict):
        release_hold(
            hold_id=hold.pk,
            amount=1,
            idempotency_key="release-key-unique-0002",
            request_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_video_seconds_use_existing_freeze_consume_release_ledger():
    admin, _, subscription = provision()
    account = add_customer_quota(
        subscription,
        admin,
        quota_type="video_credits",
        amount=0,
    )
    account = fund(account, admin, amount=10)
    business_id = uuid.uuid4()

    hold = freeze_quota(
        account_id=account.pk,
        amount=10,
        business_type="video_generation",
        business_id=business_id,
        idempotency_key="video-freeze-key-unique-0001",
        request_id=uuid.uuid4(),
    )
    consume_hold(
        hold_id=hold.pk,
        amount=5,
        idempotency_key="video-consume-key-unique-0001",
        request_id=uuid.uuid4(),
    )
    release_hold(
        hold_id=hold.pk,
        amount=5,
        idempotency_key="video-release-key-unique-0001",
        request_id=uuid.uuid4(),
    )

    hold.refresh_from_db()
    account.refresh_from_db()
    assert hold.status == QuotaHold.Status.SETTLED
    assert hold.consumed_amount == 5
    assert hold.released_amount == 5
    assert account.available == 5
    assert account.frozen == 0
    replay = replay_account(account)
    assert (replay.available, replay.frozen) == (5, 0)


@pytest.mark.django_db
def test_different_idempotency_key_cannot_duplicate_business_hold():
    admin, _, subscription = provision()
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="geo_detection_runs")
    business_id = uuid.uuid4()
    account = fund(account, admin)
    freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="test_task",
        business_id=business_id,
        idempotency_key="freeze-business-key-0001",
        request_id=uuid.uuid4(),
    )
    with pytest.raises(QuotaBusinessAlreadyHeld):
        freeze_quota(
            account_id=account.pk,
            amount=1,
            business_type="test_task",
            business_id=business_id,
            idempotency_key="freeze-business-key-0002",
            request_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_existing_hold_can_settle_after_subscription_terminated():
    admin, _, subscription = provision()
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="geo_detection_runs")
    account = fund(account, admin)
    hold = freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="test_task",
        business_id=uuid.uuid4(),
        idempotency_key="freeze-after-end-key-0001",
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
    release_hold(
        hold_id=hold.pk,
        amount=1,
        idempotency_key="release-after-end-key-0001",
        request_id=uuid.uuid4(),
    )
    hold.refresh_from_db()
    assert hold.status == QuotaHold.Status.SETTLED


@pytest.mark.django_db
def test_existing_hold_can_consume_after_subscription_time_window_ends():
    admin, _, subscription = provision()
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="geo_detection_runs")
    account = fund(account, admin)
    hold = freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="test_task",
        business_id=uuid.uuid4(),
        idempotency_key="freeze-expired-key-0001",
        request_id=uuid.uuid4(),
    )
    with patch(
        "apps.quotas.services.timezone.now",
        return_value=subscription.ends_at + timedelta(seconds=1),
    ):
        consume_hold(
            hold_id=hold.pk,
            amount=1,
            idempotency_key="consume-expired-key-0001",
            request_id=uuid.uuid4(),
        )
    hold.refresh_from_db()
    assert hold.status == QuotaHold.Status.SETTLED


@pytest.mark.django_db
def test_manual_deduct_does_not_reduce_frozen_and_grants_do_not_change_entitlement():
    admin, _, subscription = provision()
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="geo_detection_runs")
    initial_entitlement = account.entitlement_amount
    context = resolve_admin_context(admin)
    for index, action in enumerate(("grant", "compensate", "manual_deduct"), start=1):
        account.refresh_from_db()
        before_frozen = account.frozen
        digests = derive_idempotency_digests(
            f"adjust-key-unique-{index:04d}",
            operation=action,
            user_id=account.user_id,
            account_id=account.pk,
            business_type="quota_adjustment",
            business_id=account.pk,
            request_payload={"amount": 1, "reason": "??????"},
        )
        adjust_quota_account(
            requester=admin,
            admin_context=context,
            account_id=account.pk,
            expected_version=account.version,
            action=action,
            amount=1,
            reason="??????",
            digests=digests,
            request_id=uuid.uuid4(),
        )
        account.refresh_from_db()
        assert account.frozen == before_frozen
        assert account.entitlement_amount == initial_entitlement


@pytest.mark.django_db
def test_user_quota_apis_do_not_leak_business_or_idempotency_fields():
    admin, user, subscription = provision()
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="geo_detection_runs")
    account = fund(account, admin)
    freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="private_task",
        business_id=uuid.uuid4(),
        idempotency_key="private-business-key-0001",
        request_id=uuid.uuid4(),
    )
    client = APIClient()
    client.force_authenticate(user)
    accounts = client.get("/api/v1/quotas")
    ledger = client.get("/api/v1/quota-ledger")
    assert accounts.status_code == ledger.status_code == 200
    serialized = str(ledger.json())
    for forbidden in (
        "business_id",
        "private_task",
        "idempotency",
        "request_digest",
        "safe_reason",
        "actor_id",
        "entitlement_snapshot",
        "sanitized_payload",
        "internal_actor",
    ):
        assert forbidden not in serialized


@pytest.mark.django_db
def test_customer_quota_center_exposes_only_natural_unit_accounts_and_safe_ledger():
    admin, user, subscription = provision()
    account = add_customer_quota(
        subscription,
        admin,
        quota_type="geo_detection_runs",
        amount=5,
    )
    hold = freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="geo_detection_job",
        business_id=uuid.uuid4(),
        idempotency_key="customer-center-freeze-0001",
        request_id=uuid.uuid4(),
    )
    consume_hold(
        hold_id=hold.pk,
        amount=1,
        idempotency_key="customer-center-consume-0001",
        request_id=uuid.uuid4(),
    )

    client = APIClient()
    client.force_authenticate(user)
    accounts = client.get("/api/v1/quotas")
    ledger = client.get("/api/v1/quota-ledger?page=1&page_size=20")

    assert accounts.status_code == ledger.status_code == 200
    rows = accounts.json()["data"]["accounts"]
    expected_types = {item.key for item in CURRENT_ACCOUNT_DEFINITIONS if item.customer_visible}
    assert {row["quota_type"] for row in rows} == expected_types
    geo_row = next(row for row in rows if row["quota_type"] == "geo_detection_runs")
    assert geo_row["display_name"] == "GEO 综合检测"
    assert geo_row["unit_display_name"] == "次"
    assert geo_row["total_amount"] == 5
    assert geo_row["used_amount"] == 1
    assert geo_row["remaining_amount"] == 4

    entries = ledger.json()["data"]["results"]
    assert entries
    assert {entry["quota_type"] for entry in entries} <= expected_types
    consume_entry = next(entry for entry in entries if entry["action"] == "consume")
    assert consume_entry["action_name"] == "任务已完成"
    assert consume_entry["change_amount"] == -1
    serialized = str(entries)
    for forbidden in ("business_type", "business_id", "safe_reason", "request_digest"):
        assert forbidden not in serialized


@pytest.mark.django_db
def test_admin_quota_accounts_include_plan_usage_and_latest_adjustment():
    admin, _, subscription = provision()
    account = add_customer_quota(
        subscription,
        admin,
        quota_type="geo_detection_runs",
        amount=5,
    )
    hold = freeze_quota(
        account_id=account.pk,
        amount=2,
        business_type="geo_detection_job",
        business_id=uuid.uuid4(),
        idempotency_key="admin-center-freeze-0001",
        request_id=uuid.uuid4(),
    )
    consume_hold(
        hold_id=hold.pk,
        amount=2,
        idempotency_key="admin-center-consume-0001",
        request_id=uuid.uuid4(),
    )
    account.refresh_from_db()
    reason = "客户退款额度返还"
    digests = derive_idempotency_digests(
        "admin-center-refund-0001",
        operation="refund",
        user_id=account.user_id,
        account_id=account.pk,
        business_type="quota_adjustment",
        business_id=account.pk,
        request_payload={"amount": 3, "reason": reason},
    )
    adjust_quota_account(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        account_id=account.pk,
        expected_version=account.version,
        action=QuotaLedgerEntry.Action.REFUND,
        amount=3,
        reason=reason,
        digests=digests,
        request_id=uuid.uuid4(),
    )

    response = authenticate_admin_client(APIClient(), admin).get(
        "/api/v1/admin/quota-accounts?quota_type=geo_detection_runs"
    )

    assert response.status_code == 200
    row = response.json()["data"]["results"][0]
    assert row["plan_id"] == str(subscription.plan_id)
    assert row["plan_name"] == subscription.plan.name
    assert row["plan_version_no"] == subscription.plan_version_no
    assert row["used_amount"] == 2
    assert row["total_amount"] == 8
    assert row["remaining_amount"] == 6
    assert row["last_adjustment"]["action"] == "refund"
    assert row["last_adjustment"]["action_name"] == "额度返还"
    assert row["last_adjustment"]["reason"] == reason


@pytest.mark.django_db
def test_admin_refund_endpoint_requires_reason_and_appends_refund_ledger():
    admin, _, subscription = provision()
    account = add_customer_quota(
        subscription,
        admin,
        quota_type="article_generations",
        amount=2,
    )
    client = authenticate_admin_client(APIClient(), admin)
    path = f"/api/v1/admin/quota-accounts/{account.pk}/adjust/refund"

    invalid = client.post(
        path,
        {
            "expected_version": account.version,
            "amount": 1,
            "reason": "",
            "confirmed": True,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="refund-endpoint-invalid-0001",
    )
    assert invalid.status_code == 422

    response = client.post(
        path,
        {
            "expected_version": account.version,
            "amount": 2,
            "reason": "订单退款后返还额度",
            "confirmed": True,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="refund-endpoint-valid-0001",
    )
    assert response.status_code == 200
    account.refresh_from_db()
    assert account.available == 4
    entry = account.ledger_entries.latest("created_at")
    assert entry.action == QuotaLedgerEntry.Action.REFUND
    assert entry.safe_reason == "订单退款后返还额度"
    assert entry.actor_id == admin.pk


@pytest.mark.django_db
def test_direct_adjustment_keeps_idempotency_secret_out_of_response_and_audit(caplog):
    requester, _, subscription = provision()
    User.objects.create_superuser(phone="13700137000", nickname="?????", password=PASSWORD)
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="geo_detection_runs")
    client_header_value = "repeatable-test-request"
    response = authenticate_admin_client(APIClient(), requester).post(
        f"/api/v1/admin/quota-accounts/{account.pk}/adjust/grant",
        {
            "expected_version": account.version,
            "amount": 1,
            "reason": "????",
            "confirmed": True,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=client_header_value,
    )
    assert response.status_code == 200
    assert client_header_value not in str(response.json())
    assert client_header_value not in caplog.text
    event = AuditEvent.objects.get(action_key="quota.grant", outcome="executed")
    assert client_header_value not in str(
        {"safe_before": event.safe_before, "safe_after": event.safe_after}
    )


@pytest.mark.django_db
def test_risk_catalog_uses_direct_confirmation_and_has_no_reset():
    for key in (
        "quota.grant",
        "quota.compensate",
        "quota.refund",
        "quota.manual_deduct",
    ):
        definition = RISK_ACTION_BY_KEY[key]
        action = RiskAction.objects.get(key=key)
        policy = RiskPolicy.objects.get(action=action)
        assert definition.supported_modes == (CONFIRM,)
        assert definition.default_mode == definition.minimum_mode == CONFIRM
        assert action.minimum_mode == policy.current_mode == CONFIRM
    assert "quota.reset" not in RISK_ACTION_BY_KEY
    assert not RiskAction.objects.filter(key="quota.reset").exists()


def test_no_public_reset_route():
    for path in (
        "/api/v1/quotas/reset",
        "/api/v1/admin/quota-accounts/reset",
        "/api/v1/admin/quota-reset",
    ):
        with pytest.raises(Resolver404):
            resolve(path)


def test_models_support_subject_cycle_without_mutable_status_fields():
    names = {field.name for field in QuotaAccount._meta.fields}
    assert "subject" in names
    assert "status" not in names
    assert "expires_at" not in names
    assert "subject_cycle" in {value for value, _ in QuotaAccount.Scope.choices}


@override_settings(QUOTA_IDEMPOTENCY_HMAC_KEY="isolated-test-" + "quota-key-0123456789abcdef")
def test_hmac_scope_changes_operation_account_and_business_target():
    common = {
        "user_id": uuid.uuid4(),
        "account_id": uuid.uuid4(),
        "business_type": "task",
        "business_id": uuid.uuid4(),
        "request_payload": {"amount": 1},
    }
    first = derive_idempotency_digests("same-raw-key-0001", operation="freeze", **common)
    changed = derive_idempotency_digests("same-raw-key-0001", operation="consume", **common)
    assert first.scope_digest != changed.scope_digest
    assert first.request_digest == changed.request_digest
