from django.db import migrations

GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION quotas_validate_transfer_ledger() RETURNS trigger AS $$
BEGIN
    IF NEW.action = 'plan_change_transfer_out' THEN
        IF NOT EXISTS (
            SELECT 1 FROM quota_transfers WHERE transfer_out_entry_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'QUOTA_TRANSFER_OUT_LEDGER_UNBOUND';
        END IF;
    ELSIF NEW.action = 'plan_change_transfer_in' THEN
        IF NOT EXISTS (
            SELECT 1 FROM quota_transfers WHERE transfer_in_entry_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'QUOTA_TRANSFER_IN_LEDGER_UNBOUND';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER quotas_transfer_ledger_bound
AFTER INSERT ON quota_ledger_entries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quotas_validate_transfer_ledger();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS quotas_transfer_ledger_bound ON quota_ledger_entries;
DROP FUNCTION IF EXISTS quotas_validate_transfer_ledger();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("quotas", "0005_plan_change_postgresql_guards")]
    operations = [migrations.RunPython(install, reverse)]
