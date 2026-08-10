import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.urls import Resolver404, resolve
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admin_rbac.models import ApprovalRequest, RiskAction, RiskPolicy
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.risk_catalog import RISK_ACTION_BY_KEY, TWO_PERSON
from apps.plans.change_idempotency import derive_plan_change_digests
from apps.plans.change_services import (
    SubscriptionChangeActiveHolds,
    SubscriptionChangeAlreadyExists,
    cancel_scheduled_change,
    execute_subscription_change,
)
from apps.plans.models import Subscription, SubscriptionChange
from apps.plans.subscription_services import activate_application, grant_trial
from apps.quotas.idempotency import derive_idempotency_digests
from apps.quotas.models import QuotaAccount, QuotaTransfer
from apps.quotas.services import adjust_quota_account, freeze_quota
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client
from tests.test_subscriptions import PASSWORD, application_for, published_plan


@pytest.fixture(autouse=True)
def seed_catalogs(db):
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def admin(phone="13900139000"):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def customer(phone="13800138000"):
    return User.objects.create_user(
        phone=phone,
        nickname="套餐变更用户",
        password=PASSWORD,
        approval_status=User.ApprovalStatus.APPROVED,
    )


def activate_formal(actor, user, *, code, valid_days=30):
    plan, version = published_plan(actor, code=code, valid_days=valid_days)
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
        opening_note="测试开通",
        request_id=uuid.uuid4(),
    )
    return subscription, plan, version


def change_digests(actor, source, payload, key=None, operation="subscription.change"):
    return derive_plan_change_digests(
        key or f"plan-change-{uuid.uuid4()}",
        operation=operation,
        requester_id=actor.pk,
        target_id=source.pk,
        request_payload=payload,
    )


def execute(actor, source, target_plan, target_version, *, change_type, policy="overwrite"):
    payload = {
        "target_plan_version_id": str(target_version.pk),
        "change_type": change_type,
        "quota_policy": policy,
        "confirm_unavailable": False,
        "unavailable_reason": "",
        "reason": "业务套餐调整",
    }
    return execute_subscription_change(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        source_subscription_id=source.pk,
        expected_version=source.version,
        target_plan_id=target_plan.pk,
        target_plan_version_id=target_version.pk,
        requested_type=change_type,
        quota_policy=policy,
        confirm_unavailable=False,
        unavailable_reason="",
        reason=payload["reason"],
        digests=change_digests(actor, source, payload),
        request_id=uuid.uuid4(),
    )


@pytest.mark.django_db
def test_catalog_and_routes_are_fixed_without_manual_execution_endpoint():
    for key in ("subscription.change", "subscription.change.cancel"):
        definition = RISK_ACTION_BY_KEY[key]
        action = RiskAction.objects.get(pk=key)
        policy = RiskPolicy.objects.get(action=action)
        assert definition.supported_modes == (TWO_PERSON,)
        assert definition.default_mode == definition.minimum_mode == TWO_PERSON
        assert action.supported_modes == [TWO_PERSON]
        assert policy.current_mode == TWO_PERSON
    expected = {
        "/api/v1/admin/subscriptions/00000000-0000-0000-0000-000000000001/change/preview",
        "/api/v1/admin/subscriptions/00000000-0000-0000-0000-000000000001/change",
        "/api/v1/admin/subscription-changes",
        "/api/v1/admin/subscription-changes/00000000-0000-0000-0000-000000000001",
        "/api/v1/admin/subscription-changes/00000000-0000-0000-0000-000000000001/cancel",
        "/api/v1/subscription/changes",
    }
    assert all(resolve(path) for path in expected)
    with pytest.raises(Resolver404):
        resolve("/api/v1/admin/subscription-changes/00000000-0000-0000-0000-000000000001/execute")


@pytest.mark.django_db
def test_replacement_executes_immediately_and_uses_real_source_chain():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="change-source")
    target_plan, target_version = published_plan(actor, code="change-target")
    old_end = source.ends_at
    change = execute(
        actor,
        source,
        target_plan,
        target_version,
        change_type=SubscriptionChange.ChangeType.REPLACEMENT,
    )
    source.refresh_from_db()
    target = change.target_subscription
    assert change.status == SubscriptionChange.Status.EXECUTED
    assert source.status == Subscription.Status.TERMINATED
    assert target.source_type == Subscription.SourceType.PLAN_CHANGE
    assert target.source_change == change
    assert target.source_application is None
    assert target.ends_at == old_end
    assert Subscription.objects.filter(user=user, status="active").count() == 1
    with pytest.raises(SubscriptionChangeAlreadyExists):
        execute(
            actor,
            source,
            target_plan,
            target_version,
            change_type=SubscriptionChange.ChangeType.REPLACEMENT,
        )


@pytest.mark.django_db
def test_renewal_is_only_scheduled_and_cancel_is_independently_idempotent():
    actor, user = admin(), customer()
    source, plan, version = activate_formal(actor, user, code="renew-source")
    change = execute(
        actor,
        source,
        plan,
        version,
        change_type=SubscriptionChange.ChangeType.RENEWAL,
    )
    assert change.status == SubscriptionChange.Status.SCHEDULED
    assert change.effective_at == source.ends_at
    assert not hasattr(change, "target_subscription")
    raw_payload = {"reason": "取消排期"}
    digests = change_digests(
        actor,
        change,
        raw_payload,
        operation="subscription.change.cancel",
    )
    cancelled = cancel_scheduled_change(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        change_id=change.pk,
        expected_version=change.version,
        reason=raw_payload["reason"],
        digests=digests,
        request_id=uuid.uuid4(),
    )
    replayed = cancel_scheduled_change(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        change_id=change.pk,
        expected_version=change.version,
        reason=raw_payload["reason"],
        digests=digests,
        request_id=uuid.uuid4(),
    )
    assert replayed.pk == cancelled.pk
    assert cancelled.status == SubscriptionChange.Status.CANCELLED
    assert cancelled.idempotency_key_digest != cancelled.cancellation_idempotency_key_digest


@pytest.mark.django_db
def test_trial_conversion_resets_window_and_anchor():
    actor, user = admin(), customer()
    trial_plan, _ = published_plan(actor, code="conversion-trial", trial=True)
    trial = grant_trial(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=trial_plan.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    target_plan, target_version = published_plan(actor, code="conversion-formal")
    before = timezone.now()
    change = execute(
        actor,
        trial,
        target_plan,
        target_version,
        change_type=SubscriptionChange.ChangeType.TRIAL_CONVERSION,
    )
    target = change.target_subscription
    assert before <= target.starts_at <= timezone.now()
    assert target.ends_at == target.starts_at + timedelta(days=target_version.valid_days)
    assert target.cycle_anchor_day == timezone.localtime(target.starts_at).day


@pytest.mark.django_db
def test_retain_creates_zero_entitlement_carryover_and_paired_transfer():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="retain-source")
    source_account = QuotaAccount.objects.get(
        subscription=source,
        quota_type="detection_points",
    )
    digests = derive_idempotency_digests(
        "retain-fund-request-0001",
        operation="grant",
        user_id=user.pk,
        account_id=source_account.pk,
        business_type="quota_adjustment",
        business_id=source_account.pk,
        request_payload={"amount": 4, "reason": "测试余额"},
    )
    adjust_quota_account(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        account_id=source_account.pk,
        expected_version=source_account.version,
        action="grant",
        amount=4,
        reason="测试余额",
        digests=digests,
        request_id=uuid.uuid4(),
    )
    target_plan, target_version = published_plan(actor, code="retain-target")
    change = execute(
        actor,
        source,
        target_plan,
        target_version,
        change_type=SubscriptionChange.ChangeType.REPLACEMENT,
        policy="retain",
    )
    source_account.refresh_from_db()
    carryover = QuotaAccount.objects.get(
        subscription=change.target_subscription,
        quota_type="detection_points",
        batch_type="carryover",
    )
    transfer = QuotaTransfer.objects.get(change=change, source_account=source_account)
    assert source_account.available == source_account.frozen == 0
    assert carryover.entitlement_amount == 0 and carryover.available == 4
    assert carryover.spendable_until == source.ends_at
    assert transfer.transfer_out_entry.available_delta == -4
    assert transfer.transfer_in_entry.available_delta == 4


@pytest.mark.django_db
def test_open_hold_blocks_change_without_automatic_release():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="hold-source")
    account = QuotaAccount.objects.get(subscription=source, quota_type="detection_points")
    digests = derive_idempotency_digests(
        "hold-block-fund-0001",
        operation="grant",
        user_id=user.pk,
        account_id=account.pk,
        business_type="quota_adjustment",
        business_id=account.pk,
        request_payload={"amount": 1, "reason": "测试冻结"},
    )
    adjust_quota_account(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        account_id=account.pk,
        expected_version=account.version,
        action="grant",
        amount=1,
        reason="测试冻结",
        digests=digests,
        request_id=uuid.uuid4(),
    )
    freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="change_race",
        business_id=uuid.uuid4(),
        idempotency_key="hold-block-freeze-0001",
        request_id=uuid.uuid4(),
    )
    target_plan, target_version = published_plan(actor, code="hold-target")
    with pytest.raises(SubscriptionChangeActiveHolds):
        execute(
            actor,
            source,
            target_plan,
            target_version,
            change_type=SubscriptionChange.ChangeType.REPLACEMENT,
        )
    source.refresh_from_db()
    account.refresh_from_db()
    assert source.status == Subscription.Status.ACTIVE
    assert account.frozen == 1


@pytest.mark.django_db
def test_change_api_stores_only_derived_idempotency_and_blocks_second_pending():
    requester, approver, user = admin(), admin("13700137000"), customer()
    source, _, _ = activate_formal(requester, user, code="api-source")
    target_plan, target_version = published_plan(requester, code="api-target")
    del target_plan, approver
    client = authenticate_admin_client(APIClient(), requester)
    raw_key = "plan-change-api-key-0001"
    body = {
        "expected_version": source.version,
        "target_plan_version_id": str(target_version.pk),
        "change_type": "replacement",
        "quota_policy": "overwrite",
        "reason": "API 变更",
    }
    response = client.post(
        f"/api/v1/admin/subscriptions/{source.pk}/change",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=raw_key,
    )
    assert response.status_code == 202
    approval = ApprovalRequest.objects.get(pk=response.json()["data"]["approval_id"])
    assert approval.action_key == "subscription.change"
    assert raw_key not in str(approval.sanitized_payload)
    assert approval.sanitized_payload["idempotency_key_digest"]
    conflict = client.post(
        f"/api/v1/admin/subscriptions/{source.pk}/change",
        {**body, "reason": "不同请求"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="plan-change-api-key-0002",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "APPROVAL_STATE_CONFLICT"


@pytest.mark.django_db
@pytest.mark.django_db
def test_cancel_change_api_blocks_second_pending_request():
    requester, approver, user = admin(), admin("13700137001"), customer()
    source, plan, version = activate_formal(requester, user, code="api-cancel-source")
    del approver
    change = execute(
        requester,
        source,
        plan,
        version,
        change_type=SubscriptionChange.ChangeType.RENEWAL,
    )
    client = authenticate_admin_client(APIClient(), requester)
    url = f"/api/v1/admin/subscription-changes/{change.pk}/cancel"
    first = client.post(
        url,
        {"expected_version": change.version, "reason": "客户取消续费"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="plan-change-cancel-api-key-0001",
    )
    assert first.status_code == 202
    approval = ApprovalRequest.objects.get(pk=first.json()["data"]["approval_id"])
    assert approval.action_key == "subscription.change.cancel"
    assert "plan-change-cancel-api-key-0001" not in str(approval.sanitized_payload)

    conflict = client.post(
        url,
        {"expected_version": change.version, "reason": "另一项取消原因"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="plan-change-cancel-api-key-0002",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "APPROVAL_STATE_CONFLICT"


def test_user_change_api_exposes_no_internal_payload_or_digests():
    actor, user = admin(), customer()
    source, plan, version = activate_formal(actor, user, code="user-change")
    execute(actor, source, plan, version, change_type=SubscriptionChange.ChangeType.RENEWAL)
    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/v1/subscription/changes")
    assert response.status_code == 200
    text = str(response.json())
    for forbidden in (
        "idempotency",
        "request_digest",
        "entitlement_digest",
        "entitlement_snapshot",
        "sanitized_payload",
        "business_id",
        "batch_type",
        "source_change",
    ):
        assert forbidden not in text
