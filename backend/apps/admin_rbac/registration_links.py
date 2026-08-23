from uuid import UUID

from django.conf import settings
from django.core import signing

from .models import AdminProfile, AdminRole

REGISTRATION_REF_SALT = "xianwen.admin-registration-channel.v1"
MAX_REGISTRATION_REF_LENGTH = 512


class InvalidRegistrationReference(Exception):
    pass


def issue_registration_ref(profile: AdminProfile) -> str:
    if profile.user.is_superuser or profile.role_id is None:
        raise InvalidRegistrationReference
    signer = signing.TimestampSigner(salt=REGISTRATION_REF_SALT)
    return signer.sign(profile.registration_channel_key.hex)


def resolve_registration_admin(registration_ref: str, *, for_update: bool = False) -> AdminProfile:
    if not registration_ref or len(registration_ref) > MAX_REGISTRATION_REF_LENGTH:
        raise InvalidRegistrationReference
    signer = signing.TimestampSigner(salt=REGISTRATION_REF_SALT)
    try:
        raw_key = signer.unsign(
            registration_ref,
            max_age=settings.REGISTRATION_REF_MAX_AGE_SECONDS,
        )
        channel_key = UUID(raw_key)
    except (ValueError, signing.BadSignature, signing.SignatureExpired) as exc:
        raise InvalidRegistrationReference from exc

    queryset = AdminProfile.objects.select_related("user", "role")
    if for_update:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(
            registration_channel_key=channel_key,
            admin_status=AdminProfile.Status.ACTIVE,
            user__is_active=True,
            user__is_staff=True,
            user__is_superuser=False,
            role__isnull=False,
            role__status=AdminRole.Status.ACTIVE,
        )
    except AdminProfile.DoesNotExist as exc:
        raise InvalidRegistrationReference from exc
