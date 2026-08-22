from enum import StrEnum

from .models import Tenant, User


class CommercialIdentity(StrEnum):
    PLATFORM_SUPER_ADMIN = "PLATFORM_SUPER_ADMIN"
    TENANT_ADMIN = "TENANT_ADMIN"
    END_USER = "END_USER"


def commercial_identity(user: User) -> CommercialIdentity:
    if user.is_superuser and user.is_staff:
        return CommercialIdentity.PLATFORM_SUPER_ADMIN
    # Null tenant is retained only as a transitional state for pre-migration/test
    # records. The data migration assigns every real non-superuser admin.
    if user.is_staff:
        return CommercialIdentity.TENANT_ADMIN
    return CommercialIdentity.END_USER


def commercial_home_route(user: User) -> str:
    identity = commercial_identity(user)
    if identity in {
        CommercialIdentity.PLATFORM_SUPER_ADMIN,
        CommercialIdentity.TENANT_ADMIN,
    }:
        return "/admin"
    return "/workspace"


def tenant_branding(tenant: Tenant | None) -> dict[str, str] | None:
    if tenant is None:
        return None
    return {
        "id": str(tenant.id),
        "key": tenant.key,
        "display_name": tenant.display_name,
        "brand_name": tenant.brand_name or tenant.display_name,
        "logo_reference": tenant.logo_reference,
    }
