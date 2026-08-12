from django.db import migrations


GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION documents_guard_upload_intent() RETURNS trigger AS $$
DECLARE
    v_subject_user uuid;
    v_group record;
    v_version record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'FILE_UPLOAD_INTENT_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT user_id INTO v_subject_user FROM subjects WHERE id = NEW.subject_id;
        SELECT user_id, quota_type, business_type, business_id, requested_amount
          INTO v_group FROM quota_hold_groups WHERE id = NEW.quota_hold_group_id;
        IF NOT FOUND OR v_subject_user IS DISTINCT FROM NEW.user_id
           OR v_group.user_id IS DISTINCT FROM NEW.user_id
           OR v_group.quota_type <> 'storage_bytes'
           OR v_group.business_type <> 'file_upload'
           OR v_group.business_id IS DISTINCT FROM NEW.id
           OR v_group.requested_amount IS DISTINCT FROM NEW.declared_size THEN
            RAISE EXCEPTION 'FILE_UPLOAD_INTENT_OWNERSHIP_INVALID';
        END IF;
        IF NEW.purpose <> 'subject_library'
           OR NEW.status <> 'pending_upload'
           OR NEW.version <> 1
           OR NEW.completed_version_id IS NOT NULL
           OR NEW.staging_key !~ '^staging/[0-9a-f]{32}$'
           OR NEW.final_key !~ ('^objects/' || replace(NEW.id::text, '-', '') || '/[0-9a-f]{32}$') THEN
            RAISE EXCEPTION 'FILE_UPLOAD_INTENT_INITIAL_STATE_INVALID';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        NEW.user_id, NEW.subject_id, NEW.purpose,
        NEW.declared_filename, NEW.declared_content_type, NEW.declared_size,
        NEW.declared_file_kind, NEW.staging_key, NEW.final_key,
        NEW.quota_hold_group_id, NEW.idempotency_key_version,
        NEW.idempotency_key_digest, NEW.request_digest, NEW.expires_at, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.subject_id, OLD.purpose,
        OLD.declared_filename, OLD.declared_content_type, OLD.declared_size,
        OLD.declared_file_kind, OLD.staging_key, OLD.final_key,
        OLD.quota_hold_group_id, OLD.idempotency_key_version,
        OLD.idempotency_key_digest, OLD.request_digest, OLD.expires_at, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'FILE_UPLOAD_INTENT_BINDING_IMMUTABLE';
    END IF;
    IF OLD.status IN ('completed', 'rejected', 'expired') THEN
        IF NEW.status <> OLD.status
           OR NEW.completed_version_id IS DISTINCT FROM OLD.completed_version_id
           OR NEW.verification_generation IS DISTINCT FROM OLD.verification_generation
           OR NEW.stable_error_code IS DISTINCT FROM OLD.stable_error_code THEN
            RAISE EXCEPTION 'FILE_UPLOAD_INTENT_TERMINAL';
        END IF;
    ELSIF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'pending_upload' AND NEW.status IN ('verifying', 'expired'))
        OR (OLD.status = 'verifying' AND NEW.status IN ('completed', 'rejected'))
    ) THEN
        RAISE EXCEPTION 'FILE_UPLOAD_INTENT_STATE_INVALID';
    END IF;
    IF ROW(
        NEW.status, NEW.completed_version_id, NEW.verification_generation,
        NEW.retry_count, NEW.next_attempt_at, NEW.stable_error_code
    ) IS DISTINCT FROM ROW(
        OLD.status, OLD.completed_version_id, OLD.verification_generation,
        OLD.retry_count, OLD.next_attempt_at, OLD.stable_error_code
    ) AND NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'FILE_UPLOAD_INTENT_VERSION_INVALID';
    END IF;
    IF NEW.version < OLD.version THEN
        RAISE EXCEPTION 'FILE_UPLOAD_INTENT_VERSION_INVALID';
    END IF;
    IF NEW.status = 'completed' THEN
        SELECT v.id, v.object_key, d.user_id, d.subject_id
          INTO v_version
          FROM document_versions v
          JOIN user_documents d ON d.id = v.document_id
         WHERE v.id = NEW.completed_version_id;
        IF NOT FOUND OR v_version.object_key <> NEW.final_key
           OR v_version.user_id <> NEW.user_id OR v_version.subject_id <> NEW.subject_id THEN
            RAISE EXCEPTION 'FILE_UPLOAD_INTENT_COMPLETION_INVALID';
        END IF;
    ELSIF NEW.completed_version_id IS NOT NULL THEN
        RAISE EXCEPTION 'FILE_UPLOAD_INTENT_COMPLETION_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_guard_document() RETURNS trigger AS $$
DECLARE
    v_subject_user uuid;
    v_version_document uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'USER_DOCUMENT_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT user_id INTO v_subject_user FROM subjects WHERE id = NEW.subject_id;
        IF NOT FOUND OR v_subject_user <> NEW.user_id OR NEW.purpose <> 'subject_library'
           OR NEW.current_version_id IS NOT NULL OR NEW.version <> 1 THEN
            RAISE EXCEPTION 'USER_DOCUMENT_INITIAL_STATE_INVALID';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        NEW.user_id, NEW.subject_id, NEW.purpose, NEW.display_name, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.subject_id, OLD.purpose, OLD.display_name, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'USER_DOCUMENT_BINDING_IMMUTABLE';
    END IF;
    IF OLD.current_version_id IS NOT NULL OR NEW.current_version_id IS NULL THEN
        RAISE EXCEPTION 'USER_DOCUMENT_CURRENT_VERSION_IMMUTABLE';
    END IF;
    SELECT document_id INTO v_version_document
      FROM document_versions WHERE id = NEW.current_version_id;
    IF NOT FOUND OR v_version_document <> NEW.id THEN
        RAISE EXCEPTION 'USER_DOCUMENT_CURRENT_VERSION_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_guard_document_version() RETURNS trigger AS $$
DECLARE
    v_document record;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'DOCUMENT_VERSION_IMMUTABLE';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DOCUMENT_VERSION_DELETE_FORBIDDEN';
    END IF;
    SELECT user_id, subject_id INTO v_document FROM user_documents WHERE id = NEW.document_id;
    IF NOT FOUND OR NEW.version_no <> 1
       OR NEW.object_key !~ '^objects/[0-9a-f]{32}/[0-9a-f]{32}$'
       OR NEW.sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'DOCUMENT_VERSION_INITIAL_STATE_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_guard_storage_allocation() RETURNS trigger AS $$
DECLARE
    v_version record;
    v_account record;
    v_ledger record;
    v_intent record;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'FILE_STORAGE_ALLOCATION_IMMUTABLE';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'FILE_STORAGE_ALLOCATION_DELETE_FORBIDDEN';
    END IF;
    SELECT v.size_bytes, v.object_key, d.user_id, d.subject_id
      INTO v_version
      FROM document_versions v JOIN user_documents d ON d.id = v.document_id
     WHERE v.id = NEW.document_version_id;
    SELECT user_id, subscription_id, quota_type INTO v_account
      FROM quota_accounts WHERE id = NEW.quota_account_id;
    SELECT account_id, user_id, subscription_id, quota_type, action,
           frozen_delta, available_delta, business_type, business_id
      INTO v_ledger FROM quota_ledger_entries WHERE id = NEW.consume_ledger_id;
    SELECT id, user_id, subject_id, final_key INTO v_intent
      FROM file_upload_intents WHERE final_key = v_version.object_key;
    IF NOT FOUND OR v_version.size_bytes IS NULL OR v_account.user_id IS NULL
       OR v_ledger.account_id IS NULL
       OR NEW.size_bytes <> v_version.size_bytes
       OR NEW.user_id <> v_version.user_id OR NEW.user_id <> v_account.user_id
       OR NEW.user_id <> v_ledger.user_id OR NEW.user_id <> v_intent.user_id
       OR v_intent.subject_id <> v_version.subject_id
       OR v_account.quota_type <> 'storage_bytes'
       OR v_ledger.account_id <> NEW.quota_account_id
       OR v_ledger.subscription_id <> v_account.subscription_id
       OR v_ledger.quota_type <> 'storage_bytes'
       OR v_ledger.action <> 'consume'
       OR v_ledger.available_delta <> 0
       OR v_ledger.frozen_delta <> -NEW.size_bytes
       OR v_ledger.business_type <> 'file_upload'
       OR v_ledger.business_id <> v_intent.id THEN
        RAISE EXCEPTION 'FILE_STORAGE_ALLOCATION_BINDING_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_guard_subject_version_reference() RETURNS trigger AS $$
DECLARE
    v_subject_version record;
    v_document_version record;
    v_field_type text;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_DOCUMENT_REFERENCE_IMMUTABLE';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_DOCUMENT_REFERENCE_DELETE_FORBIDDEN';
    END IF;
    SELECT v.subject_id, s.user_id, v.field_values, v.schema_snapshot
      INTO v_subject_version
      FROM subject_versions v JOIN subjects s ON s.id = v.subject_id
     WHERE v.id = NEW.subject_version_id;
    SELECT v.detected_file_kind, d.user_id, d.subject_id
      INTO v_document_version
      FROM document_versions v JOIN user_documents d ON d.id = v.document_id
     WHERE v.id = NEW.document_version_id
       AND EXISTS (
           SELECT 1 FROM file_upload_intents i
            WHERE i.completed_version_id = v.id AND i.status = 'completed'
       );
    SELECT field->>'field_type' INTO v_field_type
      FROM jsonb_array_elements(v_subject_version.schema_snapshot->'fields') field
     WHERE field->>'field_key' = NEW.field_key;
    IF NOT FOUND OR v_subject_version.subject_id IS NULL
       OR v_document_version.subject_id IS NULL
       OR v_field_type NOT IN ('image', 'file')
       OR v_subject_version.user_id <> v_document_version.user_id
       OR v_subject_version.subject_id <> v_document_version.subject_id
       OR v_subject_version.field_values->NEW.field_key->>'document_version_id'
          <> NEW.document_version_id::text
       OR (v_field_type = 'image'
           AND v_document_version.detected_file_kind NOT IN ('jpeg', 'png', 'webp')) THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_DOCUMENT_REFERENCE_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_assert_document_complete() RETURNS trigger AS $$
DECLARE
    v_current_version_id uuid;
    v_document_id uuid;
BEGIN
    SELECT current_version_id INTO v_current_version_id
      FROM user_documents WHERE id = NEW.id;
    SELECT document_id INTO v_document_id
      FROM document_versions WHERE id = v_current_version_id;
    IF v_current_version_id IS NULL OR v_document_id <> NEW.id THEN
        RAISE EXCEPTION 'USER_DOCUMENT_INCOMPLETE' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_assert_version_complete() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM file_upload_intents i
          JOIN user_documents d ON d.current_version_id = NEW.id
          JOIN file_storage_allocations a ON a.document_version_id = NEW.id
         WHERE i.completed_version_id = NEW.id AND i.status = 'completed'
           AND i.user_id = d.user_id AND i.subject_id = d.subject_id
           AND i.final_key = NEW.object_key AND a.user_id = d.user_id
           AND a.size_bytes = NEW.size_bytes
    ) THEN
        RAISE EXCEPTION 'DOCUMENT_VERSION_COMPLETION_INCOMPLETE'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_guard_storage_ledger() RETURNS trigger AS $$
DECLARE
    v_account record;
    v_usage bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RETURN NEW;
    END IF;
    IF NEW.quota_type = 'storage_bytes' AND NEW.action IN (
        'grant', 'compensate', 'manual_deduct',
        'plan_change_forfeit', 'plan_change_transfer_out', 'plan_change_transfer_in',
        'cycle_forfeit', 'cycle_late_release_forfeit'
    ) THEN
        RAISE EXCEPTION 'STORAGE_CAPACITY_MIGRATION_FORBIDDEN';
    END IF;
    IF NEW.action = 'storage_capacity_reconcile' THEN
        SELECT user_id, entitlement_amount INTO v_account
          FROM quota_accounts WHERE id = NEW.account_id;
        SELECT COALESCE(SUM(size_bytes), 0) INTO v_usage
          FROM file_storage_allocations WHERE user_id = v_account.user_id;
        IF NEW.quota_type <> 'storage_bytes' OR NEW.hold_id IS NOT NULL
           OR NEW.frozen_delta <> 0
           OR NEW.available_after <> GREATEST(v_account.entitlement_amount - v_usage, 0) THEN
            RAISE EXCEPTION 'STORAGE_CAPACITY_RECONCILIATION_INVALID';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS documents_upload_intent_guard ON file_upload_intents;
CREATE TRIGGER documents_upload_intent_guard
BEFORE INSERT OR UPDATE OR DELETE ON file_upload_intents
FOR EACH ROW EXECUTE FUNCTION documents_guard_upload_intent();

DROP TRIGGER IF EXISTS documents_document_guard ON user_documents;
CREATE TRIGGER documents_document_guard
BEFORE INSERT OR UPDATE OR DELETE ON user_documents
FOR EACH ROW EXECUTE FUNCTION documents_guard_document();

DROP TRIGGER IF EXISTS documents_version_guard ON document_versions;
CREATE TRIGGER documents_version_guard
BEFORE INSERT OR UPDATE OR DELETE ON document_versions
FOR EACH ROW EXECUTE FUNCTION documents_guard_document_version();

DROP TRIGGER IF EXISTS documents_allocation_guard ON file_storage_allocations;
CREATE TRIGGER documents_allocation_guard
BEFORE INSERT OR UPDATE OR DELETE ON file_storage_allocations
FOR EACH ROW EXECUTE FUNCTION documents_guard_storage_allocation();

DROP TRIGGER IF EXISTS documents_subject_version_reference_guard
ON subject_version_document_references;
CREATE TRIGGER documents_subject_version_reference_guard
BEFORE INSERT OR UPDATE OR DELETE ON subject_version_document_references
FOR EACH ROW EXECUTE FUNCTION documents_guard_subject_version_reference();

DROP TRIGGER IF EXISTS documents_document_complete ON user_documents;
CREATE CONSTRAINT TRIGGER documents_document_complete
AFTER INSERT ON user_documents DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION documents_assert_document_complete();

DROP TRIGGER IF EXISTS documents_version_complete ON document_versions;
CREATE CONSTRAINT TRIGGER documents_version_complete
AFTER INSERT ON document_versions DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION documents_assert_version_complete();

DROP TRIGGER IF EXISTS documents_storage_ledger_guard ON quota_ledger_entries;
CREATE TRIGGER documents_storage_ledger_guard
BEFORE INSERT ON quota_ledger_entries
FOR EACH ROW EXECUTE FUNCTION documents_guard_storage_ledger();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS documents_storage_ledger_guard ON quota_ledger_entries;
DROP TRIGGER IF EXISTS documents_version_complete ON document_versions;
DROP TRIGGER IF EXISTS documents_document_complete ON user_documents;
DROP TRIGGER IF EXISTS documents_subject_version_reference_guard
ON subject_version_document_references;
DROP TRIGGER IF EXISTS documents_allocation_guard ON file_storage_allocations;
DROP TRIGGER IF EXISTS documents_version_guard ON document_versions;
DROP TRIGGER IF EXISTS documents_document_guard ON user_documents;
DROP TRIGGER IF EXISTS documents_upload_intent_guard ON file_upload_intents;
DROP FUNCTION IF EXISTS documents_guard_storage_ledger();
DROP FUNCTION IF EXISTS documents_assert_version_complete();
DROP FUNCTION IF EXISTS documents_assert_document_complete();
DROP FUNCTION IF EXISTS documents_guard_subject_version_reference();
DROP FUNCTION IF EXISTS documents_guard_storage_allocation();
DROP FUNCTION IF EXISTS documents_guard_document_version();
DROP FUNCTION IF EXISTS documents_guard_document();
DROP FUNCTION IF EXISTS documents_guard_upload_intent();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARD_SQL)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
        ("quotas", "0010_remove_quotaledgerentry_quota_ledger_hold_by_action_and_more"),
    ]
    operations = [migrations.RunPython(install_guards, remove_guards)]
