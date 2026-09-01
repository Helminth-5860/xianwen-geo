import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import models
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admin_rbac.sensitive_audit_models import SensitiveAuditLog
from apps.admin_rbac.sensitive_audit_services import purge_expired_sensitive_audit_logs
from apps.quotas.models import QuotaAccount
from tests.admin_session_helpers import authenticate_admin_client
from tests.test_quotas import provision


@pytest.fixture(autouse=True)
def seed_catalogs(db):
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)


@pytest.mark.django_db
def test_quota_grant_creates_sensitive_audit_evidence():
    requester, user, subscription = provision()
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="detection_points")
    before = account.available
    response = authenticate_admin_client(APIClient(), requester).post(
        f"/api/v1/admin/quota-accounts/{account.pk}/adjust/grant",
        {
            "expected_version": account.version,
            "amount": 1,
            "reason": "专项审计验收",
            "confirmed": True,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="audit-success-key-0001",
    )

    assert response.status_code == 200
    log = SensitiveAuditLog.objects.get(action_key="quota.grant", outcome="success")
    assert log.actor_user_id_snapshot == requester.pk
    assert log.target_user_id_snapshot == user.pk
    assert log.quota_before == before
    assert log.quota_requested_delta == 1
    assert log.quota_delta == 1
    assert log.quota_after == before + 1
    assert str(log.ledger_entry_id) == response.json()["ledger_entry_id"]
    assert log.safe_reason == "专项审计验收"
    assert str(log.operation_ip) == "127.0.0.1"
    assert str(log.login_ip_snapshot) == "127.0.0.1"


@pytest.mark.django_db
def test_failed_manual_deduct_is_audited_without_ledger_entry():
    requester, user, subscription = provision(phone="13800138001")
    account = QuotaAccount.objects.get(subscription=subscription, quota_type="detection_points")
    before = account.available
    amount = before + 1
    response = authenticate_admin_client(APIClient(), requester).post(
        f"/api/v1/admin/quota-accounts/{account.pk}/adjust/manual-deduct",
        {
            "expected_version": account.version,
            "amount": amount,
            "reason": "失败审计验收",
            "confirmed": True,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="audit-failure-key-0001",
    )

    assert response.status_code == 409
    log = SensitiveAuditLog.objects.get(action_key="quota.manual_deduct", outcome="failure")
    assert log.actor_user_id_snapshot == requester.pk
    assert log.target_user_id_snapshot == user.pk
    assert log.quota_before == before
    assert log.quota_requested_delta == -amount
    assert log.quota_delta is None
    assert log.quota_after == before
    assert log.ledger_entry_id is None
    assert log.failure_reason == "QUOTA_INSUFFICIENT"


@pytest.mark.django_db
def test_sensitive_audit_log_is_append_only_but_retention_can_purge_expired_rows():
    log = SensitiveAuditLog.objects.create(
        action_key="user.freeze",
        outcome=SensitiveAuditLog.Outcome.SUCCESS,
        request_id=uuid.uuid4(),
    )

    with pytest.raises(TypeError):
        log.delete()
    with pytest.raises(TypeError):
        SensitiveAuditLog.objects.filter(pk=log.pk).update(safe_reason="tamper")
    with pytest.raises(TypeError):
        SensitiveAuditLog.objects.filter(pk=log.pk).delete()

    models.QuerySet.update(
        SensitiveAuditLog.objects.filter(pk=log.pk),
        created_at=timezone.now() - timedelta(days=366),
    )
    assert purge_expired_sensitive_audit_logs(batch_size=10, max_batches=1) == 1
    assert not SensitiveAuditLog.objects.filter(pk=log.pk).exists()
