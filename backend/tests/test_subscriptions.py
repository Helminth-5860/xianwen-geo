import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminPermission,
    AdminProfile,
    AdminRole,
    AdminRolePermission,
    AuditEvent,
    CustomerAssignment,
    RiskAction,
    RiskPolicy,
)
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.risk_catalog import CONFIRM, RISK_ACTION_BY_KEY
from apps.plans.application_services import create_application
from apps.plans.models import (
    PlanApplication,
    PlanApplicationEvent,
    Subscription,
    SubscriptionEvent,
)
from apps.plans.services import (
    archive_plan,
    create_plan,
    create_plan_version,
    publish_plan_version,
    set_plan_offline,
    update_plan_version,
)
from apps.plans.subscription_services import (
    SubscriptionConfirmationRequired,
    SubscriptionPlanUnavailable,
    SubscriptionStateConflict,
    SubscriptionTrialAlreadyGranted,
    activate_application,
    current_subscription,
    grant_trial,
    scoped_subscriptions,
    terminate_subscription,
)
from apps.users.models import Notification, User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def seed_catalogs():
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def superuser(phone):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def customer(phone="13800138000"):
    return User.objects.create_user(
        phone=phone,
        nickname="订阅用户",
        password=PASSWORD,
    )


def _plan_limit_value(item):
    if item.value_type == "integer":
        return item.integer_value
    if item.value_type == "boolean":
        return item.boolean_value
    if item.value_type in {"text", "enum"}:
        return item.text_value
    return None if item.json_value == {"value": None} else item.json_value


def published_plan(actor, *, code="formal-plan", trial=False, valid_days=30):
    plan = create_plan(
        plan_id=uuid.uuid4(),
        actor=actor,
        data={
            "code": code,
            "name": "试用套餐" if trial else "正式套餐",
            "description": "公开说明",
            "price_display_mode": "fixed",
            "display_price": "0.00" if trial else "99.00",
            "is_trial": trial,
            "sort_order": 1,
        },
    )
    version = create_plan_version(plan_id=plan.pk, actor=actor, expected_plan_version=plan.version)
    if valid_days != version.valid_days:
        version = update_plan_version(
            version_id=version.pk,
            actor=actor,
            expected_version=version.version,
            valid_days=valid_days,
            queue_priority=version.queue_priority,
            limits=[
                {"key": item.limit_key, "value": _plan_limit_value(item)}
                for item in version.limits.all()
            ],
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
        actor=actor,
        expected_version=version.version,
        confirm_informal_composite=True,
    )
    plan.refresh_from_db()
    return plan, version


def application_for(user, plan, version):
    return create_application(
        applicant=user,
        plan_id=plan.pk,
        plan_version_id=version.pk,
        user_note="请开通",
        idempotency_key=str(uuid.uuid4()),
        request_id=uuid.uuid4(),
    ).application


def admin_client(user):
    return authenticate_admin_client(APIClient(), user)


@pytest.mark.django_db
def test_catalog_modes_use_direct_confirmation_and_handlers_exist():
    for key in ("subscription.open", "subscription.grant_trial", "subscription.terminate"):
        definition = RISK_ACTION_BY_KEY[key]
        action = RiskAction.objects.get(key=key)
        policy = RiskPolicy.objects.get(action=action)
        assert definition.supported_modes == (CONFIRM,)
        assert definition.default_mode == definition.minimum_mode == CONFIRM
        assert action.supported_modes == [CONFIRM]
        assert policy.current_mode == CONFIRM


@pytest.mark.django_db
def test_current_subscription_is_read_only_and_returns_null_for_expired_window():
    admin = superuser("13900139000")
    user = customer()
    plan, version = published_plan(admin, trial=True)
    subscription = grant_trial(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=plan.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    Subscription.objects.filter(pk=subscription.pk).update(
        starts_at=timezone.now() - timedelta(days=2), ends_at=timezone.now() - timedelta(days=1)
    )
    before = SubscriptionEvent.objects.count()
    assert current_subscription(user) is None
    response = APIClient()
    response.force_authenticate(user)
    result = response.get("/api/v1/subscription")
    assert result.status_code == 200
    assert result.json()["data"] == {"current": None}
    subscription.refresh_from_db()
    assert subscription.status == Subscription.Status.ACTIVE
    assert SubscriptionEvent.objects.count() == before


@pytest.mark.django_db
def test_formal_activation_is_atomic_and_uses_bound_snapshot():
    admin = superuser("13900139000")
    user = customer()
    plan, version = published_plan(admin)
    application = application_for(user, plan, version)
    subscription, activated, flags = activate_application(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        application_id=application.pk,
        expected_version=application.version,
        selected_plan_version_id=None,
        confirm_unavailable=False,
        unavailable_reason="",
        confirm_version_override=False,
        override_reason="",
        opening_note="已核验",
        request_id=uuid.uuid4(),
    )
    assert subscription.source_application == application
    assert subscription.plan_version == version
    assert subscription.entitlement_snapshot == version.effective_config
    assert subscription.entitlement_digest == version.config_digest
    assert activated.status == PlanApplication.Status.ACTIVATED
    assert flags["version_override"] is False
    assert (
        SubscriptionEvent.objects.filter(subscription=subscription, event_type="activated").count()
        == 1
    )
    assert (
        PlanApplicationEvent.objects.filter(application=application, event_type="activated").count()
        == 1
    )
    assert Notification.objects.filter(related_subscription=subscription).count() == 1
    with pytest.raises(SubscriptionStateConflict):
        activate_application(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            application_id=application.pk,
            expected_version=activated.version,
            selected_plan_version_id=None,
            confirm_unavailable=False,
            unavailable_reason="",
            confirm_version_override=False,
            override_reason="",
            opening_note="",
            request_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_expired_active_is_transitioned_before_new_formal_subscription():
    admin = superuser("13900139000")
    user = customer()
    trial, _ = published_plan(admin, code="trial-once", trial=True)
    old = grant_trial(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=trial.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    Subscription.objects.filter(pk=old.pk).update(
        starts_at=timezone.now() - timedelta(days=2), ends_at=timezone.now() - timedelta(days=1)
    )
    plan, version = published_plan(admin)
    application = application_for(user, plan, version)
    new, _, _ = activate_application(
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
    old.refresh_from_db()
    assert old.status == Subscription.Status.EXPIRED
    assert old.expired_at is not None and old.version == 2
    assert new.status == Subscription.Status.ACTIVE
    assert SubscriptionEvent.objects.filter(subscription=old, event_type="expired").count() == 1


@pytest.mark.django_db
def test_trial_is_server_selected_and_never_repeatable():
    admin = superuser("13900139000")
    user = customer()
    trial, _ = published_plan(admin, trial=True)
    subscription = grant_trial(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=trial.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    assert subscription.is_trial is True and subscription.source_application is None
    terminate_subscription(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        subscription_id=subscription.pk,
        expected_version=subscription.version,
        reason="结束试用",
        request_id=uuid.uuid4(),
    )
    with pytest.raises(SubscriptionTrialAlreadyGranted):
        grant_trial(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            user_id=user.pk,
            expected_status_version=user.status_version,
            plan_id=trial.pk,
            opening_note="",
            request_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_offline_bound_plan_requires_explicit_confirmation_and_reason():
    admin = superuser("13900139000")
    user = customer()
    plan, version = published_plan(admin)
    application = application_for(user, plan, version)
    set_plan_offline(plan_id=plan.pk, actor=admin, expected_version=plan.version)
    with pytest.raises(SubscriptionConfirmationRequired):
        activate_application(
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


@pytest.mark.django_db
def test_open_api_confirms_then_executes_directly_with_audit():
    requester = superuser("13900139000")
    user = customer()
    plan, version = published_plan(requester)
    application = application_for(user, plan, version)
    requester_client = authenticate_admin_client(APIClient(), requester, step_up=False)
    response = requester_client.post(
        f"/api/v1/admin/plan-applications/{application.pk}/activate",
        {"expected_version": application.version, "confirmed": True},
        format="json",
    )
    assert response.status_code == 200
    application.refresh_from_db()
    assert application.status == PlanApplication.Status.ACTIVATED
    assert Subscription.objects.filter(source_application=application).count() == 1
    assert (
        AuditEvent.objects.filter(action_key="subscription.open", outcome="executed").count() == 1
    )


@pytest.mark.django_db
def test_trial_api_rejects_client_controlled_trial_and_version_fields():
    admin = superuser("13900139000")
    user = customer()
    trial, version = published_plan(admin, trial=True)
    response = admin_client(admin).post(
        f"/api/v1/admin/users/{user.pk}/subscriptions/trial",
        {
            "expected_version": user.status_version,
            "plan_id": str(trial.pk),
            "is_trial": True,
            "plan_version_id": str(version.pk),
        },
        format="json",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_user_response_excludes_snapshot_digest_and_internal_notes():
    admin = superuser("13900139000")
    user = customer()
    trial, _ = published_plan(admin, trial=True)
    grant_trial(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=trial.pk,
        opening_note="内部备注",
        request_id=uuid.uuid4(),
    )
    client = APIClient()
    client.force_authenticate(user)
    payload = client.get("/api/v1/subscription").json()["data"]["current"]
    serialized = str(payload)
    assert "entitlement_snapshot" not in payload
    assert "entitlement_digest" not in payload
    assert "opening_note" not in payload
    assert "内部备注" not in serialized


@pytest.mark.django_db
def test_orm_delete_guards_and_terminal_service_transition():
    admin = superuser("13900139000")
    user = customer()
    trial, _ = published_plan(admin, trial=True)
    subscription = grant_trial(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=trial.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    with pytest.raises(TypeError):
        subscription.delete()
    with pytest.raises(TypeError):
        SubscriptionEvent.objects.filter(subscription=subscription).delete()
    terminated = terminate_subscription(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        subscription_id=subscription.pk,
        expected_version=subscription.version,
        reason="管理员终止",
        request_id=uuid.uuid4(),
    )
    with pytest.raises(SubscriptionStateConflict):
        terminate_subscription(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            subscription_id=terminated.pk,
            expected_version=terminated.version,
            reason="重复终止",
            request_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_subscription_scope_is_consistent_for_own_role_all_and_object_404():
    root = superuser("13900139000")
    trial, _ = published_plan(root, code="scope-trial", trial=True)
    role = AdminRole.objects.create(name="订阅客户经理", data_scope=AdminRole.DataScope.OWN)
    peer_role = AdminRole.objects.create(name="其他客户组", data_scope=AdminRole.DataScope.OWN)
    manager_user = User.objects.create_user(
        phone="13700137010",
        nickname="客户经理甲",
        password=PASSWORD,
        is_staff=True,
    )
    peer_user = User.objects.create_user(
        phone="13700137011",
        nickname="客户经理乙",
        password=PASSWORD,
        is_staff=True,
    )
    outsider_user = User.objects.create_user(
        phone="13700137012",
        nickname="其他组管理员",
        password=PASSWORD,
        is_staff=True,
    )
    manager = AdminProfile.objects.create(user=manager_user, role=role)
    peer = AdminProfile.objects.create(user=peer_user, role=role)
    outsider = AdminProfile.objects.create(user=outsider_user, role=peer_role)
    permissions = AdminPermission.objects.filter(
        key__in=("subscriptions.list", "subscriptions.view")
    )
    AdminRolePermission.objects.bulk_create(
        [AdminRolePermission(role=role, permission=permission) for permission in permissions]
    )
    customers = [customer(f"1360013600{index}") for index in range(4)]
    subscriptions = []
    for item, owner in zip(customers, (manager, peer, outsider, outsider), strict=True):
        CustomerAssignment.objects.create(customer=item, owner_admin=owner)
        subscriptions.append(
            grant_trial(
                requester=root,
                admin_context=resolve_admin_context(root),
                user_id=item.pk,
                expected_status_version=item.status_version,
                plan_id=trial.pk,
                opening_note="",
                request_id=uuid.uuid4(),
            )
        )

    context = SimpleNamespace(profile=manager)
    assert list(scoped_subscriptions(manager_user, context).values_list("pk", flat=True)) == [
        subscriptions[0].pk
    ]
    client = admin_client(manager_user)
    own_list = client.get("/api/v1/admin/subscriptions")
    assert own_list.status_code == 200
    assert own_list.json()["data"]["pagination"]["count"] == 1
    assert client.get(f"/api/v1/admin/subscriptions/{subscriptions[1].pk}").status_code == 404

    role.data_scope = AdminRole.DataScope.ROLE
    role.save(update_fields=["data_scope", "updated_at"])
    context = SimpleNamespace(
        profile=AdminProfile.objects.select_related("role").get(pk=manager.pk)
    )
    assert scoped_subscriptions(manager_user, context).count() == 1

    role.data_scope = AdminRole.DataScope.ALL
    role.save(update_fields=["data_scope", "updated_at"])
    context = SimpleNamespace(
        profile=AdminProfile.objects.select_related("role").get(pk=manager.pk)
    )
    assert scoped_subscriptions(manager_user, context).count() == 1


@pytest.mark.django_db
def test_formal_activation_rejects_bound_snapshot_digest_drift():
    admin = superuser("13900139000")
    user = customer()
    plan, version = published_plan(admin)
    application = application_for(user, plan, version)
    PlanApplication.objects.filter(pk=application.pk).update(requested_config_digest="0" * 64)
    application.refresh_from_db()
    with pytest.raises(Exception) as error:
        activate_application(
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
    assert getattr(error.value, "code", None) == "SUBSCRIPTION_PLAN_VERSION_MISMATCH"


@pytest.mark.django_db
def test_version_override_requires_independent_permission_before_direct_execution():
    root = superuser("13900139000")
    user = customer()
    plan, requested_version = published_plan(root, code="override-permission")
    application = application_for(user, plan, requested_version)
    override_version = create_plan_version(
        plan_id=plan.pk,
        actor=root,
        expected_plan_version=plan.version,
    )
    role = AdminRole.objects.create(name="订阅开通员", data_scope=AdminRole.DataScope.ALL)
    manager_user = User.objects.create_user(
        phone="13700137020",
        nickname="订阅开通员",
        password=PASSWORD,
        is_staff=True,
    )
    manager = AdminProfile.objects.create(user=manager_user, role=role)
    CustomerAssignment.objects.create(customer=user, owner_admin=manager)
    permissions = AdminPermission.objects.filter(key="subscriptions.open")
    AdminRolePermission.objects.bulk_create(
        [AdminRolePermission(role=role, permission=permission) for permission in permissions]
    )

    response = admin_client(manager_user).post(
        f"/api/v1/admin/plan-applications/{application.pk}/activate",
        {
            "expected_version": application.version,
            "selected_plan_version_id": str(override_version.pk),
            "confirm_version_override": True,
            "override_reason": "管理员明确选择同套餐其他版本",
        },
        format="json",
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.django_db
def test_trial_stores_deterministic_31_day_anchor_and_valid_days_window():
    admin = superuser("13900139000")
    user = customer()
    trial, version = published_plan(admin, trial=True)
    starts_at = datetime(2026, 1, 31, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    with patch("apps.plans.subscription_services.timezone.now", return_value=starts_at):
        subscription = grant_trial(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            user_id=user.pk,
            expected_status_version=user.status_version,
            plan_id=trial.pk,
            opening_note="",
            request_id=uuid.uuid4(),
        )
    assert subscription.starts_at == starts_at
    assert subscription.ends_at == starts_at + timedelta(days=version.valid_days)
    assert subscription.cycle_anchor_day == 31


@pytest.mark.django_db
def test_subscription_write_endpoint_requires_real_csrf():
    admin = superuser("13900139000")
    user = customer()
    trial, _ = published_plan(admin, trial=True)
    client = authenticate_admin_client(APIClient(enforce_csrf_checks=True), admin)
    response = client.post(
        f"/api/v1/admin/users/{user.pk}/subscriptions/trial",
        {
            "expected_version": user.status_version,
            "plan_id": str(trial.pk),
        },
        format="json",
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.django_db
def test_trial_current_version_and_unavailable_plan_boundaries():
    admin = superuser("13900139000")
    trial, _ = published_plan(admin, code="unavailable-trial", trial=True)
    current_version_id = trial.current_published_version_id
    first_user = customer()
    subscription = grant_trial(
        requester=admin,
        admin_context=resolve_admin_context(admin),
        user_id=first_user.pk,
        expected_status_version=first_user.status_version,
        plan_id=trial.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    assert subscription.plan_version_id == current_version_id

    trial = set_plan_offline(
        plan_id=trial.pk,
        actor=admin,
        expected_version=trial.version,
    )
    offline_user = customer("13700137000")
    with pytest.raises(SubscriptionPlanUnavailable):
        grant_trial(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            user_id=offline_user.pk,
            expected_status_version=offline_user.status_version,
            plan_id=trial.pk,
            opening_note="",
            request_id=uuid.uuid4(),
        )
    trial = archive_plan(
        plan_id=trial.pk,
        actor=admin,
        expected_version=trial.version,
    )
    archived_trial_user = customer("13600136000")
    with pytest.raises(SubscriptionPlanUnavailable):
        grant_trial(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            user_id=archived_trial_user.pk,
            expected_status_version=archived_trial_user.status_version,
            plan_id=trial.pk,
            opening_note="",
            request_id=uuid.uuid4(),
        )

    formal_user = customer("13500135000")
    formal, version = published_plan(admin, code="archived-formal")
    application = application_for(formal_user, formal, version)
    formal = set_plan_offline(
        plan_id=formal.pk,
        actor=admin,
        expected_version=formal.version,
    )
    archive_plan(
        plan_id=formal.pk,
        actor=admin,
        expected_version=formal.version,
    )
    with pytest.raises(SubscriptionPlanUnavailable):
        activate_application(
            requester=admin,
            admin_context=resolve_admin_context(admin),
            application_id=application.pk,
            expected_version=application.version,
            selected_plan_version_id=None,
            confirm_unavailable=True,
            unavailable_reason="确认归档边界",
            confirm_version_override=False,
            override_reason="",
            opening_note="",
            request_id=uuid.uuid4(),
        )
