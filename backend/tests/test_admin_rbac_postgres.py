import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connection, connections
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminPermission,
    AdminProfile,
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
    RoleVersionConflict,
    assign_customer,
    change_admin_status,
    create_admin,
    update_role,
)
from apps.users.models import User
from apps.users.sms.providers import MockSmsProvider, get_sms_provider
from apps.users.sms.service import send_verification_code

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def seed_permission_catalog():
    # Transactional tests flush data migrations between cases; restore the immutable catalog.
    call_command("sync_admin_rbac", "--apply", verbosity=0)


@pytest.fixture(autouse=True)
def clear_test_redis():
    if connection.vendor != "postgresql":
        yield
        return
    client = get_redis_connection("default")
    client.flushdb()
    yield
    client.flushdb()


def require_postgresql():
    if connection.vendor != "postgresql":
        pytest.skip("仅通过 scripts/test-postgres-rbac.* 在真实 PostgreSQL 执行。")


def run_parallel(*operations):
    barrier = threading.Barrier(len(operations))

    def run(operation):
        close_old_connections()
        barrier.wait()
        try:
            return operation()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return [future.result() for future in [pool.submit(run, op) for op in operations]]


def make_superuser(phone):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def browser_client():
    client = APIClient(enforce_csrf_checks=True)
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return client, response.json()["data"]["csrf_token"]


def sms_login_with_real_redis(phone):
    provider = get_sms_provider()
    assert isinstance(provider, MockSmsProvider)
    send_verification_code(phone, "login", "127.0.0.1", provider=provider)
    code = provider.outbox[-1].code
    client, csrf = browser_client()
    response = client.post(
        "/api/v1/auth/login/sms",
        {"phone": phone, "sms_code": code},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    return client, response


def test_postgresql_role_version_allows_only_one_concurrent_update():
    require_postgresql()
    actor = make_superuser("13900139000")
    role = AdminRole.objects.create(name="并发角色", data_scope=AdminRole.DataScope.ALL)

    def update(scope):
        try:
            update_role(
                actor_id=actor.id,
                role_id=role.id,
                expected_version=1,
                name=None,
                description=None,
                data_scope=scope,
                permission_keys=[],
                request_id=uuid.uuid4(),
            )
            return "success"
        except RoleVersionConflict:
            return "conflict"

    assert sorted(run_parallel(lambda: update("own"), lambda: update("role"))) == [
        "conflict",
        "success",
    ]


def test_postgresql_last_superuser_concurrency_preserves_one_active():
    require_postgresql()
    first = make_superuser("13900139000")
    second = make_superuser("13700137000")

    def lock(actor, target):
        try:
            change_admin_status(
                actor_id=actor.id,
                profile_id=target.admin_profile.id,
                action="lock",
                expected_version=1,
                request_id=uuid.uuid4(),
            )
            return "success"
        except LastSuperuserProtected:
            return "protected"

    results = run_parallel(lambda: lock(first, second), lambda: lock(second, first))
    assert sorted(results) == ["protected", "success"]
    assert (
        AdminProfile.objects.filter(
            user__is_superuser=True,
            user__is_staff=True,
            admin_status=AdminProfile.Status.ACTIVE,
        ).count()
        == 1
    )


def test_postgresql_first_assignment_version_zero_allows_one_creator():
    require_postgresql()
    actor = make_superuser("13900139000")
    role = AdminRole.objects.create(name="负责人", data_scope=AdminRole.DataScope.ALL)
    owner = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="管理员",
        password=PASSWORD,
        role_id=role.id,
        request_id=uuid.uuid4(),
    )
    customer = User.objects.create_user(phone="13800138000", nickname="客户", password=PASSWORD)

    def assign():
        actor.refresh_from_db()
        try:
            assign_customer(
                actor=actor,
                context=resolve_admin_context(actor),
                customer=customer,
                owner_admin_id=owner.id,
                expected_version=0,
                reason="",
                request_id=uuid.uuid4(),
            )
            return "success"
        except AssignmentVersionConflict:
            return "conflict"

    assert sorted(run_parallel(assign, assign)) == ["conflict", "success"]
    assert CustomerAssignment.objects.get(customer=customer).version == 1


def test_postgresql_lock_with_assignment_is_not_blocked():
    require_postgresql()
    actor = make_superuser("13900139000")
    role = AdminRole.objects.create(name="紧急锁定", data_scope=AdminRole.DataScope.ALL)
    owner = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="管理员",
        password=PASSWORD,
        role_id=role.id,
        request_id=uuid.uuid4(),
    )
    customer = User.objects.create_user(phone="13800138000", nickname="客户", password=PASSWORD)
    CustomerAssignment.objects.create(customer=customer, owner_admin=owner)
    old_client, csrf = browser_client()
    password_login = old_client.post(
        "/api/v1/auth/login/password",
        {"phone": owner.user.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert password_login.status_code == 200

    changed = change_admin_status(
        actor_id=actor.id,
        profile_id=owner.id,
        action="lock",
        expected_version=1,
        request_id=uuid.uuid4(),
    )
    assert changed.admin_status == AdminProfile.Status.LOCKED
    assert changed.customer_assignments.get().customer_id == customer.id
    assert old_client.get("/api/v1/me").status_code == 401

    _, locked_sms = sms_login_with_real_redis(owner.user.phone)
    assert locked_sms.status_code == 403
    assert locked_sms.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"

    get_redis_connection("default").flushdb()
    changed = change_admin_status(
        actor_id=actor.id,
        profile_id=owner.id,
        action="unlock",
        expected_version=2,
        request_id=uuid.uuid4(),
    )
    assert changed.admin_status == AdminProfile.Status.ACTIVE
    new_client, unlocked_sms = sms_login_with_real_redis(owner.user.phone)
    assert unlocked_sms.status_code == 200
    assert new_client.get("/api/v1/me").status_code == 200
    assert old_client.get("/api/v1/me").status_code == 401


def test_postgresql_own_role_all_scopes_and_phone_filter_remain_closed():
    require_postgresql()
    actor = make_superuser("13900139000")
    own_role = AdminRole.objects.create(name="本人范围", data_scope=AdminRole.DataScope.OWN)
    shared_role = AdminRole.objects.create(name="角色范围", data_scope=AdminRole.DataScope.ROLE)
    all_role = AdminRole.objects.create(name="全部范围", data_scope=AdminRole.DataScope.ALL)
    permissions = list(AdminPermission.objects.filter(key__in=("users.list", "users.view")))
    for role in (own_role, shared_role, all_role):
        AdminRolePermission.objects.bulk_create(
            [AdminRolePermission(role=role, permission=permission) for permission in permissions]
        )
    own_admin = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="本人管理员",
        password=PASSWORD,
        role_id=own_role.id,
        request_id=uuid.uuid4(),
    )
    shared_first = create_admin(
        actor_id=actor.id,
        phone="13600136000",
        nickname="角色甲",
        password=PASSWORD,
        role_id=shared_role.id,
        request_id=uuid.uuid4(),
    )
    shared_second = create_admin(
        actor_id=actor.id,
        phone="13500135000",
        nickname="角色乙",
        password=PASSWORD,
        role_id=shared_role.id,
        request_id=uuid.uuid4(),
    )
    all_admin = create_admin(
        actor_id=actor.id,
        phone="13400134000",
        nickname="全部管理员",
        password=PASSWORD,
        role_id=all_role.id,
        request_id=uuid.uuid4(),
    )
    own_customer = User.objects.create_user(
        phone="13800138000", nickname="本人客户", password=PASSWORD
    )
    role_customer = User.objects.create_user(
        phone="13300133000", nickname="角色客户", password=PASSWORD
    )
    unassigned = User.objects.create_user(phone="13200132000", nickname="未分配", password=PASSWORD)
    CustomerAssignment.objects.create(customer=own_customer, owner_admin=own_admin)
    CustomerAssignment.objects.create(customer=role_customer, owner_admin=shared_first)

    own_ids = set(
        scoped_customers(own_admin.user, resolve_admin_context(own_admin.user)).values_list(
            "id", flat=True
        )
    )
    role_ids = set(
        scoped_customers(shared_second.user, resolve_admin_context(shared_second.user)).values_list(
            "id", flat=True
        )
    )
    all_ids = set(
        scoped_customers(all_admin.user, resolve_admin_context(all_admin.user)).values_list(
            "id", flat=True
        )
    )
    assert own_ids == {own_customer.id}
    assert role_ids == {role_customer.id}
    assert {own_customer.id, role_customer.id, unassigned.id}.issubset(all_ids)

    context = resolve_admin_context(own_admin.user)
    assert context is not None and "users.list" in context.permission_keys
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]
    login = client.post(
        "/api/v1/auth/login/password",
        {"phone": own_admin.user.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert login.status_code == 200, login.json()
    filtered = client.get("/api/v1/admin/users", {"phone": role_customer.phone})
    assert filtered.status_code == 200, filtered.json()
    assert filtered.json()["data"]["results"] == []
    assert client.get(f"/api/v1/admin/users/{role_customer.id}").status_code == 404


def test_postgresql_disable_and_lock_race_preserves_emergency_lock():
    require_postgresql()
    actor = make_superuser("13900139000")
    role = AdminRole.objects.create(name="竞态负责人", data_scope=AdminRole.DataScope.ALL)
    owner = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="管理员",
        password=PASSWORD,
        role_id=role.id,
        request_id=uuid.uuid4(),
    )
    customer = User.objects.create_user(phone="13800138000", nickname="客户", password=PASSWORD)
    CustomerAssignment.objects.create(customer=customer, owner_admin=owner)

    def change(action):
        try:
            change_admin_status(
                actor_id=actor.id,
                profile_id=owner.id,
                action=action,
                expected_version=1,
                request_id=uuid.uuid4(),
            )
            return "success"
        except (AdminHasAssignedCustomers, AdminVersionConflict):
            return "conflict"

    assert sorted(run_parallel(lambda: change("disable"), lambda: change("lock"))) == [
        "conflict",
        "success",
    ]
    owner.refresh_from_db()
    assert owner.admin_status == AdminProfile.Status.LOCKED
