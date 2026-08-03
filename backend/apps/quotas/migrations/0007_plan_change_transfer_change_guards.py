from django.db import migrations

GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION quotas_validate_transfer() RETURNS trigger AS $$
DECLARE source_row quota_accounts%%ROWTYPE; target_row quota_accounts%%ROWTYPE;
        out_row quota_ledger_entries%%ROWTYPE; in_row quota_ledger_entries%%ROWTYPE;
        change_row subscription_changes%%ROWTYPE; linked_target_id uuid;
BEGIN
    SELECT * INTO source_row FROM quota_accounts WHERE id = NEW.source_account_id;
    SELECT * INTO target_row FROM quota_accounts WHERE id = NEW.target_account_id;
    SELECT * INTO out_row FROM quota_ledger_entries WHERE id = NEW.transfer_out_entry_id;
    SELECT * INTO in_row FROM quota_ledger_entries WHERE id = NEW.transfer_in_entry_id;
    SELECT * INTO change_row FROM subscription_changes WHERE id = NEW.change_id;
    SELECT id INTO linked_target_id FROM subscriptions WHERE source_change_id = NEW.change_id;
    IF source_row.id IS NULL OR target_row.id IS NULL
       OR out_row.id IS NULL OR in_row.id IS NULL OR change_row.id IS NULL
       OR linked_target_id IS NULL OR change_row.status <> 'executed'
       OR source_row.subscription_id <> change_row.from_subscription_id
       OR target_row.subscription_id <> linked_target_id
       OR source_row.user_id <> change_row.user_id OR target_row.user_id <> change_row.user_id
       OR source_row.quota_type <> target_row.quota_type OR NEW.quota_type <> source_row.quota_type
       OR out_row.account_id <> source_row.id OR in_row.account_id <> target_row.id
       OR out_row.user_id <> change_row.user_id OR in_row.user_id <> change_row.user_id
       OR out_row.subscription_id <> source_row.subscription_id
       OR in_row.subscription_id <> target_row.subscription_id
       OR out_row.quota_type <> NEW.quota_type OR in_row.quota_type <> NEW.quota_type
       OR out_row.business_type <> 'subscription_change'
       OR in_row.business_type <> 'subscription_change'
       OR out_row.business_id <> NEW.change_id OR in_row.business_id <> NEW.change_id
       OR out_row.action <> 'plan_change_transfer_out'
       OR in_row.action <> 'plan_change_transfer_in'
       OR out_row.available_delta <> -NEW.amount OR in_row.available_delta <> NEW.amount
       OR out_row.frozen_delta <> 0 OR in_row.frozen_delta <> 0 THEN
        RAISE EXCEPTION 'QUOTA_TRANSFER_PAIR_MISMATCH';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


REVERSE_SQL = r"""
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
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("quotas", "0006_plan_change_transfer_ledger_guards")]
    operations = [migrations.RunPython(install, reverse)]
