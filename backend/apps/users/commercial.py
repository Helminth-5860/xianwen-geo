from enum import StrEnum

from .models import Tenant, User


class CommercialIdentity(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    USER = "USER"


def commercial_identity(user: User) -> CommercialIdentity:
    if user.is_superuser and user.is_staff:
        return CommercialIdentity.SUPER_ADMIN
    if user.is_staff:
        return CommercialIdentity.ADMIN
    return CommercialIdentity.USER


def commercial_home_route(user: User) -> str:
    identity = commercial_identity(user)
    if identity in {
        CommercialIdentity.SUPER_ADMIN,
        CommercialIdentity.ADMIN,
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
