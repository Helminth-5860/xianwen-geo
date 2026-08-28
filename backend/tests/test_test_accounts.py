import uuid

import pytest
from rest_framework.test import APIClient

from apps.admin_rbac.models import AuditEvent
from apps.plans.models import Plan, Subscription
from apps.plans.subscription_services import (
    current_subscription,
    effective_entitlement_snapshot,
)
from apps.quotas.models import QuotaAccount, QuotaLedgerEntry
from apps.quotas.services import consume_hold, freeze_quota
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


def _super_admin():
    return User.objects.create_superuser(
        phone="13900139000",
        nickname="超级管理员",
        password=PASSWORD,
    )


def _user():
    return User.objects.create_user(
        phone="15360264519",
        nickname="内部测试用户",
        password=PASSWORD,
    )


@pytest.mark.django_db
def test_only_super_admin_can_toggle_test_account_and_change_is_audited():
    actor = _super_admin()
    user = _user()
    endpoint = f"/api/v1/admin/users/{user.pk}/test-account"
    payload = {"enabled": True, "confirmed": True, "current_password": PASSWORD}

    ordinary_client = APIClient()
    ordinary_client.force_authenticate(user)
    assert ordinary_client.post(endpoint, payload, format="json").status_code == 403
    user.refresh_from_db()
    assert user.is_test_account is False

    admin_client = authenticate_admin_client(APIClient(), actor)
    response = admin_client.post(endpoint, payload, format="json")

    assert response.status_code == 200
    assert response.json()["data"]["is_test_account"] is True
    user.refresh_from_db()
    assert user.is_test_account is True
    subscription = current_subscription(user)
    assert subscription is not None
    assert subscription.source_type == Subscription.SourceType.INTERNAL_TEST
    assert subscription.plan.code == Plan.INTERNAL_TEST_CODE
    assert AuditEvent.objects.filter(
        actor=actor,
        subject=user,
        action_key="user.test_account.set",
        outcome="succeeded",
    ).exists()

    disabled = admin_client.post(
        endpoint,
        {"enabled": False, "confirmed": True, "current_password": PASSWORD},
        format="json",
    )
    assert disabled.status_code == 200
    user.refresh_from_db()
    subscription.refresh_from_db()
    assert user.is_test_account is False
    assert subscription.status == Subscription.Status.TERMINATED


@pytest.mark.django_db
def test_test_account_has_full_entitlements_and_quota_settlement_does_not_deduct():
    actor = _super_admin()
    user = _user()
    client = authenticate_admin_client(APIClient(), actor)
    endpoint = f"/api/v1/admin/users/{user.pk}/test-account"
    response = client.post(
        endpoint,
        {"enabled": True, "confirmed": True, "current_password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200

    user.refresh_from_db()
    subscription = current_subscription(user)
    assert subscription is not None
    snapshot = effective_entitlement_snapshot(subscription)
    limits = snapshot["limits"]
    assert limits["subject_active_limit"] >= 1_000_000
    assert limits["keyword_generation_limit"] >= 1_000_000
    assert limits["question_bank_limit"] >= 1_000_000
    assert limits["detection_points"] > 1_000_000
    assert limits["article_credits"] > 1_000_000
    assert limits["image_credits"] > 1_000_000
    assert limits["video_credits"] > 1_000_000
    assert limits["report_export_enabled"] is True
    assert snapshot["model_permissions"]

    account = QuotaAccount.objects.get(
        subscription=subscription,
        quota_type="detection_points",
        subject__isnull=True,
    )
    before = (account.available, account.frozen)
    hold = freeze_quota(
        account_id=account.pk,
        amount=25,
        business_type="test_detection",
        business_id=uuid.uuid4(),
        idempotency_key="test-account-no-deduction",
        request_id=uuid.uuid4(),
    )
    assert hold.is_test_account_bypass is True
    account.refresh_from_db()
    assert (account.available, account.frozen) == before

    consume_hold(
        hold_id=hold.pk,
        amount=25,
        idempotency_key="test-account-consume-no-deduction",
        request_id=uuid.uuid4(),
    )
    account.refresh_from_db()
    assert (account.available, account.frozen) == before
    ledger = QuotaLedgerEntry.objects.get(
        idempotency_key_digest__isnull=False,
        hold__group=hold,
        action=QuotaLedgerEntry.Action.CONSUME,
    )
    assert ledger.available_delta == 0
    assert ledger.frozen_delta == 0

    video_account = QuotaAccount.objects.get(
        subscription=subscription,
        quota_type="video_credits",
        subject__isnull=True,
    )
    video_before = (video_account.available, video_account.frozen)
    video_hold = freeze_quota(
        account_id=video_account.pk,
        amount=10,
        business_type="test_video_generation",
        business_id=uuid.uuid4(),
        idempotency_key="test-video-account-no-deduction",
        request_id=uuid.uuid4(),
    )
    consume_hold(
        hold_id=video_hold.pk,
        amount=10,
        idempotency_key="test-video-consume-no-deduction",
        request_id=uuid.uuid4(),
    )
    video_account.refresh_from_db()
    assert video_hold.is_test_account_bypass is True
    assert (video_account.available, video_account.frozen) == video_before
