import json
import uuid

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminPermission, AdminRole, AdminRolePermission, AuditEvent
from apps.admin_rbac.services import create_admin
from apps.ai.credential_crypto import decrypt_secret
from apps.ai.credentials import DatabaseCredentialResolver
from apps.ai.models import APICredential, APICredentialAudit
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"
FIRST_KEY = "aaaaaaaaaaaaaaaa"
SECOND_KEY = "bbbbbbbbbbbbbbbb"


@pytest.fixture(autouse=True)
def synchronize_catalogs():
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)


def superuser(phone="13900139000"):
    return User.objects.create_superuser(phone=phone, nickname="密钥管理员", password=PASSWORD)


def super_client(*, csrf=False):
    client = APIClient(enforce_csrf_checks=csrf)
    return authenticate_admin_client(client, superuser())


def data(response):
    return response.json()["data"]


def create_deepseek(client, key=FIRST_KEY, environment="staging"):
    return client.post(
        "/api/v1/admin/api-credentials",
        {
            "provider_key": "deepseek",
            "environment": environment,
            "api_key": key,
        },
        format="json",
    )


@pytest.mark.django_db
def test_create_list_mask_encrypt_and_audit_without_plaintext():
    client = super_client()
    created = create_deepseek(client)
    assert created.status_code == 201
    row = data(created)
    assert row["provider_key"] == "deepseek"
    assert row["environment"] == "staging"
    assert row["version_no"] == 1
    assert row["status"] == "active"
    assert row["secret_mask"] == "********aaaa"
    assert FIRST_KEY not in created.content.decode()
    assert created["Cache-Control"] == "no-store"

    credential = APICredential.objects.get(pk=row["id"])
    assert FIRST_KEY not in credential.secret_reference
    assert decrypt_secret(credential.secret_reference) == FIRST_KEY

    listed = client.get("/api/v1/admin/api-credentials")
    assert listed.status_code == 200
    serialized = listed.content.decode()
    assert FIRST_KEY not in serialized
    assert "secret_reference" not in serialized
    assert "api_key" not in serialized

    specific = APICredentialAudit.objects.get(
        credential=credential, action=APICredentialAudit.Action.CREATED
    )
    global_event = AuditEvent.objects.get(
        category="api_credential", action_key="api_credential.created"
    )
    rendered = json.dumps(
        {
            "specific": specific.safe_summary,
            "global_before": global_event.safe_before,
            "global_after": global_event.safe_after,
        }
    )
    assert FIRST_KEY not in rendered
    assert credential.secret_reference not in rendered


@pytest.mark.django_db
def test_duplicate_requires_rotation_and_rotation_erases_old_ciphertext():
    client = super_client()
    first = create_deepseek(client)
    assert first.status_code == 201
    duplicate = create_deepseek(client, SECOND_KEY)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "AI_CREDENTIAL_ALREADY_EXISTS"

    first_row = data(first)
    rotated = client.post(
        f"/api/v1/admin/api-credentials/{first_row['id']}/rotate",
        {"expected_version": 1, "api_key": SECOND_KEY},
        format="json",
    )
    assert rotated.status_code == 200
    second_row = data(rotated)
    assert second_row["version_no"] == 2
    assert second_row["secret_mask"] == "********bbbb"

    old = APICredential.objects.get(pk=first_row["id"])
    new = APICredential.objects.get(pk=second_row["id"])
    assert old.status == APICredential.Status.REPLACED
    assert old.secret_reference == ""
    assert old.replaced_at is not None
    assert new.status == APICredential.Status.ACTIVE
    assert decrypt_secret(new.secret_reference) == SECOND_KEY
    assert (
        APICredential.objects.filter(
            provider=new.provider,
            environment="staging",
            status=APICredential.Status.ACTIVE,
        ).count()
        == 1
    )

    stale = client.post(
        f"/api/v1/admin/api-credentials/{second_row['id']}/rotate",
        {"expected_version": 1, "api_key": FIRST_KEY},
        format="json",
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "AI_CREDENTIAL_VERSION_CONFLICT"


@pytest.mark.django_db
def test_storage_test_is_explicitly_not_remote_provider_validation():
    client = super_client()
    row = data(create_deepseek(client))
    checked = client.post(
        f"/api/v1/admin/api-credentials/{row['id']}/test",
        {"expected_version": row["version_no"]},
        format="json",
    )
    assert checked.status_code == 200
    result = data(checked)
    assert result["storage_valid"] is True
    assert result["remote_validated"] is False
    assert FIRST_KEY not in checked.content.decode()

    event = APICredentialAudit.objects.get(action=APICredentialAudit.Action.TESTED)
    assert event.safe_summary["remote_validated"] is False
    assert FIRST_KEY not in str(event.safe_summary)


@pytest.mark.django_db
def test_resolver_decrypts_active_credential_without_repr_leak():
    client = super_client()
    create_deepseek(client)
    credential = DatabaseCredentialResolver(environment="staging").resolve("deepseek")
    assert credential.value == FIRST_KEY
    assert FIRST_KEY not in repr(credential)


@pytest.mark.django_db
def test_crypto_failure_is_safe_and_audited(settings):
    client = super_client()
    row = data(create_deepseek(client))
    settings.FIELD_ENCRYPTION_MASTER_KEY = Fernet.generate_key().decode("ascii")
    checked = client.post(
        f"/api/v1/admin/api-credentials/{row['id']}/test",
        {"expected_version": 1},
        format="json",
    )
    assert checked.status_code == 503
    assert checked.json()["error"]["code"] == "AI_CREDENTIAL_CRYPTO_FAILURE"
    assert FIRST_KEY not in checked.content.decode()
    audit = APICredentialAudit.objects.get(action=APICredentialAudit.Action.TESTED)
    assert audit.outcome == APICredentialAudit.Outcome.FAILURE
    assert audit.stable_error_code == "AI_CREDENTIAL_CRYPTO_FAILURE"


@pytest.mark.django_db
def test_only_superuser_admin_can_manage_credentials():
    actor = superuser()
    role = AdminRole.objects.create(name="模型管理员", data_scope=AdminRole.DataScope.ALL)
    model_permission = AdminPermission.objects.get(key="models.manage")
    secret_permission = AdminPermission.objects.get(key="api_credentials.manage")
    AdminRolePermission.objects.create(role=role, permission=model_permission)
    AdminRolePermission.objects.create(role=role, permission=secret_permission)
    profile = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="普通管理员",
        password=PASSWORD,
        role_id=role.id,
        request_id=uuid.uuid4(),
    )
    client = APIClient()
    authenticate_admin_client(client, profile.user)
    assert client.get("/api/v1/admin/api-credentials").status_code == 403
    assert create_deepseek(client).status_code == 403


@pytest.mark.django_db
def test_credential_reads_are_low_risk_but_writes_require_step_up():
    client = APIClient()
    authenticate_admin_client(client, superuser(), step_up=False)

    assert client.get("/api/v1/admin/api-credentials").status_code == 200
    denied = create_deepseek(client)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ADMIN_STEP_UP_REQUIRED"
    assert APICredential.objects.count() == 0


@pytest.mark.django_db
def test_write_requires_real_csrf():
    client = super_client(csrf=True)
    blocked = create_deepseek(client)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"provider_key": "unknown", "environment": "staging", "api_key": FIRST_KEY},
        {"provider_key": "deepseek", "environment": "local", "api_key": FIRST_KEY},
        {"provider_key": "deepseek", "environment": "staging", "api_key": "short"},
        {"provider_key": "deepseek", "environment": "staging", "api_key": " aaaaaaaa"},
        {"provider_key": "deepseek", "environment": "staging", "api_key": "aaaaaaaa\n"},
        {
            "provider_key": "deepseek",
            "environment": "staging",
            "api_key": FIRST_KEY,
            "extra": True,
        },
    ],
)
def test_credential_inputs_are_strict_and_opaque(payload):
    response = super_client().post("/api/v1/admin/api-credentials", payload, format="json")
    assert response.status_code == 422


@pytest.mark.django_db
def test_permission_catalog_marks_secret_management_superuser_only():
    permission = AdminPermission.objects.get(key="api_credentials.manage")
    assert permission.superuser_only is True
