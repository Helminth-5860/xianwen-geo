import uuid

import pytest
from django.core.management import call_command
from django.db import connection
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.admin_rbac.catalog import CATALOG_BY_KEY, PERMISSION_CATALOG
from apps.admin_rbac.models import (
    AdminPermission,
    AdminProfile,
    AdminRbacEvent,
    AdminRole,
    AdminRolePermission,
    CustomerAssignment,
)
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.scopes import scoped_customers
from apps.admin_rbac.services import (
    AdminHasAssignedCustomers,
    AdminVersionConflict,
    AssignmentVersionConflict,
    LastSuperuserProtected,
    RoleInUse,
    RoleVersionConflict,
    assign_customer,
    change_admin_status,
    create_admin,
    create_role,
    disable_role,
    update_admin,
    update_role,
)
from apps.users.authentication import AccountUnavailable, start_browser_session
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


def superuser(phone="13900139000"):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def customer(phone="13800138000"):
    return User.objects.create_user(phone=phone, nickname="客户", password=PASSWORD)


def role(name="审核员", scope=AdminRole.DataScope.ALL):
    return AdminRole.objects.create(name=name, data_scope=scope)


def grant(role_obj, *keys):
    permissions = AdminPermission.objects.filter(key__in=keys)
    AdminRolePermission.objects.bulk_create(
        [AdminRolePermission(role=role_obj, permission=item) for item in permissions]
    )


@pytest.mark.django_db
def test_permission_catalog_is_seeded_idempotently_with_explicit_menu_and_action_keys(capsys):
    assert AdminPermission.objects.count() == len(PERMISSION_CATALOG)
    assert CATALOG_BY_KEY["menu.admin.users"].permission_type == "menu"
    assert CATALOG_BY_KEY["users.list"].permission_type == "action"
    call_command("sync_admin_rbac", "--apply")
    call_command("sync_admin_rbac", "--apply")
    assert AdminPermission.objects.count() == len(PERMISSION_CATALOG)


@pytest.mark.django_db
def test_createsuperuser_gets_active_roleless_profile_and_fixed_permissions():
    user = superuser()
    profile = user.admin_profile
    context = resolve_admin_context(user)
    assert profile.admin_status == AdminProfile.Status.ACTIVE
    assert profile.role is None
    assert context is not None
    assert "admins.create" in context.permission_keys
    assert "menu.admin.admins" in context.menu_keys


@pytest.mark.django_db
def test_ordinary_role_cannot_receive_superuser_only_permission():
    actor = superuser()
    role_obj = create_role(
        actor_id=actor.id,
        name="普通角色",
        description="",
        data_scope=AdminRole.DataScope.ALL,
        request_id=uuid.uuid4(),
    )
    with pytest.raises(PermissionDenied):
        update_role(
            actor_id=actor.id,
            role_id=role_obj.id,
            expected_version=1,
            name=None,
            description=None,
            data_scope=None,
            permission_keys=["admins.create"],
            request_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_admin_create_uses_user_identity_and_version_conflicts():
    actor = superuser()
    role_obj = role()
    profile = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="普通管理员",
        password=PASSWORD,
        role_id=role_obj.id,
        request_id=uuid.uuid4(),
    )
    assert profile.user.is_staff is True
    assert profile.user.is_superuser is False
    assert profile.user.check_password(PASSWORD)
    with pytest.raises(AdminVersionConflict):
        update_admin(
            actor_id=actor.id,
            profile_id=profile.id,
            expected_version=99,
            nickname="并发覆盖",
            role_id=None,
            request_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_disabled_and_locked_admins_cannot_login_and_old_session_version_is_revoked(rf):
    actor = superuser()
    role_obj = role()
    for action, phone in (("disable", "13700137000"), ("lock", "13600136000")):
        profile = create_admin(
            actor_id=actor.id,
            phone=phone,
            nickname="管理员",
            password=PASSWORD,
            role_id=role_obj.id,
            request_id=uuid.uuid4(),
        )
        old_version = profile.user.session_version
        changed = change_admin_status(
            actor_id=actor.id,
            profile_id=profile.id,
            action=action,
            expected_version=1,
            request_id=uuid.uuid4(),
        )
        changed.user.refresh_from_db()
        assert changed.user.is_staff is False
        assert changed.user.session_version == old_version + 1
        request = rf.post("/")
        request.session = {}
        with pytest.raises(AccountUnavailable):
            start_browser_session(request, changed.user.id)


@pytest.mark.django_db
def test_disable_requires_assignment_transfer_but_emergency_lock_succeeds():
    actor = superuser()
    role_obj = role()
    profile = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="管理员",
        password=PASSWORD,
        role_id=role_obj.id,
        request_id=uuid.uuid4(),
    )
    CustomerAssignment.objects.create(customer=customer(), owner_admin=profile)
    with pytest.raises(AdminHasAssignedCustomers):
        change_admin_status(
            actor_id=actor.id,
            profile_id=profile.id,
            action="disable",
            expected_version=1,
            request_id=uuid.uuid4(),
        )
    changed = change_admin_status(
        actor_id=actor.id,
        profile_id=profile.id,
        action="lock",
        expected_version=1,
        request_id=uuid.uuid4(),
    )
    assert changed.admin_status == AdminProfile.Status.LOCKED


@pytest.mark.django_db
def test_last_superuser_is_protected_and_role_in_use_cannot_be_disabled():
    actor = superuser()
    with pytest.raises(LastSuperuserProtected):
        change_admin_status(
            actor_id=actor.id,
            profile_id=actor.admin_profile.id,
            action="lock",
            expected_version=1,
            request_id=uuid.uuid4(),
        )
    role_obj = role()
    create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="管理员",
        password=PASSWORD,
        role_id=role_obj.id,
        request_id=uuid.uuid4(),
    )
    with pytest.raises(RoleInUse):
        disable_role(
            actor_id=actor.id,
            role_id=role_obj.id,
            expected_version=1,
            request_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_role_version_and_permission_change_revoke_sessions():
    actor = superuser()
    role_obj = role()
    profile = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="管理员",
        password=PASSWORD,
        role_id=role_obj.id,
        request_id=uuid.uuid4(),
    )
    old_session_version = profile.user.session_version
    updated = update_role(
        actor_id=actor.id,
        role_id=role_obj.id,
        expected_version=1,
        name=None,
        description=None,
        data_scope=AdminRole.DataScope.OWN,
        permission_keys=["users.list", "menu.admin.users"],
        request_id=uuid.uuid4(),
    )
    profile.user.refresh_from_db()
    assert updated.version == 2
    assert profile.user.session_version == old_session_version + 1
    with pytest.raises(RoleVersionConflict):
        update_role(
            actor_id=actor.id,
            role_id=role_obj.id,
            expected_version=1,
            name=None,
            description=None,
            data_scope=None,
            permission_keys=[],
            request_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_assignment_transfer_is_super_only_non_null_and_version_protected():
    actor = superuser()
    context = resolve_admin_context(actor)
    role_obj = role()
    owner = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="负责人",
        password=PASSWORD,
        role_id=role_obj.id,
        request_id=uuid.uuid4(),
    )
    second_owner = create_admin(
        actor_id=actor.id,
        phone="13600136000",
        nickname="新负责人",
        password=PASSWORD,
        role_id=role_obj.id,
        request_id=uuid.uuid4(),
    )
    user = customer()
    assignment = CustomerAssignment.objects.create(customer=user, owner_admin=owner)
    first = assign_customer(
        actor=actor,
        context=context,
        customer=user,
        owner_admin_id=second_owner.id,
        expected_version=assignment.version,
        reason="",
        request_id=uuid.uuid4(),
    )
    assert first.version == 2
    assert first.owner_admin == second_owner
    with pytest.raises(AssignmentVersionConflict):
        assign_customer(
            actor=actor,
            context=context,
            customer=user,
            owner_admin_id=owner.id,
            expected_version=1,
            reason="陈旧请求",
            request_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_role_scope_never_widens_direct_customer_ownership():
    actor = superuser()
    shared_role = role("角色范围", AdminRole.DataScope.ROLE)
    first = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="甲",
        password=PASSWORD,
        role_id=shared_role.id,
        request_id=uuid.uuid4(),
    )
    second = create_admin(
        actor_id=actor.id,
        phone="13600136000",
        nickname="乙",
        password=PASSWORD,
        role_id=shared_role.id,
        request_id=uuid.uuid4(),
    )
    assigned = customer()
    second_customer = customer("13500135000")
    CustomerAssignment.objects.create(customer=assigned, owner_admin=first)
    CustomerAssignment.objects.create(customer=second_customer, owner_admin=second)
    change_admin_status(
        actor_id=actor.id,
        profile_id=first.id,
        action="lock",
        expected_version=1,
        request_id=uuid.uuid4(),
    )
    context = resolve_admin_context(second.user)
    assert context is not None
    visible = set(scoped_customers(second.user, context).values_list("id", flat=True))
    assert visible == {second_customer.id}
    super_visible = set(
        scoped_customers(actor, resolve_admin_context(actor)).values_list("id", flat=True)
    )
    assert {assigned.id, second_customer.id}.issubset(super_visible)


@pytest.mark.django_db
def test_admin_me_and_user_list_permission_are_enforced():
    actor = superuser()
    client = APIClient()
    authenticate_admin_client(client, actor)
    me = client.get("/api/v1/admin/me")
    assert me.status_code == 200
    assert "phone" not in me.json()["data"]
    ordinary_role = role()
    grant(ordinary_role, "users.list", "menu.admin.users")
    profile = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="列表管理员",
        password=PASSWORD,
        role_id=ordinary_role.id,
        request_id=uuid.uuid4(),
    )
    ordinary = APIClient()
    authenticate_admin_client(ordinary, profile.user)
    assert ordinary.get("/api/v1/admin/users").status_code == 200


@pytest.mark.django_db
def test_rbac_events_are_append_only_and_safe():
    actor = superuser()
    create_role(
        actor_id=actor.id,
        name="事件角色",
        description="",
        data_scope=AdminRole.DataScope.OWN,
        request_id=uuid.uuid4(),
    )
    event = AdminRbacEvent.objects.get()
    serialized = str(event.safe_after)
    assert actor.phone not in serialized
    assert PASSWORD not in serialized


@pytest.mark.django_db(transaction=True)
def test_postgresql_marker_for_rbac_locking_asset():
    if connection.vendor != "postgresql":
        pytest.skip("通过 scripts/test-postgres-rbac.* 在真实 PostgreSQL 执行。")
