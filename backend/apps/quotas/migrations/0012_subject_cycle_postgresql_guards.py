from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION quotas_guard_account() RETURNS trigger AS $$
DECLARE
    entry quota_ledger_entries%%ROWTYPE;
    subject_user uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'quota accounts are immutable evidence';
    END IF;
    IF NEW.subject_id IS NOT NULL THEN
        SELECT user_id INTO subject_user FROM subjects WHERE id = NEW.subject_id;
        IF subject_user IS NULL OR subject_user <> NEW.user_id THEN
            RAISE EXCEPTION 'quota subject binding mismatch';
        END IF;
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.available <> 0 OR NEW.frozen <> 0 OR NEW.ledger_sequence <> 0
           OR NEW.last_ledger_entry_id IS NOT NULL OR NEW.version <> 1 THEN
            RAISE EXCEPTION 'quota account must start empty';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        NEW.user_id, NEW.subscription_id, NEW.subject_id,
        NEW.quota_type, NEW.scope, NEW.unit, NEW.batch_key,
        NEW.entitlement_amount, NEW.cycle_started_at, NEW.cycle_ends_at
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.subscription_id, OLD.subject_id,
        OLD.quota_type, OLD.scope, OLD.unit, OLD.batch_key,
        OLD.entitlement_amount, OLD.cycle_started_at, OLD.cycle_ends_at
    ) THEN
        RAISE EXCEPTION 'quota account bindings are immutable';
    END IF;
    IF NEW.updated_at = OLD.updated_at
       AND ROW(
           NEW.available, NEW.frozen, NEW.ledger_sequence,
           NEW.last_ledger_entry_id, NEW.version
       ) IS NOT DISTINCT FROM ROW(
           OLD.available, OLD.frozen, OLD.ledger_sequence,
           OLD.last_ledger_entry_id, OLD.version
       ) THEN
        RETURN NEW;
    END IF;
    IF NEW.ledger_sequence <> OLD.ledger_sequence + 1
       OR NEW.version <> OLD.version + 1
       OR NEW.last_ledger_entry_id IS NULL THEN
        RAISE EXCEPTION 'quota account update must advance one ledger sequence';
    END IF;
    SELECT * INTO entry FROM quota_ledger_entries
     WHERE id = NEW.last_ledger_entry_id;
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

CREATE OR REPLACE FUNCTION quotas_validate_cycle_reset() RETURNS trigger AS $$
DECLARE
    previous_row quota_accounts%%ROWTYPE;
    next_row quota_accounts%%ROWTYPE;
    init_row quota_ledger_entries%%ROWTYPE;
    forfeit_row quota_ledger_entries%%ROWTYPE;
    subscription_row subscriptions%%ROWTYPE;
BEGIN
    SELECT * INTO previous_row FROM quota_accounts
     WHERE id = NEW.previous_account_id;
    SELECT * INTO next_row FROM quota_accounts WHERE id = NEW.next_account_id;
    SELECT * INTO init_row FROM quota_ledger_entries
     WHERE id = NEW.initialize_entry_id;
    SELECT * INTO subscription_row FROM subscriptions
     WHERE id = NEW.subscription_id;
    IF NEW.forfeit_entry_id IS NOT NULL THEN
        SELECT * INTO forfeit_row FROM quota_ledger_entries
         WHERE id = NEW.forfeit_entry_id;
    END IF;
    IF previous_row.id IS NULL OR next_row.id IS NULL OR init_row.id IS NULL
       OR subscription_row.id IS NULL
       OR previous_row.user_id <> next_row.user_id
       OR previous_row.subscription_id <> NEW.subscription_id
       OR next_row.subscription_id <> NEW.subscription_id
       OR previous_row.subject_id IS DISTINCT FROM NEW.subject_id
       OR next_row.subject_id IS DISTINCT FROM NEW.subject_id
       OR previous_row.quota_type <> NEW.quota_type
       OR next_row.quota_type <> NEW.quota_type
       OR previous_row.batch_type <> 'primary'
       OR next_row.batch_type <> 'primary'
       OR previous_row.cycle_ends_at <> NEW.boundary
       OR next_row.cycle_started_at <> NEW.boundary
       OR next_row.cycle_ends_at > subscription_row.ends_at
       OR init_row.account_id <> next_row.id
       OR init_row.action <> 'initialize'
       OR init_row.sequence <> 1 OR init_row.available_before <> 0
       OR init_row.available_delta <> next_row.entitlement_amount THEN
        RAISE EXCEPTION 'QUOTA_CYCLE_RESET_MISMATCH';
    END IF;
    IF NEW.forfeit_entry_id IS NOT NULL AND (
       forfeit_row.id IS NULL
       OR forfeit_row.account_id <> previous_row.id
       OR forfeit_row.action <> 'cycle_forfeit'
       OR forfeit_row.available_after <> 0
       OR forfeit_row.frozen_delta <> 0) THEN
        RAISE EXCEPTION 'QUOTA_CYCLE_FORFEIT_MISMATCH';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

REVERSE_SQL = r"""
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
        NEW.batch_key, NEW.entitlement_amount,
        NEW.cycle_started_at, NEW.cycle_ends_at
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.subscription_id, OLD.quota_type, OLD.scope, OLD.unit,
        OLD.batch_key, OLD.entitlement_amount,
        OLD.cycle_started_at, OLD.cycle_ends_at
    ) THEN
        RAISE EXCEPTION 'quota account bindings are immutable';
    END IF;
    IF NEW.updated_at = OLD.updated_at
       AND ROW(
           NEW.available, NEW.frozen, NEW.ledger_sequence,
           NEW.last_ledger_entry_id, NEW.version
       ) IS NOT DISTINCT FROM ROW(
           OLD.available, OLD.frozen, OLD.ledger_sequence,
           OLD.last_ledger_entry_id, OLD.version
       ) THEN
        RETURN NEW;
    END IF;
    IF NEW.ledger_sequence <> OLD.ledger_sequence + 1
       OR NEW.version <> OLD.version + 1
       OR NEW.last_ledger_entry_id IS NULL THEN
        RAISE EXCEPTION 'quota account update must advance one ledger sequence';
    END IF;
    SELECT * INTO entry FROM quota_ledger_entries
     WHERE id = NEW.last_ledger_entry_id;
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

CREATE OR REPLACE FUNCTION quotas_validate_cycle_reset() RETURNS trigger AS $$
DECLARE
    previous_row quota_accounts%%ROWTYPE;
    next_row quota_accounts%%ROWTYPE;
    init_row quota_ledger_entries%%ROWTYPE;
    forfeit_row quota_ledger_entries%%ROWTYPE;
    subscription_row subscriptions%%ROWTYPE;
BEGIN
    SELECT * INTO previous_row FROM quota_accounts
     WHERE id = NEW.previous_account_id;
    SELECT * INTO next_row FROM quota_accounts WHERE id = NEW.next_account_id;
    SELECT * INTO init_row FROM quota_ledger_entries
     WHERE id = NEW.initialize_entry_id;
    SELECT * INTO subscription_row FROM subscriptions
     WHERE id = NEW.subscription_id;
    IF NEW.forfeit_entry_id IS NOT NULL THEN
        SELECT * INTO forfeit_row FROM quota_ledger_entries
         WHERE id = NEW.forfeit_entry_id;
    END IF;
    IF previous_row.id IS NULL OR next_row.id IS NULL OR init_row.id IS NULL
       OR subscription_row.id IS NULL
       OR previous_row.user_id <> next_row.user_id
       OR previous_row.subscription_id <> NEW.subscription_id
       OR next_row.subscription_id <> NEW.subscription_id
       OR previous_row.quota_type <> NEW.quota_type
       OR next_row.quota_type <> NEW.quota_type
       OR previous_row.batch_type <> 'primary'
       OR next_row.batch_type <> 'primary'
       OR previous_row.cycle_ends_at <> NEW.boundary
       OR next_row.cycle_started_at <> NEW.boundary
       OR next_row.cycle_ends_at > subscription_row.ends_at
       OR init_row.account_id <> next_row.id
       OR init_row.action <> 'initialize'
       OR init_row.sequence <> 1 OR init_row.available_before <> 0
       OR init_row.available_delta <> next_row.entitlement_amount THEN
        RAISE EXCEPTION 'QUOTA_CYCLE_RESET_MISMATCH';
    END IF;
    IF NEW.forfeit_entry_id IS NOT NULL AND (
       forfeit_row.id IS NULL
       OR forfeit_row.account_id <> previous_row.id
       OR forfeit_row.action <> 'cycle_forfeit'
       OR forfeit_row.available_after <> 0
       OR forfeit_row.frozen_delta <> 0) THEN
        RAISE EXCEPTION 'QUOTA_CYCLE_FORFEIT_MISMATCH';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("quotas", "0011_remove_quotaaccount_quota_account_unique_batch_and_more")
    ]
    operations = [migrations.RunPython(install, reverse)]
