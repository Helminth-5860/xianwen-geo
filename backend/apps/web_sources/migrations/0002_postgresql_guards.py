from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION web_source_import_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'WEB_SOURCE_IMPORT_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.user_id, NEW.subject_id, NEW.canonical_url, NEW.display_url,
            NEW.has_query, NEW.hostname_fingerprint, NEW.idempotency_key_version,
            NEW.idempotency_key_digest, NEW.request_digest, NEW.created_at)
           IS DISTINCT FROM
           (OLD.user_id, OLD.subject_id, OLD.canonical_url, OLD.display_url,
            OLD.has_query, OLD.hostname_fingerprint, OLD.idempotency_key_version,
            OLD.idempotency_key_digest, OLD.request_digest, OLD.created_at) THEN
            RAISE EXCEPTION 'WEB_SOURCE_IMPORT_BINDING_IMMUTABLE';
        END IF;
        IF OLD.status IN ('succeeded', 'failed') AND (
            NEW.status <> OLD.status OR NEW.finished_at IS DISTINCT FROM OLD.finished_at
            OR NEW.generation IS DISTINCT FROM OLD.generation
            OR NEW.attempts <> OLD.attempts OR NEW.retry_count <> OLD.retry_count
            OR NEW.stable_error_code IS DISTINCT FROM OLD.stable_error_code
        ) THEN
            RAISE EXCEPTION 'WEB_SOURCE_IMPORT_TERMINAL';
        END IF;
        IF OLD.status = 'queued' AND NEW.status NOT IN ('queued', 'fetching')
           OR OLD.status = 'fetching' AND NEW.status NOT IN ('fetching', 'retry_wait', 'succeeded', 'failed')
           OR OLD.status = 'retry_wait' AND NEW.status NOT IN ('retry_wait', 'fetching')
           OR OLD.status IN ('succeeded', 'failed') AND NEW.status <> OLD.status THEN
            RAISE EXCEPTION 'WEB_SOURCE_IMPORT_TRANSITION_INVALID';
        END IF;
        IF NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'WEB_SOURCE_IMPORT_VERSION_INVALID';
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM subjects s WHERE s.id = NEW.subject_id AND s.user_id = NEW.user_id
    ) THEN
        RAISE EXCEPTION 'WEB_SOURCE_IMPORT_OWNERSHIP_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER web_source_import_guard_trigger
BEFORE INSERT OR UPDATE OR DELETE ON web_source_imports
FOR EACH ROW EXECUTE FUNCTION web_source_import_guard();

CREATE OR REPLACE FUNCTION web_source_evidence_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'WEB_SOURCE_EVIDENCE_IMMUTABLE';
    END IF;
    IF TG_TABLE_NAME = 'web_source_snapshots' THEN
        IF NOT EXISTS (
        SELECT 1 FROM web_source_imports i
        WHERE i.id = NEW.import_record_id AND i.user_id = NEW.user_id AND i.subject_id = NEW.subject_id
    ) THEN RAISE EXCEPTION 'WEB_SOURCE_SNAPSHOT_OWNERSHIP_INVALID';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'web_source_parsed_versions' THEN
        IF NOT EXISTS (
        SELECT 1 FROM web_source_imports i JOIN web_source_snapshots s ON s.import_record_id = i.id
        WHERE i.id = NEW.import_record_id AND s.id = NEW.snapshot_id
          AND i.user_id = NEW.user_id AND i.subject_id = NEW.subject_id
    ) THEN RAISE EXCEPTION 'WEB_SOURCE_PARSED_OWNERSHIP_INVALID';
        END IF;
        IF NEW.source = 'user_confirmation' AND (
            NOT EXISTS (
                SELECT 1 FROM web_source_parsed_versions parent
                WHERE parent.id = NEW.parent_version_id
                  AND parent.import_record_id = NEW.import_record_id
                  AND parent.user_id = NEW.user_id AND parent.subject_id = NEW.subject_id
                  AND parent.version_no = NEW.version_no - 1
            ) OR NOT EXISTS (
                SELECT 1 FROM web_source_parsed_versions machine
                WHERE machine.id = NEW.machine_base_version_id
                  AND machine.import_record_id = NEW.import_record_id
                  AND machine.user_id = NEW.user_id AND machine.subject_id = NEW.subject_id
                  AND machine.source = 'machine' AND machine.version_no = 1
            )
        ) THEN RAISE EXCEPTION 'WEB_SOURCE_CONFIRMATION_CHAIN_INVALID';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'web_source_events' THEN
        IF NOT EXISTS (
        SELECT 1 FROM web_source_imports i WHERE i.id = NEW.import_record_id
          AND i.user_id = NEW.user_id AND i.subject_id = NEW.subject_id
    ) THEN RAISE EXCEPTION 'WEB_SOURCE_EVENT_OWNERSHIP_INVALID';
        END IF;
        IF NEW.snapshot_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM web_source_snapshots s
            WHERE s.id = NEW.snapshot_id AND s.import_record_id = NEW.import_record_id
              AND s.user_id = NEW.user_id AND s.subject_id = NEW.subject_id
        ) THEN RAISE EXCEPTION 'WEB_SOURCE_EVENT_SNAPSHOT_INVALID';
        END IF;
        IF NEW.parsed_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM web_source_parsed_versions v
            WHERE v.id = NEW.parsed_version_id AND v.import_record_id = NEW.import_record_id
              AND v.user_id = NEW.user_id AND v.subject_id = NEW.subject_id
        ) THEN RAISE EXCEPTION 'WEB_SOURCE_EVENT_VERSION_INVALID';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER web_source_snapshot_guard_trigger
BEFORE INSERT OR UPDATE OR DELETE ON web_source_snapshots
FOR EACH ROW EXECUTE FUNCTION web_source_evidence_guard();
CREATE TRIGGER web_source_parsed_guard_trigger
BEFORE INSERT OR UPDATE OR DELETE ON web_source_parsed_versions
FOR EACH ROW EXECUTE FUNCTION web_source_evidence_guard();
CREATE TRIGGER web_source_event_guard_trigger
BEFORE INSERT OR UPDATE OR DELETE ON web_source_events
FOR EACH ROW EXECUTE FUNCTION web_source_evidence_guard();

CREATE OR REPLACE FUNCTION web_source_pointer_consistency() RETURNS trigger AS $$
DECLARE
    import_uuid uuid;
    row_record record;
    version_count bigint;
    max_version bigint;
    max_confirmation bigint;
    snapshot_count bigint;
BEGIN
    IF TG_TABLE_NAME = 'web_source_imports' THEN
        import_uuid := NEW.id;
    ELSE
        import_uuid := NEW.import_record_id;
    END IF;
    SELECT * INTO row_record FROM web_source_imports WHERE id = import_uuid;
    SELECT COUNT(*), MAX(version_no) INTO version_count, max_version
      FROM web_source_parsed_versions WHERE import_record_id = import_uuid;
    SELECT COUNT(*) INTO snapshot_count
      FROM web_source_snapshots WHERE import_record_id = import_uuid;
    IF version_count > 0 AND (
        max_version <> version_count OR NOT EXISTS (
            SELECT 1 FROM web_source_parsed_versions
            WHERE id = row_record.latest_parsed_version_id
              AND import_record_id = import_uuid AND version_no = max_version
        )
    ) THEN RAISE EXCEPTION 'WEB_SOURCE_PARSED_SEQUENCE_OR_POINTER_INVALID';
    END IF;
    IF version_count = 0 AND (
        row_record.latest_parsed_version_id IS NOT NULL
        OR row_record.current_confirmed_version_id IS NOT NULL
    ) THEN RAISE EXCEPTION 'WEB_SOURCE_POINTER_WITHOUT_VERSION';
    END IF;
    IF version_count > 0 AND NOT EXISTS (
        SELECT 1 FROM web_source_parsed_versions
        WHERE import_record_id = import_uuid AND source = 'machine' AND version_no = 1
    ) THEN RAISE EXCEPTION 'WEB_SOURCE_MACHINE_VERSION_MISSING';
    END IF;
    IF row_record.status = 'succeeded' AND (version_count = 0 OR snapshot_count <> 1) THEN
        RAISE EXCEPTION 'WEB_SOURCE_SUCCEEDED_EVIDENCE_INVALID';
    END IF;
    IF row_record.status <> 'succeeded' AND snapshot_count <> 0 THEN
        RAISE EXCEPTION 'WEB_SOURCE_NON_SUCCEEDED_HAS_SNAPSHOT';
    END IF;
    SELECT MAX(version_no) INTO max_confirmation
      FROM web_source_parsed_versions
      WHERE import_record_id = import_uuid AND source = 'user_confirmation';
    IF max_confirmation IS NULL AND row_record.current_confirmed_version_id IS NOT NULL THEN
        RAISE EXCEPTION 'WEB_SOURCE_CONFIRMED_POINTER_INVALID';
    END IF;
    IF max_confirmation IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM web_source_parsed_versions
        WHERE id = row_record.current_confirmed_version_id
          AND import_record_id = import_uuid
          AND source = 'user_confirmation'
          AND version_no = max_confirmation
    ) THEN RAISE EXCEPTION 'WEB_SOURCE_CONFIRMED_POINTER_NOT_MAX';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER web_source_import_pointer_constraint
AFTER INSERT OR UPDATE ON web_source_imports DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION web_source_pointer_consistency();
CREATE CONSTRAINT TRIGGER web_source_parsed_pointer_constraint
AFTER INSERT ON web_source_parsed_versions DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION web_source_pointer_consistency();
CREATE CONSTRAINT TRIGGER web_source_snapshot_pointer_constraint
AFTER INSERT ON web_source_snapshots DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION web_source_pointer_consistency();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS web_source_snapshot_pointer_constraint ON web_source_snapshots;
DROP TRIGGER IF EXISTS web_source_parsed_pointer_constraint ON web_source_parsed_versions;
DROP TRIGGER IF EXISTS web_source_import_pointer_constraint ON web_source_imports;
DROP FUNCTION IF EXISTS web_source_pointer_consistency();
DROP TRIGGER IF EXISTS web_source_event_guard_trigger ON web_source_events;
DROP TRIGGER IF EXISTS web_source_parsed_guard_trigger ON web_source_parsed_versions;
DROP TRIGGER IF EXISTS web_source_snapshot_guard_trigger ON web_source_snapshots;
DROP FUNCTION IF EXISTS web_source_evidence_guard();
DROP TRIGGER IF EXISTS web_source_import_guard_trigger ON web_source_imports;
DROP FUNCTION IF EXISTS web_source_import_guard();
"""

def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("web_sources", "0001_initial")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
