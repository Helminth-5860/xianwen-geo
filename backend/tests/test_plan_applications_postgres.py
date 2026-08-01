import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminProfile, AdminRole, AuditEvent, CustomerAssignment
from apps.plans.application_services import (
    PlanApplicationAlreadyOpen,
    admin_change_application,
    cancel_application,
    create_application,
    scoped_plan_applications,
)
from apps.plans.models import PlanApplication, PlanApplicationEvent
from apps.plans.services import (
    create_plan,
    create_plan_version,
    publish_plan_version,
    set_plan_offline,
)
from apps.users.models import Notification, User
from tests.admin_session_helpers import authenticate_admin_client

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def seed_catalogs():
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def require_postgresql():
    if connection.vendor != "postgresql":
        pytest.skip("仅通过 scripts/test-plan-applications.* 在真实 PostgreSQL 执行。")


def user(phone, *, admin=False, superuser=None):
    value = User(
        phone=phone,
        nickname="申请并发测试",
        approval_status="approved",
        account_status="active",
        is_staff=admin,
        is_superuser=admin if superuser is None else superuser,
    )
    value.set_unusable_password()
    value.synchronize_active_state()
    value.save()
    return value


def published_plan(admin):
    plan = create_plan(
        plan_id=uuid.uuid4(),
        actor=admin,
        data={
            "code": "application-pg",
            "name": "并发套餐",
            "description": "",
            "price_display_mode": "fixed",
            "display_price": "10.00",
            "is_trial": False,
            "sort_order": 1,
        },
    )
    version = create_plan_version(plan_id=plan.pk, actor=admin, expected_plan_version=plan.version)
    version = publish_plan_version(
        version_id=version.pk,
        actor=admin,
        expected_version=version.version,
        confirm_informal_composite=True,
    )
    plan.refresh_from_db()
    return plan, version


def apply(applicant, plan, version, key):
    return create_application(
        applicant=applicant,
        plan_id=plan.pk,
        plan_version_id=version.pk,
        user_note="",
        idempotency_key=key,
        request_id=uuid.uuid4(),
    )


def parallel(*operations):
    barrier = threading.Barrier(len(operations))

    def run(operation):
        close_old_connections()
        barrier.wait()
        try:
            return "ok", operation()
        except Exception as exc:
            return "error", exc
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return [future.result() for future in [pool.submit(run, item) for item in operations]]


def setup_application():
    admin = user("13900139000", admin=True)
    applicant = user("13800138000")
    plan, version = published_plan(admin)
    application = apply(applicant, plan, version, "application-pg-key-0001").application
    return admin, applicant, plan, version, application


def test_postgresql_same_idempotency_key_concurrency_creates_once():
    require_postgresql()
    admin, applicant = user("13900139000", admin=True), user("13800138000")
    plan, version = published_plan(admin)
    results = parallel(
        lambda: apply(applicant, plan, version, "application-pg-key-0001"),
        lambda: apply(applicant, plan, version, "application-pg-key-0001"),
    )
    assert [item[0] for item in results].count("ok") == 2
    assert PlanApplication.objects.count() == 1
    assert PlanApplicationEvent.objects.count() == Notification.objects.count() == 1


def test_postgresql_different_keys_same_plan_have_one_open_application():
    require_postgresql()
    admin, applicant = user("13900139000", admin=True), user("13800138000")
    plan, version = published_plan(admin)
    results = parallel(
        lambda: apply(applicant, plan, version, "application-pg-key-0001"),
        lambda: apply(applicant, plan, version, "application-pg-key-0002"),
    )
    assert [item[0] for item in results].count("ok") == 1
    assert any(
        isinstance(item[1], PlanApplicationAlreadyOpen) for item in results if item[0] == "error"
    )


def test_postgresql_apply_offline_and_publish_races_preserve_binding():
    require_postgresql()
    admin, applicant = user("13900139000", admin=True), user("13800138000")
    plan, version = published_plan(admin)
    results = parallel(
        lambda: apply(applicant, plan, version, "application-pg-key-0001"),
        lambda: set_plan_offline(plan_id=plan.pk, actor=admin, expected_version=plan.version),
    )
    assert any(item[0] == "ok" for item in results)
    if PlanApplication.objects.exists():
        application = PlanApplication.objects.get()
        assert application.requested_plan_version_id == version.pk
        assert application.requested_config_digest == version.config_digest


def test_postgresql_apply_new_publication_race_never_rebinds_snapshot():
    require_postgresql()
    admin, applicant = user("13900139000", admin=True), user("13800138000")
    plan, old = published_plan(admin)
    draft = create_plan_version(plan_id=plan.pk, actor=admin, expected_plan_version=plan.version)
    results = parallel(
        lambda: apply(applicant, plan, old, "application-pg-key-0001"),
        lambda: publish_plan_version(
            version_id=draft.pk,
            actor=admin,
            expected_version=draft.version,
            confirm_informal_composite=True,
        ),
    )
    assert any(item[0] == "ok" for item in results)
    if PlanApplication.objects.exists():
        application = PlanApplication.objects.get()
        assert application.requested_plan_version_id == old.pk
        assert application.requested_version_no == old.version_no


@pytest.mark.parametrize("action", ["contact", "close"])
def test_postgresql_cancel_admin_action_race_has_one_transition(action):
    require_postgresql()
    admin, applicant, _, _, application = setup_application()
    context = SimpleNamespace(profile=admin.admin_profile)
    results = parallel(
        lambda: cancel_application(
            user=applicant,
            application_id=application.pk,
            expected_version=1,
            request_id=uuid.uuid4(),
        ),
        lambda: admin_change_application(
            requester=admin,
            admin_context=context,
            application_id=application.pk,
            expected_version=1,
            action=action,
            request_id=uuid.uuid4(),
        ),
    )
    assert [item[0] for item in results].count("ok") == 1
    application.refresh_from_db()
    assert application.version == 2
    assert PlanApplicationEvent.objects.filter(application=application).count() == 2


def test_postgresql_admin_risk_endpoints_lock_only_application_row():
    require_postgresql()
    admin, _, _, _, application = setup_application()
    client = authenticate_admin_client(APIClient(), admin)
    contacted = client.post(
        f"/api/v1/admin/plan-applications/{application.pk}/contact",
        {"expected_version": 1, "confirmed": True},
        format="json",
    )
    assert contacted.status_code == 200
    assert contacted.json()["data"]["status"] == "contacted"
    closed = client.post(
        f"/api/v1/admin/plan-applications/{application.pk}/close",
        {"expected_version": 2, "confirmed": True},
        format="json",
    )
    assert closed.status_code == 200
    assert closed.json()["data"]["status"] == "closed"
    assert (
        AuditEvent.objects.filter(
            action_key__in=("plan_application.contact", "plan_application.close"),
            outcome="executed",
        ).count()
        == 2
    )


def test_postgresql_scope_uses_current_assignment_after_owner_change():
    require_postgresql()
    role = AdminRole.objects.create(name="申请范围角色", data_scope="own")
    admin = user("13900139000", admin=True, superuser=False)
    AdminProfile.objects.create(user=admin, role=role)
    other = user("13700137000", admin=True, superuser=False)
    AdminProfile.objects.create(user=other, role=role)
    applicant = user("13800138000")
    plan, version = published_plan(admin)
    application = apply(applicant, plan, version, "application-pg-key-0001").application
    CustomerAssignment.objects.create(
        customer=application.applicant, owner_admin=admin.admin_profile
    )
    context = SimpleNamespace(profile=admin.admin_profile)
    admin.admin_profile.role.data_scope = "own"
    admin.admin_profile.role.save(update_fields=["data_scope", "updated_at"])
    assert scoped_plan_applications(admin, context).filter(pk=application.pk).exists()
    CustomerAssignment.objects.filter(customer=application.applicant).update(
        owner_admin=other.admin_profile
    )
    assert not scoped_plan_applications(admin, context).filter(pk=application.pk).exists()


def test_postgresql_notification_failure_rolls_back_status_and_event(monkeypatch):
    require_postgresql()
    _, applicant, _, _, application = setup_application()

    def fail_notification(*args, **kwargs):
        raise RuntimeError("notification write failed")

    monkeypatch.setattr(Notification.objects, "create", fail_notification)
    with pytest.raises(RuntimeError):
        cancel_application(
            user=applicant,
            application_id=application.pk,
            expected_version=1,
            request_id=uuid.uuid4(),
        )
    application.refresh_from_db()
    assert application.status == "pending" and application.version == 1
    assert PlanApplicationEvent.objects.filter(application=application).count() == 1


def test_postgresql_binding_and_event_triggers_block_raw_sql_mutation():
    require_postgresql()
    _, _, _, _, application = setup_application()
    event = application.events.get()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE plan_applications SET requested_version_no = 999 WHERE id = %s",
            [application.pk],
        )
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE plan_application_events SET safe_summary = 'changed' WHERE id = %s",
            [event.pk],
        )
