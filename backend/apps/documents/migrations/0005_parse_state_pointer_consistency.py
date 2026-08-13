from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION documents_assert_parse_state_for_version(
    p_document_version uuid
) RETURNS void AS $$
DECLARE
    v_owner record;
    v_state record;
    v_latest record;
    v_confirmed record;
    v_max integer;
    v_max_confirmation integer;
BEGIN
    SELECT d.user_id, d.subject_id, v.document_id
      INTO v_owner
      FROM document_versions v
      JOIN user_documents d ON d.id = v.document_id
     WHERE v.id = p_document_version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_DOCUMENT_VERSION_INVALID';
    END IF;

    SELECT MAX(version_no),
           MAX(version_no) FILTER (WHERE source = 'user_confirmation')
      INTO v_max, v_max_confirmation
      FROM document_parsed_versions
     WHERE document_version_id = p_document_version;

    SELECT id, user_id, subject_id, document_id, document_version_id,
           latest_parsed_version_id, current_confirmed_version_id
      INTO v_state
      FROM document_parse_states
     WHERE document_version_id = p_document_version;

    IF v_max IS NULL THEN
        IF FOUND AND (
            v_state.latest_parsed_version_id IS NOT NULL
            OR v_state.current_confirmed_version_id IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_POINTER_INVALID';
        END IF;
        RETURN;
    END IF;

    IF NOT FOUND OR v_state.latest_parsed_version_id IS NULL
       OR v_state.user_id <> v_owner.user_id
       OR v_state.subject_id <> v_owner.subject_id
       OR v_state.document_id <> v_owner.document_id
       OR v_state.document_version_id <> p_document_version THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_POINTER_INVALID';
    END IF;

    SELECT document_version_id, version_no, user_id, subject_id, document_id
      INTO v_latest
      FROM document_parsed_versions
     WHERE id = v_state.latest_parsed_version_id;
    IF NOT FOUND OR v_latest.document_version_id <> p_document_version
       OR v_latest.version_no <> v_max
       OR v_latest.user_id <> v_owner.user_id
       OR v_latest.subject_id <> v_owner.subject_id
       OR v_latest.document_id <> v_owner.document_id THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_LATEST_INVALID';
    END IF;

    IF v_max_confirmation IS NULL THEN
        IF v_state.current_confirmed_version_id IS NOT NULL THEN
            RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_CONFIRMED_INVALID';
        END IF;
        RETURN;
    END IF;

    IF v_state.current_confirmed_version_id IS NULL THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_CONFIRMED_INVALID';
    END IF;
    SELECT document_version_id, version_no, source, user_id, subject_id, document_id
      INTO v_confirmed
      FROM document_parsed_versions
     WHERE id = v_state.current_confirmed_version_id;
    IF NOT FOUND OR v_confirmed.document_version_id <> p_document_version
       OR v_confirmed.source <> 'user_confirmation'
       OR v_confirmed.version_no <> v_max_confirmation
       OR v_confirmed.version_no > v_max
       OR v_confirmed.user_id <> v_owner.user_id
       OR v_confirmed.subject_id <> v_owner.subject_id
       OR v_confirmed.document_id <> v_owner.document_id THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_STATE_CONFIRMED_INVALID';
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_assert_parse_state() RETURNS trigger AS $$
BEGIN
    PERFORM documents_assert_parse_state_for_version(NEW.document_version_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION documents_assert_parsed_version_state() RETURNS trigger AS $$
BEGIN
    PERFORM documents_assert_parse_state_for_version(NEW.document_version_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER document_parsed_version_state_consistency
AFTER INSERT ON document_parsed_versions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION documents_assert_parsed_version_state();

DO $$
DECLARE
    v_document_version uuid;
BEGIN
    FOR v_document_version IN
        SELECT document_version_id FROM document_parsed_versions
        UNION
        SELECT document_version_id FROM document_parse_states
    LOOP
        PERFORM documents_assert_parse_state_for_version(v_document_version);
    END LOOP;
END $$;
"""


REVERSE_SQL = r"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM document_parsed_versions LIMIT 1) THEN
        RAISE EXCEPTION 'DOCUMENT_PARSE_EVIDENCE_REQUIRES_BACKUP_AND_FORWARD_FIX';
    END IF;
END $$;
DROP TRIGGER IF EXISTS document_parsed_version_state_consistency
    ON document_parsed_versions;
DROP FUNCTION IF EXISTS documents_assert_parsed_version_state();
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
DROP FUNCTION IF EXISTS documents_assert_parse_state_for_version(uuid);
"""


def install_pointer_consistency(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def remove_pointer_consistency(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("documents", "0004_parse_postgresql_guards")]

    operations = [migrations.RunPython(install_pointer_consistency, remove_pointer_consistency)]
