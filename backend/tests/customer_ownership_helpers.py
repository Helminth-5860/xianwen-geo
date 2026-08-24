from apps.admin_rbac.models import AdminProfile, AdminRole, CustomerAssignment
from apps.users.models import User
from apps.users.phone_numbers import normalize_phone

TEST_ADMIN_PASSWORD = "Test-Admin-Ownership-2026!"


def create_test_admin(*, tenant=None, phone="18899999999") -> AdminProfile:
    existing = AdminProfile.objects.filter(user__phone=normalize_phone(phone)).first()
    if existing is not None:
        return existing
    role, _ = AdminRole.objects.get_or_create(
        name=f"test-owner-{phone}",
        defaults={"data_scope": AdminRole.DataScope.OWN},
    )
    admin = User.objects.create_user(
        phone=phone,
        nickname="测试代理",
        password=TEST_ADMIN_PASSWORD,
        tenant=tenant,
        is_staff=True,
    )
    return AdminProfile.objects.create(user=admin, role=role)


def assign_test_customer(customer: User, *, owner=None) -> CustomerAssignment:
    owner = owner or create_test_admin(tenant=customer.tenant)
    return CustomerAssignment.objects.create(customer=customer, owner_admin=owner)
