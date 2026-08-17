import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from rest_framework.test import APIClient

from apps.ai.models import APICredential, APICredentialAudit
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "Correct-Horse-Battery-2026!"


def require_postgresql():
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL")


def client():
    user = User.objects.create_superuser(
        phone="13900139000", nickname="PostgreSQL 密钥管理员", password=PASSWORD
    )
    api = APIClient()
    authenticate_admin_client(api, user)
    return api


def create_credential(api):
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)
    response = api.post(
        "/api/v1/admin/api-credentials",
        {
            "provider_key": "deepseek",
            "environment": "staging",
            "api_key": "aaaaaaaaaaaaaaaa",
        },
        format="json",
    )
    assert response.status_code == 201
    return APICredential.objects.get(pk=response.json()["data"]["id"])


def test_postgresql_blocks_credential_delete_and_identity_tampering():
    require_postgresql()
    credential = create_credential(client())

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM api_credentials WHERE id = %s", [credential.id])

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE api_credentials SET secret_mask = %s WHERE id = %s",
                    ["tampered", credential.id],
                )


def test_postgresql_rotation_is_only_supported_state_transition_and_erases_old_ciphertext():
    require_postgresql()
    api = client()
    credential = create_credential(api)
    response = api.post(
        f"/api/v1/admin/api-credentials/{credential.id}/rotate",
        {"expected_version": 1, "api_key": "bbbbbbbbbbbbbbbb"},
        format="json",
    )
    assert response.status_code == 200
    credential.refresh_from_db()
    assert credential.status == "replaced"
    assert credential.secret_reference == ""
    assert credential.replaced_at is not None

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "UPDATE api_credentials "
                        "SET status = 'active', secret_reference = 'x' "
                        "WHERE id = %s"
                    ),
                    [credential.id],
                )


def test_postgresql_api_credential_audit_is_append_only():
    require_postgresql()
    credential = create_credential(client())
    audit = APICredentialAudit.objects.get(
        credential=credential, action=APICredentialAudit.Action.CREATED
    )
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE api_credential_audit SET outcome = 'failure' WHERE id = %s",
                    [audit.id],
                )
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM api_credential_audit WHERE id = %s", [audit.id])
