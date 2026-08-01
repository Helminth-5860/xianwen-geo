import uuid
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.management import call_command
from django.urls import resolve
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminProfile,
    AdminRole,
    AuditEvent,
    CustomerAssignment,
    RiskAction,
    RiskPolicy,
)
from apps.admin_rbac.risk_handlers import HANDLER_REGISTRY, HANDLER_SPECS
from apps.plans.application_services import scoped_plan_applications
from apps.plans.models import PlanApplication, PlanApplicationEvent
from apps.plans.services import (
    create_plan,
    create_plan_version,
    publish_plan_version,
    set_plan_offline,
)
from apps.users.models import Notification, User
from tests.admin_session_helpers import authenticate_admin_client


@pytest.fixture(autouse=True)
def seed_catalogs():
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def make_user(phone="13800138000", *, approval="pending", account="active", staff=False):
    user = User(
        phone=phone,
        nickname="申请用户",
        approval_status=approval,
        account_status=account,
        is_staff=staff,
        is_superuser=False,
    )
    user.set_unusable_password()
    user.synchronize_active_state()
    user.save()
    return user


def make_admin(phone="13900139000"):
    user = User(
        phone=phone,
        nickname="套餐管理员",
        approval_status="approved",
        account_status="active",
        is_staff=True,
        is_superuser=True,
    )
    user.set_unusable_password()
    user.synchronize_active_state()
    user.save()
    return user


def make_published_plan(admin, *, code="application-plan", trial=False):
    plan = create_plan(
        plan_id=uuid.uuid4(),
        actor=admin,
        data={
            "code": code,
            "name": "申请套餐",
            "description": "公开套餐说明",
            "price_display_mode": "fixed",
            "display_price": "99.00",
            "is_trial": trial,
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


def user_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _idempotency_value(index):
    return str(uuid.UUID(int=index))


def create_application(client, plan, version, *, key=None, note="请联系我"):
    if key is None:
        key = _idempotency_value(1)
    return client.post(
        "/api/v1/plan-applications",
        {"plan_id": str(plan.pk), "plan_version_id": str(version.pk), "user_note": note},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("approval", ["pending", "approved"])
def test_pending_and_approved_user_can_apply_with_bound_public_snapshot(approval):
    admin = make_admin()
    plan, version = make_published_plan(admin)
    response = create_application(user_client(make_user(approval=approval)), plan, version)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "pending"
    assert data["requested_plan_version_id"] == str(version.pk)
    assert data["requested_version_no"] == version.version_no
    assert data["public_plan_snapshot"]["name"] == "申请套餐"
    assert "effective_config" not in data["public_plan_snapshot"]
    application = PlanApplication.objects.get(pk=data["id"])
    assert application.requested_config_digest == version.config_digest
    assert len(application.idempotency_key_digest) == 64
    assert PlanApplicationEvent.objects.filter(application=application).count() == 1
    assert Notification.objects.filter(related_plan_application=application).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("approval", "account"),
    [
        ("rejected", "active"),
        ("pending", "cancel_pending"),
        ("pending", "frozen"),
        ("pending", "cancelled"),
    ],
)
def test_ineligible_approval_and_account_states_are_rejected(approval, account):
    admin = make_admin()
    plan, version = make_published_plan(admin)
    response = create_application(
        user_client(make_user(approval=approval, account=account)), plan, version
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PLAN_APPLICATION_NOT_ELIGIBLE"
    assert not PlanApplication.objects.exists()


@pytest.mark.django_db
def test_staff_superuser_profile_and_trial_are_not_eligible():
    admin = make_admin()
    plan, version = make_published_plan(admin)
    staff = make_user("13700137000", staff=True)
    assert create_application(user_client(staff), plan, version).status_code == 403
    ordinary = make_user("13600136000")
    AdminProfile.objects.create(user=ordinary)
    assert create_application(user_client(ordinary), plan, version).status_code == 403
    trial, trial_version = make_published_plan(admin, code="trial-plan", trial=True)
    response = create_application(user_client(make_user("13500135000")), trial, trial_version)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PLAN_APPLICATION_NOT_ELIGIBLE"


@pytest.mark.django_db
def test_idempotency_required_replay_payload_conflict_and_open_conflict():
    admin = make_admin()
    plan, version = make_published_plan(admin)
    client = user_client(make_user())
    missing = client.post(
        "/api/v1/plan-applications",
        {"plan_id": str(plan.pk), "plan_version_id": str(version.pk)},
        format="json",
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    first = create_application(client, plan, version)
    replay = create_application(client, plan, version)
    assert first.status_code == 201 and replay.status_code == 200
    assert first.json()["data"]["id"] == replay.json()["data"]["id"]
    assert PlanApplicationEvent.objects.count() == 1
    conflict = create_application(client, plan, version, note="不同内容")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    opened = create_application(client, plan, version, key=_idempotency_value(2))
    assert opened.status_code == 409
    assert opened.json()["error"]["code"] == "PLAN_APPLICATION_ALREADY_OPEN"
    assert (
        opened.json()["error"]["details"]["existing_application_id"] == first.json()["data"]["id"]
    )


@pytest.mark.django_db
def test_different_plans_and_reapply_after_cancel_are_supported():
    admin = make_admin()
    first_plan, first_version = make_published_plan(admin)
    second_plan, second_version = make_published_plan(admin, code="application-plan-2")
    client = user_client(make_user())
    first = create_application(client, first_plan, first_version)
    second = create_application(client, second_plan, second_version, key=_idempotency_value(2))
    assert first.status_code == second.status_code == 201
    first_data = first.json()["data"]
    cancelled = client.post(
        f"/api/v1/plan-applications/{first_data['id']}/cancel",
        {"expected_version": first_data["version"]},
        format="json",
    )
    assert cancelled.status_code == 200 and cancelled.json()["data"]["status"] == "cancelled"
    reapplied = create_application(client, first_plan, first_version, key=_idempotency_value(3))
    assert reapplied.status_code == 201


@pytest.mark.django_db
def test_user_ownership_lists_details_and_csrf():
    admin = make_admin()
    plan, version = make_published_plan(admin)
    owner, outsider = make_user(), make_user("13700137001")
    created = create_application(user_client(owner), plan, version).json()["data"]
    owner_client = user_client(owner)
    assert owner_client.get("/api/v1/plan-applications").json()["data"]["pagination"]["count"] == 1
    assert owner_client.get(f"/api/v1/plan-applications/{created['id']}").status_code == 200
    assert (
        user_client(outsider).get(f"/api/v1/plan-applications/{created['id']}").status_code == 404
    )
    csrf_client = APIClient(enforce_csrf_checks=True)
    csrf_client.force_authenticate(owner)
    blocked = csrf_client.post(
        f"/api/v1/plan-applications/{created['id']}/cancel",
        {"expected_version": created["version"]},
        format="json",
    )
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.django_db
def test_admin_contact_close_risk_path_events_notifications_and_audit():
    admin = make_admin()
    plan, version = make_published_plan(admin)
    application = create_application(user_client(make_user()), plan, version).json()["data"]
    client = authenticate_admin_client(APIClient(), admin)
    missing_confirm = client.post(
        f"/api/v1/admin/plan-applications/{application['id']}/contact",
        {"expected_version": 1},
        format="json",
    )
    assert missing_confirm.status_code == 422
    contacted = client.post(
        f"/api/v1/admin/plan-applications/{application['id']}/contact",
        {"expected_version": 1, "confirmed": True},
        format="json",
    )
    assert contacted.status_code == 200 and contacted.json()["data"]["status"] == "contacted"
    closed = client.post(
        f"/api/v1/admin/plan-applications/{application['id']}/close",
        {"expected_version": 2, "confirmed": True},
        format="json",
    )
    assert closed.status_code == 200 and closed.json()["data"]["status"] == "closed"
    duplicate = client.post(
        f"/api/v1/admin/plan-applications/{application['id']}/close",
        {"expected_version": 3, "confirmed": True},
        format="json",
    )
    assert duplicate.status_code == 409
    assert PlanApplicationEvent.objects.filter(application_id=application["id"]).count() == 3
    assert Notification.objects.filter(related_plan_application_id=application["id"]).count() == 3
    assert (
        AuditEvent.objects.filter(
            action_key__in=("plan_application.contact", "plan_application.close"),
            outcome="executed",
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_dynamic_own_role_all_scope_and_unassigned():
    admin = make_admin()
    plan, version = make_published_plan(admin)
    role = AdminRole.objects.create(name="申请组", data_scope="own")
    peer_role = AdminRole.objects.create(name="其他组", data_scope="own")
    owner_a = AdminProfile.objects.create(user=make_user("13700137010", staff=True), role=role)
    owner_b = AdminProfile.objects.create(user=make_user("13700137011", staff=True), role=role)
    owner_c = AdminProfile.objects.create(user=make_user("13700137012", staff=True), role=peer_role)
    customers = [make_user(f"1360013600{index}") for index in range(4)]
    for index, owner in enumerate((owner_a, owner_b, owner_c, None)):
        CustomerAssignment.objects.create(customer=customers[index], owner_admin=owner)
        create_application(
            user_client(customers[index]), plan, version, key=f"application-key-100{index}"
        )
    context = SimpleNamespace(profile=owner_a)
    assert scoped_plan_applications(owner_a.user, context).count() == 1
    role.data_scope = "role"
    role.save(update_fields=["data_scope", "updated_at"])
    assert scoped_plan_applications(owner_a.user, context).count() == 2
    role.data_scope = "all"
    role.save(update_fields=["data_scope", "updated_at"])
    assert scoped_plan_applications(owner_a.user, context).count() == 4
    CustomerAssignment.objects.filter(customer=customers[0]).update(owner_admin=owner_c)
    role.data_scope = "own"
    role.save(update_fields=["data_scope", "updated_at"])
    assert scoped_plan_applications(owner_a.user, context).count() == 0


@pytest.mark.django_db
def test_binding_survives_plan_offline_and_no_forbidden_business_models():
    admin = make_admin()
    plan, version = make_published_plan(admin)
    created = create_application(user_client(make_user()), plan, version).json()["data"]
    original = created["public_plan_snapshot"]
    plan = set_plan_offline(plan_id=plan.pk, actor=admin, expected_version=plan.version)
    application = PlanApplication.objects.get(pk=created["id"])
    assert application.public_plan_snapshot == original
    assert application.requested_plan_version_id == version.pk
    assert {model.__name__ for model in apps.get_models()}.isdisjoint(
        {"Subscription", "QuotaAccount", "Order", "Payment", "Refund", "Invoice", "Contract"}
    )


@pytest.mark.django_db
def test_event_is_append_only_catalogs_and_routes_are_complete():
    assert {
        "plan_applications.list",
        "plan_applications.view",
        "plan_applications.contact",
        "plan_applications.close",
    } <= {item.key for item in apps.get_model("admin_rbac", "AdminPermission").objects.all()}
    for key in ("plan_application.contact", "plan_application.close"):
        assert key in HANDLER_REGISTRY and key in HANDLER_SPECS
        assert RiskAction.objects.get(pk=key).minimum_mode == "confirm"
        assert RiskPolicy.objects.get(action_id=key).current_mode == "confirm"
    routes = {
        "/api/v1/plan-applications": "plan-application-list-create",
        f"/api/v1/plan-applications/{uuid.uuid4()}": "plan-application-detail",
        f"/api/v1/plan-applications/{uuid.uuid4()}/cancel": "plan-application-cancel",
        "/api/v1/admin/plan-applications": "admin-plan-application-list",
        f"/api/v1/admin/plan-applications/{uuid.uuid4()}": "admin-plan-application-detail",
        f"/api/v1/admin/plan-applications/{uuid.uuid4()}/contact": "admin-plan-application-contact",
        f"/api/v1/admin/plan-applications/{uuid.uuid4()}/close": "admin-plan-application-close",
    }
    for path, name in routes.items():
        assert resolve(path).url_name == name
    assert APIClient().post("/api/v1/package-applications", {}, format="json").status_code == 404
    event = PlanApplicationEvent()
    with pytest.raises(TypeError):
        event.delete()
