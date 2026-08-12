from __future__ import annotations

import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import connection
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.permissions import resolve_admin_context
from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.models import FileStorageAllocation
from apps.documents.services import create_upload_intent
from apps.documents.storage import S3CompatibleStorageProvider
from apps.plans.lifecycle import execute_due_renewal, expire_subscription
from apps.plans.models import Subscription
from apps.plans.services import (
    create_plan,
    create_plan_version,
    publish_plan_version,
    update_plan_version,
)
from apps.plans.subscription_services import activate_application, grant_trial
from apps.quotas.exceptions import QuotaInsufficient
from apps.quotas.models import (
    QuotaAccount,
    QuotaCycleReset,
    QuotaLedgerEntry,
    QuotaTransfer,
)
from tests.subject_risk_helpers import install_empty_published_risk_catalog
from tests.test_documents_saga_postgres import (
    _complete_and_verify,
    _new_intent,
    _provision,
)
from tests.test_plan_changes_postgres import change_operation
from tests.test_subscriptions import _plan_limit_value, application_for

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def real_lifecycle_dependencies():
    if connection.vendor != "postgresql":
        pytest.skip("run with scripts/test-files.* against PostgreSQL, Redis and MinIO")
    for command in ("sync_plan_catalog", "sync_subject_catalog", "sync_admin_rbac"):
        call_command(command, "--apply", verbosity=0)
    install_empty_published_risk_catalog()
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    provider = S3CompatibleStorageProvider()
    provider.client.head_bucket(Bucket=provider.bucket)
    yield
    redis.flushdb()


def _published_storage_plan(admin, storage_bytes, *, trial=False, plan=None):
    if plan is None:
        suffix = uuid.uuid4().hex[:8]
        plan = create_plan(
            plan_id=uuid.uuid4(),
            actor=admin,
            data={
                "code": f"storage-target-{suffix}",
                "name": "Storage target",
                "description": "Storage lifecycle evidence",
                "price_display_mode": "fixed",
                "display_price": "0.00" if trial else "99.00",
                "is_trial": trial,
                "sort_order": 1,
            },
        )
    else:
        plan.refresh_from_db()
    version = create_plan_version(
        plan_id=plan.pk,
        actor=admin,
        expected_plan_version=plan.version,
    )
    limits = [
        {
            "key": item.limit_key,
            "value": storage_bytes
            if item.limit_key == "storage_bytes"
            else _plan_limit_value(item),
        }
        for item in version.limits.all()
    ]
    version = update_plan_version(
        version_id=version.pk,
        actor=admin,
        expected_version=version.version,
        valid_days=version.valid_days,
        queue_priority=version.queue_priority,
        limits=limits,
        model_permissions=[
            {
                "model_key": item.model_key,
                "sort_order": item.sort_order,
                "selected_by_default": item.selected_by_default,
            }
            for item in version.model_permissions.all()
        ],
    )
    version = publish_plan_version(
        version_id=version.pk,
        actor=admin,
        expected_version=version.version,
        confirm_informal_composite=True,
    )
    plan.refresh_from_db()
    return plan, version


def _expire_source(source):
    expire_subscription(
        subscription_id=source.pk,
        request_id=uuid.uuid4(),
        now=source.ends_at + timedelta(seconds=1),
    )
    source.refresh_from_db()
    assert source.status == Subscription.Status.EXPIRED


def _new_subscription_through(path, *, target_storage, payload=b"immutable file usage"):
    initial_trial = path == "formal_application"
    admin, user, subject, source_account = _provision(
        storage_bytes=4096,
        trial=initial_trial,
    )
    intent, _ = _new_intent(user, subject, payload)
    _complete_and_verify(user, intent)
    usage = FileStorageAllocation.objects.filter(user=user).get().size_bytes
    source = source_account.subscription

    if path == "formal_application":
        _expire_source(source)
        plan, version = _published_storage_plan(admin, target_storage)
        application = application_for(user, plan, version)
        target, _, _ = activate_application(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            application_id=application.pk,
            expected_version=application.version,
            selected_plan_version_id=None,
            confirm_unavailable=False,
            unavailable_reason="",
            confirm_version_override=False,
            override_reason="",
            opening_note="",
            request_id=uuid.uuid4(),
        )
    elif path == "grant_trial":
        _expire_source(source)
        plan, _ = _published_storage_plan(admin, target_storage, trial=True)
        user.refresh_from_db()
        target = grant_trial(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            user_id=user.pk,
            expected_status_version=user.status_version,
            plan_id=plan.pk,
            opening_note="",
            request_id=uuid.uuid4(),
        )
    elif path == "immediate_plan_change":
        plan, version = _published_storage_plan(admin, target_storage)
        change = change_operation(
            admin.pk,
            source.pk,
            plan.pk,
            version.pk,
            f"storage-immediate-{uuid.uuid4()}",
            change_type="upgrade"
            if target_storage >= source_account.entitlement_amount
            else "downgrade",
        )
        target = Subscription.objects.get(source_change=change)
    elif path == "scheduled_renewal":
        plan, version = _published_storage_plan(
            admin,
            target_storage,
            plan=source.plan,
        )
        change = change_operation(
            admin.pk,
            source.pk,
            plan.pk,
            version.pk,
            f"storage-renewal-{uuid.uuid4()}",
            change_type="renewal",
        )
        execute_due_renewal(
            change_id=change.pk,
            request_id=uuid.uuid4(),
            now=source.ends_at + timedelta(seconds=1),
        )
        target = Subscription.objects.get(source_change=change)
    else:
        raise AssertionError(path)

    target_account = QuotaAccount.objects.get(
        subscription=target,
        quota_type="storage_bytes",
        batch_type=QuotaAccount.BatchType.PRIMARY,
    )
    return admin, user, subject, intent, target, target_account, source_account, usage


@pytest.mark.parametrize(
    "path",
    ("formal_application", "grant_trial", "immediate_plan_change", "scheduled_renewal"),
)
def test_storage_capacity_is_absolute_on_every_subscription_creation_path(path):
    (
        _admin,
        user,
        _subject,
        _intent,
        target,
        account,
        source_account,
        usage,
    ) = _new_subscription_through(path, target_storage=8192)
    assert account.entitlement_amount == 8192
    assert account.available == 8192 - usage
    assert account.frozen == 0
    assert not QuotaAccount.objects.filter(
        subscription=target,
        quota_type="storage_bytes",
        batch_type=QuotaAccount.BatchType.CARRYOVER,
    ).exists()
    assert not QuotaTransfer.objects.filter(source_account__quota_type="storage_bytes").exists()
    assert not QuotaTransfer.objects.filter(target_account__quota_type="storage_bytes").exists()
    assert not QuotaLedgerEntry.objects.filter(
        quota_type="storage_bytes",
        action__in=(
            QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_OUT,
            QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_IN,
        ),
    ).exists()
    assert not QuotaCycleReset.objects.filter(quota_type="storage_bytes").exists()
    assert QuotaAccount.objects.filter(pk=source_account.pk).exists()
    assert FileStorageAllocation.objects.filter(user=user).count() == 1


@pytest.mark.parametrize("path", ("immediate_plan_change", "scheduled_renewal"))
def test_over_capacity_plan_change_succeeds_but_blocks_new_upload_and_keeps_file(path):
    (
        _admin,
        user,
        subject,
        intent,
        target,
        account,
        _source_account,
        usage,
    ) = _new_subscription_through(path, target_storage=1, payload=b"existing usage")
    assert usage > account.entitlement_amount
    assert account.available == 0
    assert account.frozen == 0
    assert target.status == Subscription.Status.ACTIVE
    effective_now = target.starts_at + timedelta(seconds=1)
    with (
        patch("apps.documents.services.timezone.now", return_value=effective_now),
        pytest.raises(QuotaInsufficient),
    ):
        create_upload_intent(
            user_id=user.pk,
            subject_id=subject.pk,
            filename="blocked.txt",
            content_type="text/plain",
            declared_size=1,
            idempotency_key=f"over-capacity-{uuid.uuid4()}",
            request_id=uuid.uuid4(),
        )
    intent.refresh_from_db()
    assert FileStorageAllocation.objects.filter(document_version=intent.completed_version).exists()
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(
        f"/api/v1/documents/{intent.completed_version.document_id}/download-intents",
        {},
        format="json",
    )
    assert response.status_code == 200


def test_reconcile_storage_capacity_dry_run_apply_and_repeat_are_safe_and_idempotent():
    _, user, subject, account = _provision(storage_bytes=4096)
    intent, _ = _new_intent(user, subject, b"allocation usage")
    _complete_and_verify(user, intent)
    intent.refresh_from_db()
    account.refresh_from_db()
    entitlement = account.entitlement_amount
    usage = FileStorageAllocation.objects.get(user=user).size_bytes
    expected = entitlement - usage
    assert account.available == expected

    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE quota_accounts DISABLE TRIGGER quotas_account_guard")
        try:
            cursor.execute(
                "UPDATE quota_accounts SET available=entitlement_amount WHERE id=%s",
                [account.pk],
            )
        finally:
            cursor.execute("ALTER TABLE quota_accounts ENABLE TRIGGER quotas_account_guard")

    account.refresh_from_db()
    assert account.available == entitlement
    ledger_before = QuotaLedgerEntry.objects.filter(account=account).count()

    dry_output = StringIO()
    call_command("reconcile_storage_capacity", "--dry-run", stdout=dry_output)
    account.refresh_from_db()
    assert account.available == entitlement
    assert QuotaLedgerEntry.objects.filter(account=account).count() == ledger_before
    assert "changed=1" in dry_output.getvalue()

    apply_output = StringIO()
    call_command("reconcile_storage_capacity", "--apply", stdout=apply_output)
    account.refresh_from_db()
    assert account.available == expected
    assert account.entitlement_amount == entitlement
    entries = QuotaLedgerEntry.objects.filter(
        account=account,
        action=QuotaLedgerEntry.Action.STORAGE_CAPACITY_RECONCILE,
    )
    assert entries.count() == 1
    assert entries.get().available_delta == -usage

    second_output = StringIO()
    call_command("reconcile_storage_capacity", "--apply", stdout=second_output)
    account.refresh_from_db()
    assert account.available == expected
    assert entries.count() == 1
    assert "changed=0" in second_output.getvalue()
    combined_output = dry_output.getvalue() + apply_output.getvalue() + second_output.getvalue()
    for secret in (
        intent.declared_filename,
        intent.staging_key,
        intent.final_key,
        intent.completed_version.sha256,
    ):
        assert secret not in combined_output


def test_storage_capacity_service_rejects_when_no_effective_capacity_remains():
    _, user, subject, account = _provision(storage_bytes=1)
    assert account.available == 1
    with pytest.raises((QuotaInsufficient, FileStorageUnavailable)):
        create_upload_intent(
            user_id=user.pk,
            subject_id=subject.pk,
            filename="too-large.txt",
            content_type="text/plain",
            declared_size=2,
            idempotency_key=f"capacity-reject-{uuid.uuid4()}",
            request_id=uuid.uuid4(),
        )
