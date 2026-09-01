import uuid
from datetime import time, timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.plans.models import Plan, PlanVersion, Subscription
from apps.quotas.catalog import QUOTA_BY_KEY
from apps.quotas.models import QuotaAccount, QuotaHold, QuotaHoldGroup, QuotaLedgerEntry
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"
ROOT_URLCONF = "tests.control_center_api_urls"


def create_superuser(phone="13900139000"):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def create_customer(phone="13800138000", nickname="客户"):
    return User.objects.create_user(phone=phone, nickname=nickname, password=PASSWORD)


def create_plan(*, code="trial", name="免费体验", is_trial=True):
    plan = Plan.objects.create(code=code, name=name, is_trial=is_trial)
    version = PlanVersion.objects.create(
        plan=plan,
        version_no=1,
        valid_days=30,
        queue_priority=100,
    )
    return plan, version


def create_subscription(user, plan, version, *, source_type=Subscription.SourceType.TRIAL_GRANT):
    now = timezone.now()
    is_trial = source_type == Subscription.SourceType.TRIAL_GRANT
    return Subscription.objects.create(
        user=user,
        source_type=source_type,
        plan=plan,
        plan_version=version,
        plan_version_no=version.version_no,
        entitlement_snapshot={"limits": {}, "model_permissions": []},
        entitlement_digest="test-entitlement-digest",
        status=Subscription.Status.ACTIVE,
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=29),
        cycle_anchor_day=1,
        cycle_anchor_time=time(0, 0),
        is_trial=is_trial,
        activated_at=now - timedelta(days=1),
        request_id=uuid.uuid4(),
    )


def create_quota_facts(user, subscription):
    quota_type = "geo_detection_runs"
    definition = QUOTA_BY_KEY[quota_type]
    account = QuotaAccount.objects.create(
        user=user,
        subscription=subscription,
        quota_type=quota_type,
        scope=QuotaAccount.Scope.SUBSCRIPTION,
        unit=definition.unit,
        entitlement_amount=60,
        available=47,
        frozen=3,
        ledger_sequence=2,
        version=3,
    )

    business_id = uuid.uuid4()
    group = QuotaHoldGroup.objects.create(
        user=user,
        quota_type=quota_type,
        business_type="control_center_test",
        business_id=business_id,
        requested_amount=15,
        consumed_amount=15,
        status=QuotaHoldGroup.Status.SETTLED,
        freeze_idempotency_key_digest=uuid.uuid4().hex,
        freeze_idempotency_scope_digest=uuid.uuid4().hex,
        freeze_request_digest=uuid.uuid4().hex,
        settled_at=timezone.now(),
    )
    hold = QuotaHold.objects.create(
        group=group,
        account=account,
        user=user,
        subscription=subscription,
        quota_type=quota_type,
        business_type="control_center_test",
        business_id=business_id,
        requested_amount=15,
        consumed_amount=15,
        status=QuotaHold.Status.SETTLED,
        freeze_idempotency_key_digest=uuid.uuid4().hex,
        freeze_idempotency_scope_digest=uuid.uuid4().hex,
        freeze_request_digest=uuid.uuid4().hex,
        settled_at=timezone.now(),
    )
    consume = QuotaLedgerEntry.objects.create(
        account=account,
        hold=hold,
        user=user,
        subscription=subscription,
        quota_type=quota_type,
        sequence=1,
        action=QuotaLedgerEntry.Action.CONSUME,
        available_before=42,
        available_delta=0,
        available_after=42,
        frozen_before=18,
        frozen_delta=-15,
        frozen_after=3,
        account_version_before=1,
        account_version_after=2,
        business_type="control_center_test",
        business_id=business_id,
        safe_reason="真实业务消费",
        request_id=uuid.uuid4(),
        idempotency_key_digest=uuid.uuid4().hex,
        idempotency_scope_digest=uuid.uuid4().hex,
        request_digest=uuid.uuid4().hex,
    )
    actor = create_superuser("13700137000")
    grant = QuotaLedgerEntry.objects.create(
        account=account,
        user=user,
        subscription=subscription,
        quota_type=quota_type,
        sequence=2,
        action=QuotaLedgerEntry.Action.GRANT,
        available_before=42,
        available_delta=5,
        available_after=47,
        frozen_before=3,
        frozen_delta=0,
        frozen_after=3,
        account_version_before=2,
        account_version_after=3,
        business_type="admin_adjustment",
        safe_reason="客户增购额度",
        actor=actor,
        request_id=uuid.uuid4(),
        idempotency_key_digest=uuid.uuid4().hex,
        idempotency_scope_digest=uuid.uuid4().hex,
        request_digest=uuid.uuid4().hex,
    )
    account.last_ledger_entry = grant
    account.save(update_fields=["last_ledger_entry", "updated_at"])
    return account, consume, grant


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=ROOT_URLCONF)
def test_control_center_requires_superuser_admin_session():
    user = create_customer()
    ordinary = APIClient()
    ordinary.force_authenticate(user)

    response = ordinary.get(f"/api/v1/admin/users/{user.id}/control-center")

    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=ROOT_URLCONF)
def test_control_center_reports_real_subscription_quota_and_ledger_usage():
    superuser = create_superuser()
    user = create_customer()
    plan, version = create_plan()
    subscription = create_subscription(user, plan, version)
    create_quota_facts(user, subscription)

    client = APIClient()
    authenticate_admin_client(client, superuser)
    response = client.get(f"/api/v1/admin/users/{user.id}/control-center")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["user"]["id"] == str(user.id)
    assert payload["subscription"]["plan_name"] == "免费体验"
    assert payload["subscription"]["is_trial"] is True

    quota = next(item for item in payload["quotas"] if item["quota_type"] == "geo_detection_runs")
    assert quota["entitlement_amount"] == "60"
    assert quota["manual_adjustment_amount"] == "5"
    assert quota["used_amount"] == "15"
    assert quota["frozen"] == "3"
    assert quota["available"] == "47"
    assert quota["total_amount"] == "65"
    assert len(quota["accounts"]) == 1
    assert quota["accounts"][0]["used_amount"] == "15"

    assert payload["recent_ledger"][0]["action"] == QuotaLedgerEntry.Action.GRANT
    assert payload["recent_ledger"][0]["available_delta"] == "5"
    assert payload["usage"]["items"][0]["amount"] == "15"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=ROOT_URLCONF)
def test_control_center_does_not_surface_legacy_internal_test_subscription():
    superuser = create_superuser()
    user = create_customer()
    plan, version = create_plan(code="legacy-internal", name="历史内部授权", is_trial=False)
    create_subscription(user, plan, version, source_type=Subscription.SourceType.INTERNAL_TEST)

    client = APIClient()
    authenticate_admin_client(client, superuser)
    response = client.get(f"/api/v1/admin/users/{user.id}/control-center")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["subscription"] is None
    assert payload["subscription_history"] == []
    assert payload["quotas"] == []
