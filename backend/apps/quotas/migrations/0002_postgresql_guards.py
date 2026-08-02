from django.db import migrations


GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION quotas_guard_account() RETURNS trigger AS $$
DECLARE
    entry quota_ledger_entries%%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'quota accounts are immutable evidence';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.available <> 0 OR NEW.frozen <> 0 OR NEW.ledger_sequence <> 0
           OR NEW.last_ledger_entry_id IS NOT NULL OR NEW.version <> 1 THEN
            RAISE EXCEPTION 'quota account must start empty';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        NEW.user_id, NEW.subscription_id, NEW.quota_type, NEW.scope, NEW.unit,
        NEW.batch_key, NEW.entitlement_amount, NEW.cycle_started_at, NEW.cycle_ends_at
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.subscription_id, OLD.quota_type, OLD.scope, OLD.unit,
        OLD.batch_key, OLD.entitlement_amount, OLD.cycle_started_at, OLD.cycle_ends_at
    ) THEN
        RAISE EXCEPTION 'quota account bindings are immutable';
    END IF;
    IF NEW.updated_at = OLD.updated_at
       AND ROW(NEW.available, NEW.frozen, NEW.ledger_sequence, NEW.last_ledger_entry_id, NEW.version)
           IS NOT DISTINCT FROM
           ROW(OLD.available, OLD.frozen, OLD.ledger_sequence, OLD.last_ledger_entry_id, OLD.version) THEN
        RETURN NEW;
    END IF;
    IF NEW.ledger_sequence <> OLD.ledger_sequence + 1 OR NEW.version <> OLD.version + 1
       OR NEW.last_ledger_entry_id IS NULL THEN
        RAISE EXCEPTION 'quota account update must advance one ledger sequence';
    END IF;
    SELECT * INTO entry FROM quota_ledger_entries WHERE id = NEW.last_ledger_entry_id;
    IF NOT FOUND OR entry.account_id <> OLD.id
       OR entry.sequence <> NEW.ledger_sequence
       OR entry.available_before <> OLD.available
       OR entry.frozen_before <> OLD.frozen
       OR entry.available_after <> NEW.available
       OR entry.frozen_after <> NEW.frozen
       OR entry.account_version_before <> OLD.version
       OR entry.account_version_after <> NEW.version THEN
        RAISE EXCEPTION 'quota account update does not match ledger entry';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_guard_ledger() RETURNS trigger AS $$
DECLARE
    account_row quota_accounts%%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'quota ledger is append only';
    END IF;
    SELECT * INTO account_row FROM quota_accounts WHERE id = NEW.account_id FOR UPDATE;
    IF NOT FOUND
       OR NEW.user_id <> account_row.user_id
       OR NEW.subscription_id <> account_row.subscription_id
       OR NEW.quota_type <> account_row.quota_type
       OR NEW.sequence <> account_row.ledger_sequence + 1
       OR NEW.available_before <> account_row.available
       OR NEW.frozen_before <> account_row.frozen
       OR NEW.account_version_before <> account_row.version
       OR NEW.account_version_after <> account_row.version + 1 THEN
        RAISE EXCEPTION 'quota ledger does not extend account state';
    END IF;
    IF NEW.hold_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM quota_holds h
        WHERE h.id = NEW.hold_id
          AND h.account_id = NEW.account_id
          AND h.user_id = NEW.user_id
          AND h.subscription_id = NEW.subscription_id
          AND h.quota_type = NEW.quota_type
    ) THEN
        RAISE EXCEPTION 'quota ledger hold binding mismatch';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_guard_ledger_applied() RETURNS trigger AS $$
DECLARE
    account_row quota_accounts%%ROWTYPE;
    last_sequence bigint;
BEGIN
    SELECT * INTO account_row FROM quota_accounts WHERE id = NEW.account_id;
    SELECT sequence INTO last_sequence FROM quota_ledger_entries
      WHERE id = account_row.last_ledger_entry_id;
    IF account_row.ledger_sequence < NEW.sequence
       OR last_sequence IS DISTINCT FROM account_row.ledger_sequence THEN
        RAISE EXCEPTION 'quota ledger entry was not applied to account';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_guard_hold() RETURNS trigger AS $$
DECLARE
    account_row quota_accounts%%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'quota holds are immutable evidence';
    END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT * INTO account_row FROM quota_accounts WHERE id = NEW.account_id;
        IF NOT FOUND OR NEW.user_id <> account_row.user_id
           OR NEW.subscription_id <> account_row.subscription_id
           OR NEW.quota_type <> account_row.quota_type THEN
            RAISE EXCEPTION 'quota hold binding mismatch';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        NEW.account_id, NEW.user_id, NEW.subscription_id, NEW.quota_type,
        NEW.business_type, NEW.business_id, NEW.requested_amount,
        NEW.freeze_idempotency_key_version, NEW.freeze_idempotency_key_digest,
        NEW.freeze_idempotency_scope_digest, NEW.freeze_request_digest
    ) IS DISTINCT FROM ROW(
        OLD.account_id, OLD.user_id, OLD.subscription_id, OLD.quota_type,
        OLD.business_type, OLD.business_id, OLD.requested_amount,
        OLD.freeze_idempotency_key_version, OLD.freeze_idempotency_key_digest,
        OLD.freeze_idempotency_scope_digest, OLD.freeze_request_digest
    ) THEN
        RAISE EXCEPTION 'quota hold bindings are immutable';
    END IF;
    IF OLD.status = 'settled' THEN
        RAISE EXCEPTION 'settled quota hold is terminal';
    END IF;
    IF NEW.version <> OLD.version + 1
       OR NEW.consumed_amount < OLD.consumed_amount
       OR NEW.released_amount < OLD.released_amount THEN
        RAISE EXCEPTION 'invalid quota hold transition';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS quotas_account_guard ON quota_accounts;
CREATE TRIGGER quotas_account_guard
BEFORE INSERT OR UPDATE OR DELETE ON quota_accounts
FOR EACH ROW EXECUTE FUNCTION quotas_guard_account();

DROP TRIGGER IF EXISTS quotas_ledger_guard ON quota_ledger_entries;
CREATE TRIGGER quotas_ledger_guard
BEFORE INSERT OR UPDATE OR DELETE ON quota_ledger_entries
FOR EACH ROW EXECUTE FUNCTION quotas_guard_ledger();

DROP TRIGGER IF EXISTS quotas_ledger_applied ON quota_ledger_entries;
CREATE CONSTRAINT TRIGGER quotas_ledger_applied
AFTER INSERT ON quota_ledger_entries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quotas_guard_ledger_applied();

DROP TRIGGER IF EXISTS quotas_hold_guard ON quota_holds;
CREATE TRIGGER quotas_hold_guard
BEFORE INSERT OR UPDATE OR DELETE ON quota_holds
FOR EACH ROW EXECUTE FUNCTION quotas_guard_hold();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS quotas_hold_guard ON quota_holds;
DROP TRIGGER IF EXISTS quotas_ledger_applied ON quota_ledger_entries;
DROP TRIGGER IF EXISTS quotas_ledger_guard ON quota_ledger_entries;
DROP TRIGGER IF EXISTS quotas_account_guard ON quota_accounts;
DROP FUNCTION IF EXISTS quotas_guard_hold();
DROP FUNCTION IF EXISTS quotas_guard_ledger_applied();
DROP FUNCTION IF EXISTS quotas_guard_ledger();
DROP FUNCTION IF EXISTS quotas_guard_account();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARD_SQL)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("quotas", "0001_initial")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
