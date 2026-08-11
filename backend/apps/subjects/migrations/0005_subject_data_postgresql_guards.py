from django.db import migrations


INSTALL_SQL = r"""
CREATE OR REPLACE FUNCTION subjects_guard_subject() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SUBJECT_DELETE_FORBIDDEN';
    END IF;
    IF ROW(
        NEW.user_id, NEW.subject_type_id, NEW.schema_version,
        NEW.schema_snapshot_format_version, NEW.schema_snapshot, NEW.schema_digest,
        NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.subject_type_id, OLD.schema_version,
        OLD.schema_snapshot_format_version, OLD.schema_snapshot, OLD.schema_digest,
        OLD.created_at
    ) THEN
        RAISE EXCEPTION 'SUBJECT_IMMUTABLE_BINDING';
    END IF;
    IF OLD.status = 'archived' AND NEW.draft_values IS DISTINCT FROM OLD.draft_values THEN
        RAISE EXCEPTION 'SUBJECT_ARCHIVED_READ_ONLY';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'draft' AND NEW.status IN ('active', 'archived')) OR
        (OLD.status = 'active' AND NEW.status = 'archived') OR
        (OLD.status = 'archived' AND NEW.status = 'active')
    ) THEN
        RAISE EXCEPTION 'SUBJECT_STATE_CONFLICT';
    END IF;
    IF (
        NEW.status IS DISTINCT FROM OLD.status OR
        NEW.draft_values IS DISTINCT FROM OLD.draft_values
    ) AND NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_CONFLICT';
    END IF;
    IF NEW.version < OLD.version THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_CONFLICT';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_subject_version() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_IMMUTABLE';
    END IF;
    RAISE EXCEPTION 'SUBJECT_VERSION_DELETE_FORBIDDEN';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_subject_event() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'SUBJECT_EVENT_IMMUTABLE';
    END IF;
    RAISE EXCEPTION 'SUBJECT_EVENT_DELETE_FORBIDDEN';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_context() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SUBJECT_CONTEXT_DELETE_FORBIDDEN';
    END IF;
    IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
        RAISE EXCEPTION 'SUBJECT_CONTEXT_USER_IMMUTABLE';
    END IF;
    IF NEW.current_subject_id IS DISTINCT FROM OLD.current_subject_id
       AND NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'SUBJECT_CONTEXT_VERSION_CONFLICT';
    END IF;
    IF NEW.version < OLD.version THEN
        RAISE EXCEPTION 'SUBJECT_CONTEXT_VERSION_CONFLICT';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_assert_context(p_user_id uuid) RETURNS void AS $$
DECLARE
    v_current_subject_id uuid;
BEGIN
    SELECT current_subject_id INTO v_current_subject_id
    FROM subject_contexts
    WHERE user_id = p_user_id;
    IF NOT FOUND OR v_current_subject_id IS NULL THEN
        RETURN;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM subjects
        WHERE id = v_current_subject_id
          AND user_id = p_user_id
          AND status <> 'archived'
    ) THEN
        RAISE EXCEPTION 'SUBJECT_CONTEXT_INVALID'
            USING ERRCODE = 'check_violation';
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_validate_context_from_context() RETURNS trigger AS $$
BEGIN
    PERFORM subjects_assert_context(NEW.user_id);
    IF TG_OP = 'UPDATE' AND OLD.user_id IS DISTINCT FROM NEW.user_id THEN
        PERFORM subjects_assert_context(OLD.user_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_validate_context_from_subject() RETURNS trigger AS $$
BEGIN
    PERFORM subjects_assert_context(NEW.user_id);
    IF OLD.user_id IS DISTINCT FROM NEW.user_id THEN
        PERFORM subjects_assert_context(OLD.user_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER subjects_subject_guard
BEFORE UPDATE OR DELETE ON subjects
FOR EACH ROW EXECUTE FUNCTION subjects_guard_subject();

CREATE TRIGGER subjects_version_guard
BEFORE UPDATE OR DELETE ON subject_versions
FOR EACH ROW EXECUTE FUNCTION subjects_guard_subject_version();

CREATE TRIGGER subjects_event_guard
BEFORE UPDATE OR DELETE ON subject_events
FOR EACH ROW EXECUTE FUNCTION subjects_guard_subject_event();

CREATE TRIGGER subjects_context_guard
BEFORE UPDATE OR DELETE ON subject_contexts
FOR EACH ROW EXECUTE FUNCTION subjects_guard_context();

CREATE CONSTRAINT TRIGGER subjects_context_consistency
AFTER INSERT OR UPDATE ON subject_contexts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_context_from_context();

CREATE CONSTRAINT TRIGGER subjects_context_subject_consistency
AFTER UPDATE OF status, user_id ON subjects
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_context_from_subject();
"""


REMOVE_SQL = r"""
DROP TRIGGER IF EXISTS subjects_context_subject_consistency ON subjects;
DROP TRIGGER IF EXISTS subjects_context_consistency ON subject_contexts;
DROP TRIGGER IF EXISTS subjects_context_guard ON subject_contexts;
DROP TRIGGER IF EXISTS subjects_event_guard ON subject_events;
DROP TRIGGER IF EXISTS subjects_version_guard ON subject_versions;
DROP TRIGGER IF EXISTS subjects_subject_guard ON subjects;
DROP FUNCTION IF EXISTS subjects_validate_context_from_subject();
DROP FUNCTION IF EXISTS subjects_validate_context_from_context();
DROP FUNCTION IF EXISTS subjects_assert_context(uuid);
DROP FUNCTION IF EXISTS subjects_guard_context();
DROP FUNCTION IF EXISTS subjects_guard_subject_event();
DROP FUNCTION IF EXISTS subjects_guard_subject_version();
DROP FUNCTION IF EXISTS subjects_guard_subject();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(INSTALL_SQL)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REMOVE_SQL)


class Migration(migrations.Migration):
    dependencies = [("subjects", "0004_subject_subjectcontext_subjectevent_subjectversion_and_more")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
