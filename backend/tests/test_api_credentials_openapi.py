from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "openapi" / "openapi-v1.yaml").read_text(encoding="utf-8"))


def test_api_credential_paths_and_superadmin_security_contract_are_documented():
    paths = SPEC["paths"]
    assert set(paths["/admin/api-credentials"]) == {"get", "post"}
    assert set(paths["/admin/api-credentials/{credentialId}/rotate"]) == {"post"}
    assert set(paths["/admin/api-credentials/{credentialId}/test"]) == {"post"}
    for path in (
        "/admin/api-credentials",
        "/admin/api-credentials/{credentialId}/rotate",
        "/admin/api-credentials/{credentialId}/test",
    ):
        for operation in paths[path].values():
            assert "403" in operation["responses"]


def test_api_credential_schemas_never_expose_ciphertext_and_mark_plaintext_write_only():
    schemas = SPEC["components"]["schemas"]
    credential = schemas["APICredential"]
    serialized = str(credential).lower()
    assert "secret_reference" not in serialized
    assert "cipher" not in serialized
    assert "api_key" not in credential["properties"]
    assert credential["properties"]["secret_mask"]["readOnly"] is True
    assert schemas["APICredentialCreateRequest"]["properties"]["api_key"]["writeOnly"] is True
    assert schemas["APICredentialRotateRequest"]["properties"]["api_key"]["writeOnly"] is True
    assert schemas["APICredentialTestResult"]["properties"]["remote_validated"]["const"] is False


def test_xw0403_test_endpoint_is_documented_as_local_storage_check_not_provider_call():
    operation = SPEC["paths"]["/admin/api-credentials/{credentialId}/test"]["post"]
    assert "不执行真实 Provider 网络验证" in operation["summary"]
