from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION xw_ai_credential_guard() RETURNS trigger AS $$
DECLARE
    expected_version integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'API credential history cannot be deleted';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'active' OR NEW.secret_reference = '' OR NEW.replaced_at IS NOT NULL THEN
            RAISE EXCEPTION 'new API credential must be active with encrypted secret';
        END IF;
        SELECT COALESCE(MAX(version_no), 0) + 1 INTO expected_version
          FROM api_credentials
         WHERE provider_id = NEW.provider_id
           AND environment = NEW.environment;
        IF NEW.version_no <> expected_version THEN
            RAISE EXCEPTION 'API credential version must advance by exactly one';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.provider_id IS DISTINCT FROM OLD.provider_id
       OR NEW.environment IS DISTINCT FROM OLD.environment
       OR NEW.version_no IS DISTINCT FROM OLD.version_no
       OR NEW.secret_mask IS DISTINCT FROM OLD.secret_mask
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'API credential identity/history fields are immutable';
    END IF;

    IF OLD.status = 'active' AND NEW.status = 'replaced' THEN
        IF NEW.secret_reference <> ''
           OR NEW.replaced_at IS NULL
           OR NEW.replaced_by_id IS NULL THEN
            RAISE EXCEPTION 'replaced credential must erase ciphertext and record replacement';
        END IF;
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'unsupported API credential state transition';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ai_credential_guard
BEFORE INSERT OR UPDATE OR DELETE ON api_credentials
FOR EACH ROW EXECUTE FUNCTION xw_ai_credential_guard();

CREATE OR REPLACE FUNCTION xw_ai_credential_audit_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'API credential audit is append-only';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ai_credential_audit_guard
BEFORE UPDATE OR DELETE ON api_credential_audit
FOR EACH ROW EXECUTE FUNCTION xw_ai_credential_audit_guard();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS ai_credential_audit_guard ON api_credential_audit;
DROP FUNCTION IF EXISTS xw_ai_credential_audit_guard();
DROP TRIGGER IF EXISTS ai_credential_guard ON api_credentials;
DROP FUNCTION IF EXISTS xw_ai_credential_guard();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def reverse_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("ai", "0003_api_credentials")]
    operations = [migrations.RunPython(install_guards, reverse_guards)]
