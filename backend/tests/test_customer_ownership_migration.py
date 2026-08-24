import importlib

import pytest
from django.apps import apps as django_apps

from apps.admin_rbac.models import AdminProfile, AdminRole, CustomerAssignment
from apps.users.models import Tenant, User

PASSWORD = "Correct-Horse-Battery-2026!"


def make_admin(phone, tenant):
    role = AdminRole.objects.create(name=f"迁移代理-{phone}", data_scope=AdminRole.DataScope.OWN)
    admin = User.objects.create_user(
        phone=phone,
        nickname="迁移代理",
        password=PASSWORD,
        tenant=tenant,
        is_staff=True,
    )
    return AdminProfile.objects.create(user=admin, role=role)


def run_backfill():
    migration = importlib.import_module(
        "apps.admin_rbac.migrations.0022_enforce_admin_customer_ownership"
    )
    migration.backfill_customer_ownership(django_apps, None)


def run_independent_user_backfill():
    migration = importlib.import_module("apps.admin_rbac.migrations.0027_allow_independent_users")
    migration.ensure_assignment_rows(django_apps, None)


@pytest.mark.django_db
def test_ownership_migration_backfills_exactly_one_same_tenant_admin():
    tenant = Tenant.objects.create(key="migration-one", display_name="迁移租户")
    owner = make_admin("13700000101", tenant)
    customer = User.objects.create_user(
        phone="13800000101", nickname="待回填客户", password=PASSWORD, tenant=tenant
    )

    run_backfill()

    assert CustomerAssignment.objects.get(customer=customer).owner_admin == owner


@pytest.mark.django_db
def test_ownership_migration_fails_closed_on_ambiguous_same_tenant_admins():
    tenant = Tenant.objects.create(key="migration-ambiguous", display_name="歧义租户")
    make_admin("13700000111", tenant)
    make_admin("13700000112", tenant)
    customer = User.objects.create_user(
        phone="13800000111", nickname="歧义客户", password=PASSWORD, tenant=tenant
    )

    with pytest.raises(RuntimeError, match="exactly one eligible non-super ADMIN"):
        run_backfill()

    assert not CustomerAssignment.objects.filter(customer=customer).exists()


@pytest.mark.django_db
def test_independent_user_migration_creates_nullable_assignment_boundary():
    customer = User.objects.create_user(phone="13800000121", nickname="独立客户", password=PASSWORD)

    run_independent_user_backfill()

    assignment = CustomerAssignment.objects.get(customer=customer)
    assert assignment.owner_admin is None
