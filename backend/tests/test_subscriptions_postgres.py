import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.utils import timezone
from django_redis import get_redis_connection

from apps.admin_rbac.permissions import resolve_admin_context
from apps.plans.application_services import create_application
from apps.plans.models import Plan, PlanApplication, Subscription, SubscriptionEvent
from apps.plans.services import (
    create_plan,
    create_plan_version,
    publish_plan_version,
    set_plan_offline,
    update_plan_version,
)
from apps.plans.subscription_services import activate_application, grant_trial
from apps.users.models import Notification, User

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
        return [future.result(timeout=20) for future in [pool.submit(run, op) for op in operations]]


def admin(phone="13900139000"):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password="Test-2026!")


def customer(phone="13800138000"):
    return User.objects.create_user(
        phone=phone,
        nickname="订阅用户",
        password="Test-2026!",
        approval_status=User.ApprovalStatus.APPROVED,
    )


def published(actor, code, trial=False):
    plan = create_plan(
        plan_id=uuid.uuid4(),
        actor=actor,
        data={
            "code": code,
            "name": code,
            "description": "说明",
            "price_display_mode": "fixed",
            "display_price": "0.00" if trial else "99.00",
            "is_trial": trial,
            "sort_order": 1,
        },
    )
    version = create_plan_version(plan_id=plan.pk, actor=actor, expected_plan_version=plan.version)
    version = publish_plan_version(
        version_id=version.pk,
        actor=actor,
        expected_version=version.version,
        confirm_informal_composite=True,
    )
    plan.refresh_from_db()
    return plan, version


def make_application(user, plan, version):
    return create_application(
        applicant=user,
        plan_id=plan.pk,
        plan_version_id=version.pk,
        user_note="",
        idempotency_key=str(uuid.uuid4()),
        request_id=uuid.uuid4(),
    ).application


def activate(actor, application):
    actor = User.objects.get(pk=actor.pk)
    application = PlanApplication.objects.get(pk=application.pk)
    return activate_application(
        requester=actor,
        admin_context=resolve_admin_context(actor),
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


def test_postgresql_concurrent_formal_activation_creates_one_subscription():
    actor, user = admin(), customer()
    plan, version = published(actor, "concurrent-formal")
    application = make_application(user, plan, version)
    results = parallel(lambda: activate(actor, application), lambda: activate(actor, application))
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert Subscription.objects.filter(source_application=application).count() == 1


def test_postgresql_concurrent_trial_grant_is_single():
    actor, user = admin(), customer()
    plan, _ = published(actor, "concurrent-trial", True)

    def operation():
        current_actor, current_user = User.objects.get(pk=actor.pk), User.objects.get(pk=user.pk)
        return grant_trial(
            requester=current_actor,
            admin_context=resolve_admin_context(current_actor),
            user_id=current_user.pk,
            expected_status_version=current_user.status_version,
            plan_id=plan.pk,
            opening_note="",
            request_id=uuid.uuid4(),
        )

    results = parallel(operation, operation)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert Subscription.objects.filter(user=user, is_trial=True).count() == 1


def test_postgresql_raw_sql_guards_subscription_and_event():
    actor, user = admin(), customer()
    plan, _ = published(actor, "guard-trial", True)
    subscription = grant_trial(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=plan.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    event = SubscriptionEvent.objects.get(subscription=subscription)
    for sql, params in (
        ("DELETE FROM subscriptions WHERE id = %s", [subscription.pk]),
        (
            "UPDATE subscriptions SET plan_version_no = plan_version_no + 1 WHERE id = %s",
            [subscription.pk],
        ),
        ("DELETE FROM subscription_events WHERE id = %s", [event.pk]),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)


def test_postgresql_raw_sql_cannot_restore_terminal_records():
    actor, user = admin(), customer()
    trial, _ = published(actor, "terminal-trial", True)
    subscription = grant_trial(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=trial.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    Subscription.objects.filter(pk=subscription.pk).update(
        status="terminated",
        terminated_at=timezone.now(),
        terminated_by=actor,
        termination_reason="终止",
        version=2,
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subscriptions SET status='active', terminated_at=NULL, "
                "terminated_by_id=NULL, termination_reason='', version=version+1 WHERE id=%s",
                [subscription.pk],
            )
    other = customer("13700137000")
    formal, version = published(actor, "terminal-app")
    application = make_application(other, formal, version)
    activate(actor, application)
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE plan_applications SET status='pending', activated_at=NULL, "
                "activated_by_id=NULL WHERE id=%s",
                [application.pk],
            )


def test_postgresql_expired_rollover_is_atomic():
    actor, user = admin(), customer()
    trial, _ = published(actor, "rollover-trial", True)
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
    formal, version = published(actor, "rollover-formal")
    new, _, _ = activate(actor, make_application(user, formal, version))
    old.refresh_from_db()
    assert old.status == "expired" and old.version == 2 and new.status == "active"


def test_postgresql_failure_injection_rolls_back_activation():
    actor, user = admin(), customer()
    plan, version = published(actor, "rollback-formal")
    application = make_application(user, plan, version)
    original = Notification.objects.create

    def fail(*args, **kwargs):
        if kwargs.get("notification_type") == "plan_application_activated":
            raise RuntimeError("injected")
        return original(*args, **kwargs)

    with (
        patch.object(Notification.objects, "create", side_effect=fail),
        pytest.raises(RuntimeError),
    ):
        activate(actor, application)
    application.refresh_from_db()
    assert application.status == "pending"
    assert not Subscription.objects.filter(source_application=application).exists()


def test_postgresql_plan_then_version_lock_order_has_no_deadlock():
    actor = admin()
    plan, _ = published(actor, "lock-order")
    draft = create_plan_version(plan_id=plan.pk, actor=actor, expected_plan_version=plan.version)

    def update():
        version = type(draft).objects.get(pk=draft.pk)
        return update_plan_version(
            version_id=version.pk,
            actor=User.objects.get(pk=actor.pk),
            expected_version=version.version,
            valid_days=version.valid_days,
            queue_priority=version.queue_priority,
            limits=[],
            model_permissions=[],
        )

    def offline():
        current = Plan.objects.get(pk=plan.pk)
        return set_plan_offline(
            plan_id=current.pk,
            actor=User.objects.get(pk=actor.pk),
            expected_version=current.version,
        )

    results = parallel(update, offline)
    assert not any("deadlock" in str(result).lower() for result in results)
