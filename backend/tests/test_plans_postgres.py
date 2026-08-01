import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from rest_framework.test import APIClient

from apps.admin_rbac.models import ApprovalRequest, AuditEvent, RiskPolicy
from apps.admin_rbac.risk_handlers import HANDLER_SPECS
from apps.plans.models import Plan, PlanLimit, PlanModelPermission, PlanVersion
from apps.plans.services import (
    PlanDomainError,
    archive_plan,
    build_effective_config,
    create_plan,
    create_plan_version,
    publish_plan_version,
    set_plan_offline,
)
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

pytestmark = pytest.mark.django_db(transaction=True)
TEST_PASSWORD = secrets.token_urlsafe(32)


@pytest.fixture(autouse=True)
def seed_catalog():
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def require_postgresql():
    if connection.vendor != "postgresql":
        pytest.skip("仅通过 scripts/test-plans.* 在真实 PostgreSQL 执行。")


def actor(phone="13900139000", *, password=None):
    user = User(
        phone=phone,
        nickname="套餐并发管理员",
        is_staff=True,
        is_superuser=True,
        account_status=User.AccountStatus.ACTIVE,
    )
    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    user.synchronize_active_state()
    user.save()
    return user


def admin_client(user):
    return authenticate_admin_client(APIClient(), user)


def plan_for(user, code="postgres-plan"):
    return create_plan(
        plan_id=uuid.uuid4(),
        actor=user,
        data={
            "code": code,
            "name": "PG 套餐",
            "description": "",
            "price_display_mode": "fixed",
            "display_price": "10.00",
            "is_trial": False,
            "sort_order": 0,
        },
    )


def draft_for(user, plan):
    return create_plan_version(plan_id=plan.pk, actor=user, expected_plan_version=plan.version)


def publish(user, version):
    return publish_plan_version(
        version_id=version.pk,
        actor=user,
        expected_version=version.version,
        confirm_informal_composite=True,
    )


def parallel(*operations):
    barrier = threading.Barrier(len(operations))

    def run(operation):
        close_old_connections()
        barrier.wait()
        try:
            return ("ok", operation())
        except Exception as exc:
            return ("error", exc)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return [future.result() for future in [pool.submit(run, item) for item in operations]]


def assert_pointer(plan):
    plan.refresh_from_db()
    current = plan.current_published_version
    if plan.status == Plan.Status.DRAFT:
        assert current is None
    elif plan.status == Plan.Status.PUBLISHED:
        assert current is not None and current.status == PlanVersion.Status.PUBLISHED
    elif plan.status == Plan.Status.OFFLINE and current is not None:
        assert current.status == PlanVersion.Status.PUBLISHED
    elif plan.status == Plan.Status.ARCHIVED:
        assert current is None


def test_postgresql_version_number_concurrency_has_one_draft():
    require_postgresql()
    user = actor()
    plan = plan_for(user)
    expected = plan.version
    results = parallel(
        lambda: create_plan_version(plan_id=plan.pk, actor=user, expected_plan_version=expected),
        lambda: create_plan_version(plan_id=plan.pk, actor=user, expected_plan_version=expected),
    )
    assert [item[0] for item in results].count("ok") == 1
    assert PlanVersion.objects.filter(plan=plan, status="draft").count() == 1
    assert list(PlanVersion.objects.filter(plan=plan).values_list("version_no", flat=True)) == [1]


def test_postgresql_publish_concurrency_has_one_execution():
    require_postgresql()
    user = actor()
    plan = plan_for(user)
    draft = draft_for(user, plan)
    results = parallel(lambda: publish(user, draft), lambda: publish(user, draft))
    assert [item[0] for item in results].count("ok") == 1
    assert PlanVersion.objects.filter(plan=plan, status="published").count() == 1
    assert_pointer(plan)


def test_postgresql_publish_offline_race_preserves_pointer():
    require_postgresql()
    user = actor()
    plan = plan_for(user)
    publish(user, draft_for(user, plan))
    plan.refresh_from_db()
    new = draft_for(user, plan)
    plan.refresh_from_db()
    results = parallel(
        lambda: publish_plan_version(
            version_id=new.pk,
            actor=user,
            expected_version=new.version,
            confirm_informal_composite=True,
        ),
        lambda: set_plan_offline(plan_id=plan.pk, actor=user, expected_version=plan.version),
    )
    assert any(item[0] == "ok" for item in results)
    assert_pointer(plan)


def test_postgresql_publish_archive_race_has_valid_terminal_state():
    require_postgresql()
    user = actor()
    plan = plan_for(user)
    publish(user, draft_for(user, plan))
    plan.refresh_from_db()
    plan = set_plan_offline(plan_id=plan.pk, actor=user, expected_version=plan.version)
    new = draft_for(user, plan)
    plan.refresh_from_db()
    results = parallel(
        lambda: publish_plan_version(
            version_id=new.pk,
            actor=user,
            expected_version=new.version,
            confirm_informal_composite=True,
        ),
        lambda: archive_plan(plan_id=plan.pk, actor=user, expected_version=plan.version),
    )
    assert any(item[0] == "ok" for item in results)
    assert_pointer(plan)


def test_postgresql_pointer_consistency_through_new_publication():
    require_postgresql()
    user = actor()
    plan = plan_for(user)
    old = publish(user, draft_for(user, plan))
    plan.refresh_from_db()
    new = publish(user, draft_for(user, plan))
    old.refresh_from_db()
    plan.refresh_from_db()
    assert old.status == "retired" and new.status == "published"
    assert plan.current_published_version_id == new.pk
    assert_pointer(plan)


def test_postgresql_version_trigger_blocks_queryset_bulk_and_raw_sql():
    require_postgresql()
    user = actor()
    version = publish(user, draft_for(user, plan_for(user)))
    with pytest.raises(DatabaseError), transaction.atomic():
        PlanVersion.objects.filter(pk=version.pk).update(valid_days=999)
    version.valid_days = 998
    with pytest.raises(DatabaseError), transaction.atomic():
        PlanVersion.objects.bulk_update([version], ["valid_days"])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE plan_versions SET queue_priority = 999 WHERE id = %s", [version.pk])


def test_postgresql_entitlement_triggers_block_child_mutations():
    require_postgresql()
    user = actor()
    version = publish(user, draft_for(user, plan_for(user)))
    limit_row = version.limits.first()
    model_row = version.model_permissions.first()
    with pytest.raises(DatabaseError), transaction.atomic():
        PlanLimit.objects.filter(pk=limit_row.pk).update(integer_value=999)
    with pytest.raises(DatabaseError), transaction.atomic():
        PlanModelPermission.objects.filter(pk=model_row.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM plan_limits WHERE id = %s", [limit_row.pk])


def test_postgresql_snapshot_digest_and_shared_approval_orchestrator():
    require_postgresql()
    requester = actor(password=TEST_PASSWORD)
    approver = actor("13700137000", password=TEST_PASSWORD)
    plan = plan_for(requester)
    version = publish(requester, draft_for(requester, plan))
    snapshot, digest = build_effective_config(version, version.snapshot_generated_at)
    assert snapshot == version.effective_config and digest == version.config_digest
    plan.refresh_from_db()
    plan = set_plan_offline(plan_id=plan.pk, actor=requester, expected_version=plan.version)

    requested = admin_client(requester).post(
        f"/api/v1/admin/plans/{plan.pk}/archive",
        {"expected_version": plan.version, "confirmed": True},
        format="json",
    )
    assert requested.status_code == 202
    approval = ApprovalRequest.objects.get(pk=requested.json()["data"]["approval_id"])
    first = admin_client(approver)
    second = admin_client(approver)
    responses = parallel(
        lambda: first.post(
            f"/api/v1/admin/approvals/{approval.pk}/approve",
            {"current_password": TEST_PASSWORD},
            format="json",
        ),
        lambda: second.post(
            f"/api/v1/admin/approvals/{approval.pk}/approve",
            {"current_password": TEST_PASSWORD},
            format="json",
        ),
    )

    assert sorted(item[1].status_code for item in responses if item[0] == "ok") == [200, 409]
    approval.refresh_from_db()
    plan.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.EXECUTED
    assert plan.status == Plan.Status.ARCHIVED
    assert AuditEvent.objects.filter(approval_request=approval, outcome="executed").count() == 1
    assert HANDLER_SPECS["plan.archive"].execute is not None
    assert RiskPolicy.objects.get(action_id="plan.archive").current_mode == "two_person"
    assert issubclass(PlanDomainError, Exception)
