import uuid
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.urls import Resolver404, resolve
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admin_rbac.models import ApprovalRequest
from apps.admin_rbac.permissions import resolve_admin_context
from apps.plans.lifecycle import (
    RENEWAL_BLOCKED_BY_HOLD,
    execute_due_renewal,
    expire_subscription,
)
from apps.plans.models import Subscription, SubscriptionChange, SubscriptionEvent
from apps.quotas.idempotency import derive_idempotency_digests
from apps.quotas.lifecycle import next_cycle_boundary
from apps.quotas.models import QuotaAccount, QuotaLedgerEntry
from apps.quotas.services import adjust_quota_account, freeze_quota
from tests.admin_session_helpers import authenticate_admin_client
from tests.test_plan_changes import activate_formal, admin, customer
from tests.test_subscriptions import PASSWORD


@pytest.fixture(autouse=True)
def seed_catalogs(db):
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def approved_renewal(*, valid_days=30):
    requester = admin()
    approver = admin("13700137021")
    user = customer()
    source, _plan, version = activate_formal(
        requester,
        user,
        code=f"renewal-lifecycle-{valid_days}",
        valid_days=valid_days,
    )
    client = authenticate_admin_client(APIClient(), requester)
    submitted = client.post(
        f"/api/v1/admin/subscriptions/{source.pk}/change",
        {
            "expected_version": source.version,
            "target_plan_version_id": str(version.pk),
            "change_type": "renewal",
            "quota_policy": "retain",
            "reason": "scheduled renewal lifecycle test",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="test-test-test-test-0115",
    )
    assert submitted.status_code == 202
    approval = ApprovalRequest.objects.get(pk=submitted.json()["data"]["approval_id"])
    approved = authenticate_admin_client(APIClient(), approver, "198.51.100.115").post(
        f"/api/v1/admin/approvals/{approval.pk}/approve",
        {"current_password": PASSWORD},
        format="json",
        REMOTE_ADDR="198.51.100.115",
    )
    assert approved.status_code == 200
    approval.refresh_from_db()
    change = SubscriptionChange.objects.get(source_approval=approval)
    return source, change


@pytest.mark.django_db
def test_month_end_anchor_clamps_without_drifting():
    shanghai = ZoneInfo("Asia/Shanghai")
    subscription = SimpleNamespace(
        cycle_anchor_day=31,
        cycle_anchor_time=time(9, 30),
        ends_at=datetime(2026, 5, 1, tzinfo=shanghai),
    )
    february = next_cycle_boundary(subscription, datetime(2026, 1, 31, 9, 30, tzinfo=shanghai))
    march = next_cycle_boundary(subscription, february)
    assert february == datetime(2026, 2, 28, 9, 30, tzinfo=shanghai)
    assert march == datetime(2026, 3, 31, 9, 30, tzinfo=shanghai)


@pytest.mark.django_db
def test_expiry_is_idempotent_and_writes_one_event():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="expiry-idempotent")
    moment = source.ends_at + timedelta(seconds=1)
    expire_subscription(subscription_id=source.pk, request_id=uuid.uuid4(), now=moment)
    expire_subscription(subscription_id=source.pk, request_id=uuid.uuid4(), now=moment)
    source.refresh_from_db()
    assert source.status == Subscription.Status.EXPIRED
    assert SubscriptionEvent.objects.filter(subscription=source, event_type="expired").count() == 1


@pytest.mark.django_db
def test_blocked_renewal_still_expires_source_and_persists_retry():
    source, change = approved_renewal()
    account = QuotaAccount.objects.get(subscription=source, quota_type="detection_points")
    digests = derive_idempotency_digests(
        "renewal-hold-fund-key-0001",
        operation="grant",
        user_id=source.user_id,
        account_id=account.pk,
        business_type="quota_adjustment",
        business_id=account.pk,
        request_payload={"amount": 1, "reason": "renewal hold funding"},
    )
    adjust_quota_account(
        requester=source.opened_by,
        admin_context=resolve_admin_context(source.opened_by),
        account_id=account.pk,
        expected_version=account.version,
        action="grant",
        amount=1,
        reason="renewal hold funding",
        digests=digests,
        request_id=uuid.uuid4(),
    )
    freeze_quota(
        account_id=account.pk,
        amount=1,
        business_type="renewal_test",
        business_id=uuid.uuid4(),
        idempotency_key="renewal-hold-idempotency-key-0001",
        request_id=uuid.uuid4(),
    )
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=source.ends_at + timedelta(seconds=1),
    )
    source.refresh_from_db()
    change.refresh_from_db()
    assert source.status == Subscription.Status.EXPIRED
    assert change.status == SubscriptionChange.Status.SCHEDULED
    assert change.stable_error_code == RENEWAL_BLOCKED_BY_HOLD
    assert change.retry_count == 1
    assert change.next_attempt_at is not None


@pytest.mark.django_db
def test_current_subscription_get_remains_read_only_after_time_expiry():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="readonly-current")
    moment = timezone.now()
    Subscription.objects.filter(pk=source.pk).update(
        starts_at=moment - timedelta(days=2), ends_at=moment - timedelta(days=1)
    )
    before_events = SubscriptionEvent.objects.count()
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/v1/subscription")
    assert response.status_code == 200
    assert response.json()["data"]["current"] is None
    source.refresh_from_db()
    assert source.status == Subscription.Status.ACTIVE
    assert SubscriptionEvent.objects.count() == before_events


@pytest.mark.django_db
def test_cycle_anchor_time_is_stored_from_shanghai_activation_time():
    actor, user = admin(), customer()
    source, _, _ = activate_formal(actor, user, code="anchor-time")
    local = timezone.localtime(source.starts_at, ZoneInfo("Asia/Shanghai"))
    assert source.cycle_anchor_time == local.timetz().replace(tzinfo=None)


@pytest.mark.django_db
def test_no_public_execute_or_reset_routes():
    for path in (
        "/api/v1/admin/subscription-changes/00000000-0000-0000-0000-000000000001/execute",
        "/api/v1/admin/quotas/reset",
        "/api/v1/admin/subscriptions/00000000-0000-0000-0000-000000000001/reset",
    ):
        with pytest.raises(Resolver404):
            resolve(path)


def test_celery_lifecycle_safety_configuration(settings):
    assert settings.CELERY_TASK_ACKS_LATE is True
    assert settings.CELERY_TASK_REJECT_ON_WORKER_LOST is True
    assert settings.CELERY_WORKER_PREFETCH_MULTIPLIER == 1
    assert set(settings.CELERY_BEAT_SCHEDULE) == {
        "scan-due-renewals",
        "scan-due-expiries",
        "scan-due-quota-cycles",
        "scan-expired-file-upload-intents",
        "scan-file-verification-retries",
        "scan-document-parse-retries",
        "dispatch-subject-enrichment-jobs",
        "dispatch-queued-web-imports",
        "scan-web-import-retries",
    }
    assert QuotaLedgerEntry.Action.CYCLE_FORFEIT == "cycle_forfeit"
