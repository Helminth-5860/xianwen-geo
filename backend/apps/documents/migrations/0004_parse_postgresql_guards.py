from django.db import migrations


GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION documents_guard_parse_job() RETURNS trigger AS $$
DECLARE
    v_owner record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_JOB_DELETE_FORBIDDEN';
    END IF;
    SELECT d.user_id, d.subject_id, v.document_id
      INTO v_owner
      FROM user_documents d
      JOIN document_versions v ON v.document_id = d.id
     WHERE d.id = NEW.document_id AND v.id = NEW.document_version_id;
    IF NOT FOUND OR v_owner.user_id <> NEW.user_id
       OR v_owner.subject_id <> NEW.subject_id
       OR v_owner.document_id <> NEW.document_id THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_JOB_OWNERSHIP_INVALID';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.generation IS NOT NULL
           OR NEW.attempts <> 0 OR NEW.retry_count <> 0
           OR NEW.finished_at IS NOT NULL THEN
            RAISE EXCEPTION 'DOCUMENT_PARSE_JOB_INITIAL_STATE_INVALID';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        NEW.user_id, NEW.subject_id, NEW.document_id, NEW.document_version_id,
        NEW.parser_key, NEW.parser_version, NEW.ocr_provider_key,
        NEW.idempotency_key_version, NEW.idempotency_key_digest,
        NEW.request_digest, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.subject_id, OLD.document_id, OLD.document_version_id,
        OLD.parser_key, OLD.parser_version, OLD.ocr_provider_key,
        OLD.idempotency_key_version, OLD.idempotency_key_digest,
        OLD.request_digest, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_JOB_BINDING_IMMUTABLE';
    END IF;
    IF OLD.status IN ('succeeded', 'failed') AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_JOB_TERMINAL';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'queued' AND NEW.status = 'running')
        OR (OLD.status = 'running' AND NEW.status IN ('retry_wait', 'succeeded', 'failed'))
        OR (OLD.status = 'retry_wait' AND NEW.status = 'running')
    ) THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_JOB_TRANSITION_INVALID';
    END IF;
    IF NEW.attempts < OLD.attempts OR NEW.retry_count < OLD.retry_count THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_JOB_COUNTER_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_guard_parsed_version() RETURNS trigger AS $$
DECLARE
    v_owner record;
    v_parent record;
    v_base record;
    v_expected integer;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'DOCUMENT_PARSED_VERSION_IMMUTABLE';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DOCUMENT_PARSED_VERSION_DELETE_FORBIDDEN';
    END IF;
    SELECT d.user_id, d.subject_id, v.document_id
      INTO v_owner
      FROM user_documents d
      JOIN document_versions v ON v.document_id = d.id
     WHERE d.id = NEW.document_id AND v.id = NEW.document_version_id;
    IF NOT FOUND OR v_owner.user_id <> NEW.user_id
       OR v_owner.subject_id <> NEW.subject_id
       OR v_owner.document_id <> NEW.document_id THEN
        RAISE EXCEPTION 'DOCUMENT_PARSED_VERSION_OWNERSHIP_INVALID';
    END IF;
    SELECT COALESCE(MAX(version_no), 0) + 1 INTO v_expected
      FROM document_parsed_versions WHERE document_version_id = NEW.document_version_id;
    IF NEW.version_no <> v_expected THEN
        RAISE EXCEPTION 'DOCUMENT_PARSED_VERSION_SEQUENCE_INVALID';
    END IF;
    IF NEW.source = 'parser' THEN
        IF NEW.version_no <> 1 OR NEW.parent_version_id IS NOT NULL
           OR NEW.machine_base_version_id IS NOT NULL
           OR NEW.confirmed_by_id IS NOT NULL OR NEW.confirmed_at IS NOT NULL THEN
            RAISE EXCEPTION 'DOCUMENT_PARSED_VERSION_PARSER_INVALID';
        END IF;
    ELSIF NEW.source = 'user_confirmation' THEN
        SELECT document_version_id, version_no INTO v_parent
          FROM document_parsed_versions WHERE id = NEW.parent_version_id;
        SELECT document_version_id, source INTO v_base
          FROM document_parsed_versions WHERE id = NEW.machine_base_version_id;
        IF NOT FOUND OR v_parent.document_version_id <> NEW.document_version_id
           OR v_parent.version_no <> NEW.version_no - 1
           OR v_base.document_version_id <> NEW.document_version_id
           OR v_base.source <> 'parser'
           OR NEW.confirmed_by_id <> NEW.user_id OR NEW.confirmed_at IS NULL THEN
            RAISE EXCEPTION 'DOCUMENT_PARSED_VERSION_CONFIRMATION_INVALID';
        END IF;
    ELSE
        RAISE EXCEPTION 'DOCUMENT_PARSED_VERSION_SOURCE_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_guard_parse_state() RETURNS trigger AS $$
DECLARE
    v_owner record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_DELETE_FORBIDDEN';
    END IF;
    SELECT d.user_id, d.subject_id, v.document_id
      INTO v_owner
      FROM user_documents d
      JOIN document_versions v ON v.document_id = d.id
     WHERE d.id = NEW.document_id AND v.id = NEW.document_version_id;
    IF NOT FOUND OR v_owner.user_id <> NEW.user_id
       OR v_owner.subject_id <> NEW.subject_id
       OR v_owner.document_id <> NEW.document_id THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_OWNERSHIP_INVALID';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.user_id, NEW.subject_id, NEW.document_id, NEW.document_version_id, NEW.created_at)
           IS DISTINCT FROM
           ROW(OLD.user_id, OLD.subject_id, OLD.document_id, OLD.document_version_id, OLD.created_at)
           OR NEW.version < OLD.version THEN
            RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_BINDING_INVALID';
        END IF;
        IF OLD.current_confirmed_version_id IS NOT NULL AND (
            NEW.current_confirmed_version_id IS NULL
            OR (
                SELECT version_no FROM document_parsed_versions
                 WHERE id = NEW.current_confirmed_version_id
            ) < (
                SELECT version_no FROM document_parsed_versions
                 WHERE id = OLD.current_confirmed_version_id
            )
        ) THEN
            RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_CONFIRMED_ROLLBACK';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_assert_parse_state() RETURNS trigger AS $$
DECLARE
    v_latest record;
    v_confirmed record;
    v_max integer;
BEGIN
    IF NEW.latest_parsed_version_id IS NULL THEN
        IF EXISTS (
            SELECT 1 FROM document_parsed_versions
             WHERE document_version_id = NEW.document_version_id
        ) OR NEW.current_confirmed_version_id IS NOT NULL THEN
            RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_POINTER_INVALID';
        END IF;
        RETURN NULL;
    END IF;
    SELECT document_version_id, version_no INTO v_latest
      FROM document_parsed_versions WHERE id = NEW.latest_parsed_version_id;
    SELECT MAX(version_no) INTO v_max
      FROM document_parsed_versions WHERE document_version_id = NEW.document_version_id;
    IF NOT FOUND OR v_latest.document_version_id <> NEW.document_version_id
       OR v_latest.version_no <> v_max THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_LATEST_INVALID';
    END IF;
    IF NEW.current_confirmed_version_id IS NOT NULL THEN
        SELECT document_version_id, version_no, source INTO v_confirmed
          FROM document_parsed_versions WHERE id = NEW.current_confirmed_version_id;
        IF NOT FOUND OR v_confirmed.document_version_id <> NEW.document_version_id
           OR v_confirmed.source <> 'user_confirmation'
           OR v_confirmed.version_no > v_latest.version_no THEN
            RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_CONFIRMED_INVALID';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_guard_parse_event() RETURNS trigger AS $$
DECLARE
    v_owner record;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_EVENT_IMMUTABLE';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_EVENT_DELETE_FORBIDDEN';
    END IF;
    SELECT d.user_id, d.subject_id, v.document_id
      INTO v_owner
      FROM user_documents d JOIN document_versions v ON v.document_id = d.id
     WHERE d.id = NEW.document_id AND v.id = NEW.document_version_id;
    IF NOT FOUND OR v_owner.user_id <> NEW.user_id
       OR v_owner.subject_id <> NEW.subject_id
       OR v_owner.document_id <> NEW.document_id
       OR (NEW.job_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM document_parse_jobs j
            WHERE j.id = NEW.job_id AND j.document_version_id = NEW.document_version_id
              AND j.user_id = NEW.user_id AND j.subject_id = NEW.subject_id
       ))
       OR (NEW.parsed_version_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM document_parsed_versions p
            WHERE p.id = NEW.parsed_version_id
              AND p.document_version_id = NEW.document_version_id
              AND p.user_id = NEW.user_id AND p.subject_id = NEW.subject_id
       )) THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_EVENT_OWNERSHIP_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER document_parse_job_guard
BEFORE INSERT OR UPDATE OR DELETE ON document_parse_jobs
FOR EACH ROW EXECUTE FUNCTION documents_guard_parse_job();

CREATE TRIGGER document_parsed_version_guard
BEFORE INSERT OR UPDATE OR DELETE ON document_parsed_versions
FOR EACH ROW EXECUTE FUNCTION documents_guard_parsed_version();

CREATE TRIGGER document_parse_state_guard
BEFORE INSERT OR UPDATE OR DELETE ON document_parse_states
FOR EACH ROW EXECUTE FUNCTION documents_guard_parse_state();

CREATE CONSTRAINT TRIGGER document_parse_state_consistency
AFTER INSERT OR UPDATE ON document_parse_states
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION documents_assert_parse_state();

CREATE TRIGGER document_parse_event_guard
BEFORE INSERT OR UPDATE OR DELETE ON document_parse_events
FOR EACH ROW EXECUTE FUNCTION documents_guard_parse_event();
"""

REVERSE_SQL = r"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM document_parsed_versions LIMIT 1) THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_EVIDENCE_REQUIRES_BACKUP_AND_FORWARD_FIX';
    END IF;
END $$;
DROP TRIGGER IF EXISTS document_parse_event_guard ON document_parse_events;
DROP TRIGGER IF EXISTS document_parse_state_consistency ON document_parse_states;
DROP TRIGGER IF EXISTS document_parse_state_guard ON document_parse_states;
DROP TRIGGER IF EXISTS document_parsed_version_guard ON document_parsed_versions;
DROP TRIGGER IF EXISTS document_parse_job_guard ON document_parse_jobs;
DROP FUNCTION IF EXISTS documents_guard_parse_event();
DROP FUNCTION IF EXISTS documents_assert_parse_state();
DROP FUNCTION IF EXISTS documents_guard_parse_state();
DROP FUNCTION IF EXISTS documents_guard_parsed_version();
DROP FUNCTION IF EXISTS documents_guard_parse_job();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARD_SQL)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("documents", "0003_documentparsedversion_documentparsejob_and_more")]

    operations = [migrations.RunPython(install_guards, remove_guards)]
