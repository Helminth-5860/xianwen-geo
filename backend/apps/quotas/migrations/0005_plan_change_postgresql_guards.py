from django.db import migrations

GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION quotas_guard_account() RETURNS trigger AS $$
DECLARE entry quota_ledger_entries%%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'QUOTA_ACCOUNT_DELETE_FORBIDDEN'; END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.available <> 0 OR NEW.frozen <> 0 OR NEW.ledger_sequence <> 0
           OR NEW.last_ledger_entry_id IS NOT NULL OR NEW.version <> 1 THEN
            RAISE EXCEPTION 'QUOTA_ACCOUNT_MUST_START_EMPTY';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        NEW.user_id, NEW.subscription_id, NEW.quota_type, NEW.scope, NEW.unit,
        NEW.batch_key, NEW.batch_type, NEW.spendable_until, NEW.source_change_id,
        NEW.entitlement_amount, NEW.cycle_started_at, NEW.cycle_ends_at
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.subscription_id, OLD.quota_type, OLD.scope, OLD.unit,
        OLD.batch_key, OLD.batch_type, OLD.spendable_until, OLD.source_change_id,
        OLD.entitlement_amount, OLD.cycle_started_at, OLD.cycle_ends_at
    ) THEN RAISE EXCEPTION 'QUOTA_ACCOUNT_BINDINGS_IMMUTABLE'; END IF;
    IF NEW.updated_at = OLD.updated_at
       AND ROW(
           NEW.available, NEW.frozen, NEW.ledger_sequence, NEW.last_ledger_entry_id, NEW.version
       )
           IS NOT DISTINCT FROM
           ROW(
               OLD.available, OLD.frozen, OLD.ledger_sequence, OLD.last_ledger_entry_id, OLD.version
           )
    THEN RETURN NEW; END IF;
    IF NEW.available < 0 OR NEW.frozen < 0
       OR NEW.ledger_sequence <> OLD.ledger_sequence + 1
       OR NEW.version <> OLD.version + 1 OR NEW.last_ledger_entry_id IS NULL THEN
        RAISE EXCEPTION 'QUOTA_ACCOUNT_LEDGER_ADVANCE_REQUIRED';
    END IF;
    SELECT * INTO entry FROM quota_ledger_entries WHERE id = NEW.last_ledger_entry_id;
    IF NOT FOUND OR entry.account_id <> OLD.id OR entry.sequence <> NEW.ledger_sequence
       OR entry.available_before <> OLD.available OR entry.frozen_before <> OLD.frozen
       OR entry.available_after <> NEW.available OR entry.frozen_after <> NEW.frozen
       OR entry.account_version_before <> OLD.version
       OR entry.account_version_after <> NEW.version THEN
        RAISE EXCEPTION 'QUOTA_ACCOUNT_LEDGER_MISMATCH';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_guard_hold_group() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'QUOTA_HOLD_GROUP_DELETE_FORBIDDEN'; END IF;
    IF TG_OP = 'INSERT' THEN RETURN NEW; END IF;
    IF ROW(
        NEW.user_id, NEW.quota_type, NEW.business_type, NEW.business_id,
        NEW.requested_amount, NEW.freeze_idempotency_key_version,
        NEW.freeze_idempotency_key_digest, NEW.freeze_idempotency_scope_digest,
        NEW.freeze_request_digest
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.quota_type, OLD.business_type, OLD.business_id,
        OLD.requested_amount, OLD.freeze_idempotency_key_version,
        OLD.freeze_idempotency_key_digest, OLD.freeze_idempotency_scope_digest,
        OLD.freeze_request_digest
    ) THEN RAISE EXCEPTION 'QUOTA_HOLD_GROUP_BINDINGS_IMMUTABLE'; END IF;
    IF OLD.status = 'settled' THEN RAISE EXCEPTION 'QUOTA_HOLD_GROUP_TERMINAL'; END IF;
    IF NEW.version <> OLD.version + 1
       OR NEW.consumed_amount < OLD.consumed_amount
       OR NEW.released_amount < OLD.released_amount THEN
        RAISE EXCEPTION 'QUOTA_HOLD_GROUP_TRANSITION_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_guard_hold() RETURNS trigger AS $$
DECLARE account_row quota_accounts%%ROWTYPE; group_row quota_hold_groups%%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'QUOTA_HOLD_DELETE_FORBIDDEN'; END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT * INTO account_row FROM quota_accounts WHERE id = NEW.account_id;
        SELECT * INTO group_row FROM quota_hold_groups WHERE id = NEW.group_id;
        IF account_row.id IS NULL OR group_row.id IS NULL
           OR NEW.user_id <> account_row.user_id
           OR NEW.subscription_id <> account_row.subscription_id
           OR NEW.quota_type <> account_row.quota_type
           OR NEW.user_id <> group_row.user_id OR NEW.quota_type <> group_row.quota_type
           OR NEW.business_type <> group_row.business_type
           OR NEW.business_id <> group_row.business_id THEN
            RAISE EXCEPTION 'QUOTA_HOLD_BINDING_MISMATCH';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        NEW.group_id, NEW.account_id, NEW.user_id, NEW.subscription_id, NEW.quota_type,
        NEW.business_type, NEW.business_id, NEW.requested_amount,
        NEW.freeze_idempotency_key_version, NEW.freeze_idempotency_key_digest,
        NEW.freeze_idempotency_scope_digest, NEW.freeze_request_digest
    ) IS DISTINCT FROM ROW(
        OLD.group_id, OLD.account_id, OLD.user_id, OLD.subscription_id, OLD.quota_type,
        OLD.business_type, OLD.business_id, OLD.requested_amount,
        OLD.freeze_idempotency_key_version, OLD.freeze_idempotency_key_digest,
        OLD.freeze_idempotency_scope_digest, OLD.freeze_request_digest
    ) THEN RAISE EXCEPTION 'QUOTA_HOLD_BINDINGS_IMMUTABLE'; END IF;
    IF OLD.status = 'settled' THEN RAISE EXCEPTION 'QUOTA_HOLD_TERMINAL'; END IF;
    IF NEW.version <> OLD.version + 1
       OR NEW.consumed_amount < OLD.consumed_amount
       OR NEW.released_amount < OLD.released_amount THEN
        RAISE EXCEPTION 'QUOTA_HOLD_TRANSITION_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_assert_hold_group(p_group_id uuid) RETURNS void AS $$
DECLARE group_row quota_hold_groups%%ROWTYPE; requested_sum bigint;
        consumed_sum bigint; released_sum bigint; expected_status varchar;
BEGIN
    SELECT * INTO group_row FROM quota_hold_groups WHERE id = p_group_id;
    IF NOT FOUND THEN RETURN; END IF;
    SELECT COALESCE(SUM(requested_amount), 0), COALESCE(SUM(consumed_amount), 0),
           COALESCE(SUM(released_amount), 0)
      INTO requested_sum, consumed_sum, released_sum
      FROM quota_holds WHERE group_id = group_row.id;
    expected_status := CASE
        WHEN consumed_sum + released_sum = requested_sum THEN 'settled'
        WHEN consumed_sum + released_sum > 0 THEN 'partially_settled'
        ELSE 'open' END;
    IF requested_sum <> group_row.requested_amount
       OR consumed_sum <> group_row.consumed_amount
       OR released_sum <> group_row.released_amount
       OR expected_status <> group_row.status THEN
        RAISE EXCEPTION 'QUOTA_HOLD_GROUP_AGGREGATE_MISMATCH';
    END IF;
    RETURN;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_validate_hold_group_row() RETURNS trigger AS $$
BEGIN
    PERFORM quotas_assert_hold_group(NEW.id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_validate_hold_allocation() RETURNS trigger AS $$
BEGIN
    PERFORM quotas_assert_hold_group(NEW.group_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_guard_transfer() RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'QUOTA_TRANSFER_IMMUTABLE'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION quotas_validate_transfer() RETURNS trigger AS $$
DECLARE source_row quota_accounts%%ROWTYPE; target_row quota_accounts%%ROWTYPE;
        out_row quota_ledger_entries%%ROWTYPE; in_row quota_ledger_entries%%ROWTYPE;
BEGIN
    SELECT * INTO source_row FROM quota_accounts WHERE id = NEW.source_account_id;
    SELECT * INTO target_row FROM quota_accounts WHERE id = NEW.target_account_id;
    SELECT * INTO out_row FROM quota_ledger_entries WHERE id = NEW.transfer_out_entry_id;
    SELECT * INTO in_row FROM quota_ledger_entries WHERE id = NEW.transfer_in_entry_id;
    IF source_row.id IS NULL OR target_row.id IS NULL
       OR out_row.id IS NULL OR in_row.id IS NULL
       OR source_row.user_id <> target_row.user_id OR source_row.quota_type <> target_row.quota_type
       OR NEW.quota_type <> source_row.quota_type
       OR out_row.account_id <> source_row.id OR in_row.account_id <> target_row.id
       OR out_row.action <> 'plan_change_transfer_out'
       OR in_row.action <> 'plan_change_transfer_in'
       OR out_row.available_delta <> -NEW.amount OR in_row.available_delta <> NEW.amount
       OR out_row.frozen_delta <> 0 OR in_row.frozen_delta <> 0 THEN
        RAISE EXCEPTION 'QUOTA_TRANSFER_PAIR_MISMATCH';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS quotas_account_guard ON quota_accounts;
CREATE TRIGGER quotas_account_guard BEFORE INSERT OR UPDATE OR DELETE ON quota_accounts
FOR EACH ROW EXECUTE FUNCTION quotas_guard_account();
DROP TRIGGER IF EXISTS quotas_hold_guard ON quota_holds;
CREATE TRIGGER quotas_hold_guard BEFORE INSERT OR UPDATE OR DELETE ON quota_holds
FOR EACH ROW EXECUTE FUNCTION quotas_guard_hold();
CREATE TRIGGER quotas_hold_group_guard BEFORE UPDATE OR DELETE ON quota_hold_groups
FOR EACH ROW EXECUTE FUNCTION quotas_guard_hold_group();
CREATE CONSTRAINT TRIGGER quotas_hold_group_matches_group
AFTER INSERT OR UPDATE ON quota_hold_groups DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quotas_validate_hold_group_row();
CREATE CONSTRAINT TRIGGER quotas_hold_group_matches_hold
AFTER INSERT OR UPDATE ON quota_holds DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quotas_validate_hold_allocation();
CREATE TRIGGER quotas_transfer_guard BEFORE UPDATE OR DELETE ON quota_transfers
FOR EACH ROW EXECUTE FUNCTION quotas_guard_transfer();
CREATE CONSTRAINT TRIGGER quotas_transfer_pair
AFTER INSERT ON quota_transfers DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quotas_validate_transfer();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS quotas_transfer_pair ON quota_transfers;
DROP TRIGGER IF EXISTS quotas_transfer_guard ON quota_transfers;
DROP TRIGGER IF EXISTS quotas_hold_group_matches_hold ON quota_holds;
DROP TRIGGER IF EXISTS quotas_hold_group_matches_group ON quota_hold_groups;
DROP TRIGGER IF EXISTS quotas_hold_group_guard ON quota_hold_groups;
DROP FUNCTION IF EXISTS quotas_validate_transfer();
DROP FUNCTION IF EXISTS quotas_guard_transfer();
DROP FUNCTION IF EXISTS quotas_validate_hold_allocation();
DROP FUNCTION IF EXISTS quotas_validate_hold_group_row();
DROP FUNCTION IF EXISTS quotas_assert_hold_group(uuid);
DROP FUNCTION IF EXISTS quotas_guard_hold_group();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("quotas", "0004_quotaholdgroup_quotatransfer_and_more")]
    operations = [migrations.RunPython(install, reverse)]
