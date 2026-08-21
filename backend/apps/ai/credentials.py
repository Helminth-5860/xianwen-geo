from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.admin_rbac.audit_services import record_audit_event, validate_safe_json

from .contracts import AdapterCredential, AIModelCapability
from .credential_crypto import CredentialCryptoError, decrypt_secret, encrypt_secret, mask_secret
from .exceptions import (
    AICredentialAlreadyExists,
    AICredentialCryptoFailure,
    AICredentialInvalid,
    AICredentialStateConflict,
    AICredentialVersionConflict,
)
from .models import (
    AIProvider,
    APICredential,
    APICredentialAudit,
    APICredentialCapabilityBinding,
)


def _validate_secret(value: str) -> str:
    if not isinstance(value, str) or not (8 <= len(value) <= 4096):
        raise AICredentialInvalid
    if value != value.strip():
        raise AICredentialInvalid
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        raise AICredentialInvalid
    return value


def _summary(credential: APICredential) -> dict[str, object]:
    return {
        "provider_key": credential.provider.provider_key,
        "environment": credential.environment,
        "version_no": credential.version_no,
        "status": credential.status,
        "mask": credential.secret_mask,
    }


def _record(
    request,
    *,
    credential: APICredential,
    action: str,
    outcome: str,
    before: dict[str, object] | None = None,
    stable_error_code: str = "",
    extra: dict[str, object] | None = None,
) -> None:
    safe = _summary(credential)
    if extra:
        safe.update(extra)
    safe = validate_safe_json(safe)
    APICredentialAudit.objects.create(
        credential=credential,
        action=action,
        outcome=outcome,
        actor=request.user,
        safe_summary=safe,
        stable_error_code=stable_error_code,
    )
    record_audit_event(
        request=request,
        category="api_credential",
        action_key=f"api_credential.{action}",
        outcome="executed" if outcome == APICredentialAudit.Outcome.SUCCESS else "failed",
        actor=request.user,
        target_type="api_credential",
        target_id=credential.id,
        safe_before=before or {},
        safe_after=safe,
        stable_error_code=stable_error_code,
    )


def list_active_credentials():
    return (
        APICredential.objects.filter(status=APICredential.Status.ACTIVE)
        .select_related("provider")
        .order_by("provider__provider_key", "environment")
    )


@transaction.atomic
def create_api_credential(*, request, provider_key: str, environment: str, secret: str):
    secret = _validate_secret(secret)
    try:
        provider = AIProvider.objects.select_for_update().get(provider_key=provider_key)
    except AIProvider.DoesNotExist as exc:
        raise AICredentialInvalid from exc
    if APICredential.objects.filter(
        provider=provider, environment=environment, status=APICredential.Status.ACTIVE
    ).exists():
        raise AICredentialAlreadyExists
    version = (
        APICredential.objects.filter(provider=provider, environment=environment).aggregate(
            maximum=Max("version_no")
        )["maximum"]
        or 0
    ) + 1
    try:
        encrypted = encrypt_secret(secret)
    except CredentialCryptoError as exc:
        raise AICredentialCryptoFailure from exc
    credential = APICredential.objects.create(
        provider=provider,
        environment=environment,
        secret_reference=encrypted,
        secret_mask=mask_secret(secret),
        version_no=version,
        status=APICredential.Status.ACTIVE,
        created_by=request.user,
    )
    _record(
        request,
        credential=credential,
        action=APICredentialAudit.Action.CREATED,
        outcome=APICredentialAudit.Outcome.SUCCESS,
    )
    return credential


@transaction.atomic
def rotate_api_credential(
    *, request, credential_id, expected_version: int, secret: str
) -> APICredential:
    secret = _validate_secret(secret)
    try:
        current = (
            APICredential.objects.select_for_update()
            .select_related("provider")
            .get(pk=credential_id)
        )
    except APICredential.DoesNotExist as exc:
        raise AICredentialStateConflict from exc
    if current.status != APICredential.Status.ACTIVE:
        raise AICredentialStateConflict
    if current.version_no != expected_version:
        raise AICredentialVersionConflict
    before = _summary(current)
    try:
        encrypted = encrypt_secret(secret)
    except CredentialCryptoError as exc:
        raise AICredentialCryptoFailure from exc
    now = timezone.now()
    current.status = APICredential.Status.REPLACED
    current.secret_reference = ""
    current.replaced_at = now
    current.replaced_by = request.user
    current.save(update_fields=["status", "secret_reference", "replaced_at", "replaced_by"])
    replacement = APICredential.objects.create(
        provider=current.provider,
        environment=current.environment,
        secret_reference=encrypted,
        secret_mask=mask_secret(secret),
        version_no=current.version_no + 1,
        status=APICredential.Status.ACTIVE,
        created_by=request.user,
    )
    _record(
        request,
        credential=replacement,
        action=APICredentialAudit.Action.ROTATED,
        outcome=APICredentialAudit.Outcome.SUCCESS,
        before=before,
        extra={"replaced_credential_id": str(current.id)},
    )
    return replacement


@dataclass(frozen=True)
class CredentialTestResult:
    credential: APICredential
    storage_valid: bool
    remote_validated: bool
    stable_error_code: str = ""


@transaction.atomic
def test_api_credential(*, request, credential_id, expected_version: int) -> CredentialTestResult:
    try:
        credential = (
            APICredential.objects.select_for_update()
            .select_related("provider")
            .get(pk=credential_id)
        )
    except APICredential.DoesNotExist as exc:
        raise AICredentialStateConflict from exc
    if credential.status != APICredential.Status.ACTIVE:
        raise AICredentialStateConflict
    if credential.version_no != expected_version:
        raise AICredentialVersionConflict
    try:
        raw = decrypt_secret(credential.secret_reference)
        AdapterCredential(raw)
    except (CredentialCryptoError, ValueError):
        code = AICredentialCryptoFailure.code
        _record(
            request,
            credential=credential,
            action=APICredentialAudit.Action.TESTED,
            outcome=APICredentialAudit.Outcome.FAILURE,
            stable_error_code=code,
            extra={"storage_valid": False, "remote_validated": False},
        )
        return CredentialTestResult(
            credential=credential,
            storage_valid=False,
            remote_validated=False,
            stable_error_code=code,
        )
    _record(
        request,
        credential=credential,
        action=APICredentialAudit.Action.TESTED,
        outcome=APICredentialAudit.Outcome.SUCCESS,
        extra={"storage_valid": True, "remote_validated": False},
    )
    return CredentialTestResult(
        credential=credential,
        storage_valid=True,
        remote_validated=False,
    )


class DatabaseCredentialResolver:
    def __init__(self, *, environment: str | None = None):
        self.environment = environment or settings.API_CREDENTIAL_ENVIRONMENT

    def resolve(self, provider_key: str) -> AdapterCredential:
        try:
            credential = APICredential.objects.select_related("provider").get(
                provider__provider_key=provider_key,
                environment=self.environment,
                status=APICredential.Status.ACTIVE,
            )
        except APICredential.DoesNotExist as exc:
            raise AICredentialStateConflict from exc
        try:
            return AdapterCredential(decrypt_secret(credential.secret_reference))
        except (CredentialCryptoError, ValueError) as exc:
            raise AICredentialCryptoFailure from exc


@dataclass(frozen=True)
class CapabilityCredentialSnapshot:
    binding_id: str
    binding_version: int
    credential_id: str
    credential_version: int
    provider_key: str
    capability: str
    environment: str


def capability_credential_snapshot(
    *, provider_key: str, capability: AIModelCapability | str, environment: str | None = None
) -> CapabilityCredentialSnapshot:
    normalized = AIModelCapability(capability).value
    selected_environment = environment or settings.API_CREDENTIAL_ENVIRONMENT
    try:
        binding = APICredentialCapabilityBinding.objects.select_related("provider").get(
            provider__provider_key=provider_key,
            capability=normalized,
            environment=selected_environment,
            enabled=True,
        )
        credential = APICredential.objects.get(
            provider=binding.provider,
            environment=selected_environment,
            status=APICredential.Status.ACTIVE,
        )
    except (
        APICredentialCapabilityBinding.DoesNotExist,
        APICredential.DoesNotExist,
    ) as exc:
        raise AICredentialStateConflict from exc
    return CapabilityCredentialSnapshot(
        binding_id=str(binding.pk),
        binding_version=binding.version,
        credential_id=str(credential.pk),
        credential_version=credential.version_no,
        provider_key=provider_key,
        capability=normalized,
        environment=selected_environment,
    )


class CapabilityDatabaseCredentialResolver:
    def __init__(
        self,
        *,
        capability: AIModelCapability | str,
        environment: str | None = None,
    ) -> None:
        self.capability = AIModelCapability(capability)
        self.environment = environment or settings.API_CREDENTIAL_ENVIRONMENT

    def resolve(self, provider_key: str) -> AdapterCredential:
        snapshot = capability_credential_snapshot(
            provider_key=provider_key,
            capability=self.capability,
            environment=self.environment,
        )
        try:
            credential = APICredential.objects.get(pk=snapshot.credential_id)
            return AdapterCredential(decrypt_secret(credential.secret_reference))
        except (APICredential.DoesNotExist, CredentialCryptoError, ValueError) as exc:
            raise AICredentialCryptoFailure from exc
