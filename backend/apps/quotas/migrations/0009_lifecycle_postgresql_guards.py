from django.db import migrations


GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION quotas_guard_lifecycle_fact() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'QUOTA_LIFECYCLE_FACT_IMMUTABLE';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_validate_cycle_reset() RETURNS trigger AS $$
DECLARE previous_row quota_accounts%%ROWTYPE; next_row quota_accounts%%ROWTYPE;
        init_row quota_ledger_entries%%ROWTYPE; forfeit_row quota_ledger_entries%%ROWTYPE;
        subscription_row subscriptions%%ROWTYPE;
BEGIN
    SELECT * INTO previous_row FROM quota_accounts WHERE id = NEW.previous_account_id;
    SELECT * INTO next_row FROM quota_accounts WHERE id = NEW.next_account_id;
    SELECT * INTO init_row FROM quota_ledger_entries WHERE id = NEW.initialize_entry_id;
    SELECT * INTO subscription_row FROM subscriptions WHERE id = NEW.subscription_id;
    IF NEW.forfeit_entry_id IS NOT NULL THEN
        SELECT * INTO forfeit_row FROM quota_ledger_entries WHERE id = NEW.forfeit_entry_id;
    END IF;
    IF previous_row.id IS NULL OR next_row.id IS NULL OR init_row.id IS NULL
       OR subscription_row.id IS NULL
       OR previous_row.user_id <> next_row.user_id
       OR previous_row.subscription_id <> NEW.subscription_id
       OR next_row.subscription_id <> NEW.subscription_id
       OR previous_row.quota_type <> NEW.quota_type OR next_row.quota_type <> NEW.quota_type
       OR previous_row.batch_type <> 'primary' OR next_row.batch_type <> 'primary'
       OR previous_row.cycle_ends_at <> NEW.boundary
       OR next_row.cycle_started_at <> NEW.boundary
       OR next_row.cycle_ends_at > subscription_row.ends_at
       OR init_row.account_id <> next_row.id OR init_row.action <> 'initialize'
       OR init_row.sequence <> 1 OR init_row.available_before <> 0
       OR init_row.available_delta <> next_row.entitlement_amount THEN
        RAISE EXCEPTION 'QUOTA_CYCLE_RESET_MISMATCH';
    END IF;
    IF NEW.forfeit_entry_id IS NOT NULL AND (
       forfeit_row.id IS NULL OR forfeit_row.account_id <> previous_row.id
       OR forfeit_row.action <> 'cycle_forfeit' OR forfeit_row.available_after <> 0
       OR forfeit_row.frozen_delta <> 0) THEN
        RAISE EXCEPTION 'QUOTA_CYCLE_FORFEIT_MISMATCH';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_validate_expiry_disposition() RETURNS trigger AS $$
DECLARE account_row quota_accounts%%ROWTYPE; ledger_row quota_ledger_entries%%ROWTYPE;
        change_row subscription_changes%%ROWTYPE;
BEGIN
    SELECT * INTO account_row FROM quota_accounts WHERE id = NEW.account_id;
    IF account_row.id IS NULL OR account_row.subscription_id <> NEW.subscription_id THEN
        RAISE EXCEPTION 'QUOTA_EXPIRY_ACCOUNT_MISMATCH';
    END IF;
    IF NEW.ledger_entry_id IS NOT NULL THEN
        SELECT * INTO ledger_row FROM quota_ledger_entries WHERE id = NEW.ledger_entry_id;
        IF ledger_row.id IS NULL OR ledger_row.account_id <> NEW.account_id
           OR ledger_row.action <> 'expiry_forfeit' OR ledger_row.available_after <> 0
           OR ledger_row.frozen_delta <> 0 THEN
            RAISE EXCEPTION 'QUOTA_EXPIRY_LEDGER_MISMATCH';
        END IF;
    END IF;
    IF NEW.policy = 'retain' AND NEW.renewal_change_id IS NOT NULL THEN
        SELECT * INTO change_row FROM subscription_changes WHERE id = NEW.renewal_change_id;
        IF change_row.id IS NULL OR change_row.from_subscription_id <> NEW.subscription_id
           OR change_row.change_type <> 'renewal' OR change_row.status <> 'executed' THEN
            RAISE EXCEPTION 'QUOTA_EXPIRY_RENEWAL_MISMATCH';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER quota_cycle_reset_append_only
BEFORE UPDATE OR DELETE ON quota_cycle_resets
FOR EACH ROW EXECUTE FUNCTION quotas_guard_lifecycle_fact();
CREATE TRIGGER quota_expiry_disposition_append_only
BEFORE UPDATE OR DELETE ON quota_expiry_dispositions
FOR EACH ROW EXECUTE FUNCTION quotas_guard_lifecycle_fact();
CREATE CONSTRAINT TRIGGER quota_cycle_reset_consistency
AFTER INSERT ON quota_cycle_resets DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quotas_validate_cycle_reset();
CREATE CONSTRAINT TRIGGER quota_expiry_disposition_consistency
AFTER INSERT ON quota_expiry_dispositions DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quotas_validate_expiry_disposition();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS quota_expiry_disposition_consistency ON quota_expiry_dispositions;
DROP TRIGGER IF EXISTS quota_cycle_reset_consistency ON quota_cycle_resets;
DROP TRIGGER IF EXISTS quota_expiry_disposition_append_only ON quota_expiry_dispositions;
DROP TRIGGER IF EXISTS quota_cycle_reset_append_only ON quota_cycle_resets;
DROP FUNCTION IF EXISTS quotas_validate_expiry_disposition();
DROP FUNCTION IF EXISTS quotas_validate_cycle_reset();
DROP FUNCTION IF EXISTS quotas_guard_lifecycle_fact();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("quotas", "0008_quotacyclereset_quotaexpirydisposition_and_more")]
    operations = [migrations.RunPython(install, reverse)]
