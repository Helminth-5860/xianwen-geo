import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.models import ApprovalRequest, AuditEvent
from apps.admin_rbac.permissions import resolve_admin_context
from apps.plans.application_services import admin_change_application, cancel_application
from apps.plans.models import PlanApplication, Subscription, SubscriptionEvent
from apps.plans.subscription_services import grant_trial, terminate_subscription
from apps.users.models import Notification, User
from tests.admin_session_helpers import authenticate_admin_client
from tests.test_subscriptions_postgres import (
    activate,
    admin,
    customer,
    make_application,
    parallel,
    published,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_services():
    if connection.vendor != "postgresql":
        pytest.skip("仅通过 scripts/test-subscriptions.* 在真实 PostgreSQL/Redis 执行。")
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


INSERT_COLUMNS = (
    "id,user_id,source_application_id,plan_id,plan_version_id,plan_version_no,"
    "entitlement_snapshot,entitlement_digest,status,starts_at,ends_at,cycle_anchor_day,"
    "is_trial,opened_by_id,opening_note,activated_at,expired_at,terminated_at,"
    "terminated_by_id,termination_reason,version,request_id,created_at,updated_at"
)


def raw_clone(subscription_id, *, user_id, source_application_id):
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO subscriptions ({INSERT_COLUMNS}) "
            "SELECT %s,%s,%s,plan_id,plan_version_id,plan_version_no,"
            "entitlement_snapshot,entitlement_digest,status,starts_at,ends_at,"
            "cycle_anchor_day,is_trial,opened_by_id,opening_note,activated_at,expired_at,"
            "terminated_at,terminated_by_id,termination_reason,version,%s,created_at,updated_at "
            "FROM subscriptions WHERE id=%s",
            [
                uuid.uuid4(),
                user_id,
                source_application_id,
                uuid.uuid4(),
                subscription_id,
            ],
        )


def test_postgresql_same_user_different_applications_create_one_active_subscription():
    actor, user = admin(), customer()
    first_plan, first_version = published(actor, "different-application-first")
    second_plan, second_version = published(actor, "different-application-second")
    first = make_application(user, first_plan, first_version)
    second = make_application(user, second_plan, second_version)

    results = parallel(lambda: activate(actor, first), lambda: activate(actor, second))

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert Subscription.objects.filter(user=user, status="active").count() == 1
    assert PlanApplication.objects.filter(applicant=user, status="activated").count() == 1
    assert PlanApplication.objects.filter(applicant=user, status="pending").count() == 1


@pytest.mark.parametrize("competing_action", ["cancel", "contact", "close"])
def test_postgresql_activation_application_transition_race_is_consistent(competing_action):
    actor, user = admin(), customer()
    plan, version = published(actor, f"activation-{competing_action}")
    application = make_application(user, plan, version)

    def transition():
        if competing_action == "cancel":
            return cancel_application(
                user=User.objects.get(pk=user.pk),
                application_id=application.pk,
                expected_version=1,
                request_id=uuid.uuid4(),
            )
        current_actor = User.objects.get(pk=actor.pk)
        return admin_change_application(
            requester=current_actor,
            admin_context=resolve_admin_context(current_actor),
            application_id=application.pk,
            expected_version=1,
            action=competing_action,
            request_id=uuid.uuid4(),
        )

    results = parallel(lambda: activate(actor, application), transition)
    application.refresh_from_db()
    subscriptions = Subscription.objects.filter(source_application=application)
    if competing_action == "contact":
        assert application.status in {"contacted", "activated"}
        assert subscriptions.count() == (1 if application.status == "activated" else 0)
        successful = sum(not isinstance(result, Exception) for result in results)
        assert successful == 1
    else:
        terminal = {"cancel": "cancelled", "close": "closed"}[competing_action]
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert application.status in {"activated", terminal}
        assert subscriptions.count() == (1 if application.status == "activated" else 0)


def test_postgresql_subscription_two_person_concurrent_approval_executes_exactly_once():
    requester = admin("13900139000")
    approver = admin("13700137000")
    user = customer()
    plan, version = published(requester, "approval-exactly-once")
    application = make_application(user, plan, version)
    response = authenticate_admin_client(APIClient(), requester).post(
        f"/api/v1/admin/plan-applications/{application.pk}/activate",
        {"expected_version": application.version},
        format="json",
    )
    assert response.status_code == 202
    approval = ApprovalRequest.objects.get(pk=response.json()["data"]["approval_id"])
    first = authenticate_admin_client(APIClient(), approver)
    second = authenticate_admin_client(APIClient(), approver)

    responses = parallel(
        lambda: first.post(
            f"/api/v1/admin/approvals/{approval.pk}/approve",
            {"current_password": "Test-2026!"},
            format="json",
        ),
        lambda: second.post(
            f"/api/v1/admin/approvals/{approval.pk}/approve",
            {"current_password": "Test-2026!"},
            format="json",
        ),
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.EXECUTED
    assert Subscription.objects.filter(source_application=application).count() == 1
    assert AuditEvent.objects.filter(approval_request=approval, outcome="executed").count() == 1


def test_postgresql_raw_sql_enforces_single_active_and_single_trial_history():
    actor, user = admin(), customer()
    plan, version = published(actor, "raw-unique-formal")
    first_application = make_application(user, plan, version)
    subscription, _, _ = activate(actor, first_application)
    second_application = make_application(user, plan, version)
    with pytest.raises(DatabaseError), transaction.atomic():
        raw_clone(
            subscription.pk,
            user_id=user.pk,
            source_application_id=second_application.pk,
        )

    trial_user = customer("13700137000")
    trial_plan, _ = published(actor, "raw-unique-trial", True)
    trial = grant_trial(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        user_id=trial_user.pk,
        expected_status_version=trial_user.status_version,
        plan_id=trial_plan.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    terminate_subscription(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        subscription_id=trial.pk,
        expected_version=trial.version,
        reason="结束试用",
        request_id=uuid.uuid4(),
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        raw_clone(trial.pk, user_id=trial_user.pk, source_application_id=None)


def test_postgresql_raw_sql_guards_delete_snapshot_source_and_event_mutation():
    actor, user = admin(), customer()
    plan, version = published(actor, "raw-guard-formal")
    application = make_application(user, plan, version)
    subscription, _, _ = activate(actor, application)
    event = SubscriptionEvent.objects.get(subscription=subscription, event_type="activated")
    for sql, params in (
        ("DELETE FROM subscriptions WHERE id=%s", [subscription.pk]),
        (
            "UPDATE subscriptions SET entitlement_snapshot='{}'::jsonb WHERE id=%s",
            [subscription.pk],
        ),
        ("UPDATE subscriptions SET source_application_id=NULL WHERE id=%s", [subscription.pk]),
        ("UPDATE subscription_events SET safe_summary='tampered' WHERE id=%s", [event.pk]),
        ("DELETE FROM subscription_events WHERE id=%s", [event.pk]),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)

    unrelated = customer("13700137000")
    with pytest.raises(DatabaseError), transaction.atomic():
        raw_clone(subscription.pk, user_id=unrelated.pk, source_application_id=None)


def test_postgresql_raw_sql_blocks_terminal_restore_and_activated_application_changes():
    actor = admin()
    trial, _ = published(actor, "terminal-matrix-trial", True)
    terminated_user = customer()
    terminated = grant_trial(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        user_id=terminated_user.pk,
        expected_status_version=terminated_user.status_version,
        plan_id=trial.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    terminate_subscription(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        subscription_id=terminated.pk,
        expected_version=terminated.version,
        reason="终止",
        request_id=uuid.uuid4(),
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subscriptions SET status='active', terminated_at=NULL, "
                "terminated_by_id=NULL, termination_reason='', version=version+1 WHERE id=%s",
                [terminated.pk],
            )

    expired_user = customer("13700137000")
    expired = grant_trial(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        user_id=expired_user.pk,
        expected_status_version=expired_user.status_version,
        plan_id=trial.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    Subscription.objects.filter(pk=expired.pk).update(
        status="expired",
        expired_at=timezone.now(),
        version=2,
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subscriptions SET status='active', expired_at=NULL, "
                "version=version+1 WHERE id=%s",
                [expired.pk],
            )

    formal_user = customer("13600136000")
    formal, version = published(actor, "terminal-matrix-formal")
    application = make_application(formal_user, formal, version)
    activate(actor, application)
    for status_sql in (
        "status='pending', activated_at=NULL, activated_by_id=NULL",
        "status='cancelled', cancelled_at=NOW(), activated_at=NULL, activated_by_id=NULL",
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE plan_applications SET {status_sql} WHERE id=%s",
                    [application.pk],
                )


def test_postgresql_subscription_event_failure_rolls_back_everything():
    actor, user = admin(), customer()
    plan, version = published(actor, "rollback-event")
    application = make_application(user, plan, version)
    with (
        patch.object(SubscriptionEvent.objects, "create", side_effect=RuntimeError("event failed")),
        pytest.raises(RuntimeError),
    ):
        activate(actor, application)
    application.refresh_from_db()
    assert application.status == "pending" and application.version == 1
    assert not Subscription.objects.filter(source_application=application).exists()


def test_postgresql_audit_failure_rolls_back_approved_subscription_execution():
    requester = admin("13900139000")
    approver = admin("13700137000")
    user = customer()
    plan, version = published(requester, "rollback-audit")
    application = make_application(user, plan, version)
    requested = authenticate_admin_client(APIClient(), requester).post(
        f"/api/v1/admin/plan-applications/{application.pk}/activate",
        {"expected_version": application.version},
        format="json",
    )
    approval = ApprovalRequest.objects.get(pk=requested.json()["data"]["approval_id"])
    with patch(
        "apps.admin_rbac.risk_services.record_audit_event",
        side_effect=RuntimeError("audit failed"),
    ):
        response = authenticate_admin_client(APIClient(), approver).post(
            f"/api/v1/admin/approvals/{approval.pk}/approve",
            {"current_password": "Test-2026!"},
            format="json",
        )
    assert response.status_code == 500
    approval.refresh_from_db()
    application.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING
    assert application.status == "pending"
    assert not Subscription.objects.filter(source_application=application).exists()
    assert not AuditEvent.objects.filter(approval_request=approval, outcome="executed").exists()


def test_postgresql_expiry_rollover_failure_restores_old_active_and_events():
    actor, user = admin(), customer()
    trial, _ = published(actor, "rollback-expiry-trial", True)
    historical_now = timezone.now() - timedelta(days=40)
    with patch("apps.plans.subscription_services.timezone.now", return_value=historical_now):
        old = grant_trial(
            requester=actor,
            admin_context=resolve_admin_context(actor),
            user_id=user.pk,
            expected_status_version=user.status_version,
            plan_id=trial.pk,
            opening_note="",
            request_id=uuid.uuid4(),
        )
    formal, version = published(actor, "rollback-expiry-formal")
    application = make_application(user, formal, version)
    original = Notification.objects.create

    def fail_after_expiry(*args, **kwargs):
        if kwargs.get("notification_type") == "plan_application_activated":
            raise RuntimeError("activation notification failed")
        return original(*args, **kwargs)

    with (
        patch.object(Notification.objects, "create", side_effect=fail_after_expiry),
        pytest.raises(RuntimeError),
    ):
        activate(actor, application)
    old.refresh_from_db()
    application.refresh_from_db()
    assert old.status == "active" and old.expired_at is None and old.version == 1
    assert not SubscriptionEvent.objects.filter(subscription=old, event_type="expired").exists()
    assert application.status == "pending"
    assert not Subscription.objects.filter(source_application=application).exists()


def test_postgresql_terminate_and_reopen_race_preserves_single_active():
    actor, user = admin(), customer()
    plan, version = published(actor, "terminate-reopen")
    first_application = make_application(user, plan, version)
    current, _, _ = activate(actor, first_application)
    second_application = make_application(user, plan, version)

    def terminate():
        current_actor = User.objects.get(pk=actor.pk)
        return terminate_subscription(
            requester=current_actor,
            admin_context=resolve_admin_context(current_actor),
            subscription_id=current.pk,
            expected_version=current.version,
            reason="竞态终止",
            request_id=uuid.uuid4(),
        )

    results = parallel(terminate, lambda: activate(actor, second_application))
    current.refresh_from_db()
    second_application.refresh_from_db()
    assert any(not isinstance(result, Exception) for result in results)
    assert current.status == "terminated"
    assert Subscription.objects.filter(user=user, status="active").count() <= 1
    if second_application.status == "activated":
        assert Subscription.objects.filter(source_application=second_application).count() == 1
    else:
        assert second_application.status == "pending"
