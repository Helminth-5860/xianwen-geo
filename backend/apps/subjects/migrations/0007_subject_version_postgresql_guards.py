from django.db import migrations


INSTALL_SQL = r"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM subject_type_field_configs c
        JOIN subject_field_definitions d ON d.id = c.field_definition_id
        WHERE c.name_role <> 'none'
          AND NOT (
              (c.name_role = 'official_name' AND d.field_type IN ('text', 'single', 'select'))
              OR
              (c.name_role IN ('alias', 'english_name', 'product')
               AND d.field_type IN ('text', 'single', 'select', 'multi'))
          )
    ) THEN
        RAISE EXCEPTION 'SUBJECT_SCHEMA_NAME_ROLE_TYPE_INVALID'
            USING ERRCODE = 'check_violation';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION subjects_assert_name_role_type(p_subject_type_id uuid)
RETURNS void AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM subject_type_field_configs c
        JOIN subject_field_definitions d ON d.id = c.field_definition_id
        WHERE c.subject_type_id = p_subject_type_id
          AND c.name_role <> 'none'
          AND NOT (
              (c.name_role = 'official_name' AND d.field_type IN ('text', 'single', 'select'))
              OR
              (c.name_role IN ('alias', 'english_name', 'product')
               AND d.field_type IN ('text', 'single', 'select', 'multi'))
          )
    ) THEN
        RAISE EXCEPTION 'SUBJECT_SCHEMA_NAME_ROLE_TYPE_INVALID'
            USING ERRCODE = 'check_violation';
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_validate_name_role_type() RETURNS trigger AS $$
BEGIN
    PERFORM subjects_assert_name_role_type(NEW.subject_type_id);
    IF TG_OP = 'UPDATE' AND OLD.subject_type_id IS DISTINCT FROM NEW.subject_type_id THEN
        PERFORM subjects_assert_name_role_type(OLD.subject_type_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_subject() RETURNS trigger AS $$
DECLARE
    v_new_subject_id uuid;
    v_new_version_no bigint;
    v_old_version_no bigint;
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
    IF OLD.status = 'archived' AND (
        NEW.draft_values IS DISTINCT FROM OLD.draft_values OR
        NEW.current_version_id IS DISTINCT FROM OLD.current_version_id
    ) THEN
        RAISE EXCEPTION 'SUBJECT_ARCHIVED_READ_ONLY';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'draft' AND NEW.status IN ('active', 'archived')) OR
        (OLD.status = 'active' AND NEW.status = 'archived') OR
        (OLD.status = 'archived' AND NEW.status = 'active')
    ) THEN
        RAISE EXCEPTION 'SUBJECT_STATE_CONFLICT';
    END IF;
    IF NEW.current_version_id IS DISTINCT FROM OLD.current_version_id THEN
        IF NEW.current_version_id IS NULL THEN
            RAISE EXCEPTION 'SUBJECT_CURRENT_VERSION_REQUIRED';
        END IF;
        SELECT subject_id, version_no
        INTO v_new_subject_id, v_new_version_no
        FROM subject_versions
        WHERE id = NEW.current_version_id;
        IF NOT FOUND OR v_new_subject_id <> NEW.id THEN
            RAISE EXCEPTION 'SUBJECT_CURRENT_VERSION_INVALID';
        END IF;
        IF OLD.current_version_id IS NULL THEN
            IF v_new_version_no <> 1 OR NEW.retest_required THEN
                RAISE EXCEPTION 'SUBJECT_CURRENT_VERSION_INVALID';
            END IF;
        ELSE
            SELECT version_no INTO v_old_version_no
            FROM subject_versions WHERE id = OLD.current_version_id;
            IF v_new_version_no <> v_old_version_no + 1 OR NOT NEW.retest_required THEN
                RAISE EXCEPTION 'SUBJECT_CURRENT_VERSION_INVALID';
            END IF;
        END IF;
    END IF;
    IF (
        NEW.status IS DISTINCT FROM OLD.status OR
        NEW.draft_values IS DISTINCT FROM OLD.draft_values OR
        NEW.current_version_id IS DISTINCT FROM OLD.current_version_id OR
        NEW.retest_required IS DISTINCT FROM OLD.retest_required
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
DECLARE
    v_subject record;
    v_expected bigint;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_IMMUTABLE';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_DELETE_FORBIDDEN';
    END IF;
    SELECT schema_version, schema_snapshot_format_version, schema_snapshot, schema_digest
    INTO v_subject
    FROM subjects
    WHERE id = NEW.subject_id;
    IF NOT FOUND OR ROW(
        NEW.schema_version, NEW.schema_snapshot_format_version,
        NEW.schema_snapshot, NEW.schema_digest
    ) IS DISTINCT FROM ROW(
        v_subject.schema_version, v_subject.schema_snapshot_format_version,
        v_subject.schema_snapshot, v_subject.schema_digest
    ) THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_SCHEMA_MISMATCH'
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT COALESCE(MAX(version_no), 0) + 1 INTO v_expected
    FROM subject_versions WHERE subject_id = NEW.subject_id;
    IF NEW.version_no <> v_expected THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_SEQUENCE_INVALID'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_semantic() RETURNS trigger AS $$
DECLARE
    v_current_version_id uuid;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT s.current_version_id INTO v_current_version_id
        FROM subject_versions v
        JOIN subjects s ON s.id = v.subject_id
        WHERE v.id = NEW.subject_version_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'SUBJECT_SEMANTIC_VERSION_INVALID'
                USING ERRCODE = 'check_violation';
        END IF;
        IF v_current_version_id = NEW.subject_version_id THEN
            RAISE EXCEPTION 'SUBJECT_SEMANTIC_VERSION_FINALIZED';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'SUBJECT_SEMANTIC_IMMUTABLE';
    END IF;
    RAISE EXCEPTION 'SUBJECT_SEMANTIC_DELETE_FORBIDDEN';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_assert_version_chain(p_subject_id uuid) RETURNS void AS $$
DECLARE
    v_current_version_id uuid;
    v_count bigint;
    v_min bigint;
    v_max bigint;
    v_current_no bigint;
BEGIN
    SELECT current_version_id INTO v_current_version_id
    FROM subjects WHERE id = p_subject_id;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT COUNT(*), MIN(version_no), MAX(version_no)
    INTO v_count, v_min, v_max
    FROM subject_versions WHERE subject_id = p_subject_id;
    IF v_count = 0 THEN
        IF v_current_version_id IS NOT NULL THEN
            RAISE EXCEPTION 'SUBJECT_CURRENT_VERSION_INVALID'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN;
    END IF;
    IF v_min <> 1 OR v_max <> v_count OR v_current_version_id IS NULL THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_SEQUENCE_INVALID'
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT version_no INTO v_current_no
    FROM subject_versions
    WHERE id = v_current_version_id AND subject_id = p_subject_id;
    IF NOT FOUND OR v_current_no <> v_max THEN
        RAISE EXCEPTION 'SUBJECT_CURRENT_VERSION_INVALID'
            USING ERRCODE = 'check_violation';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM subject_versions v
        JOIN subjects s ON s.id = v.subject_id
        WHERE v.subject_id = p_subject_id
          AND ROW(v.schema_version, v.schema_snapshot_format_version, v.schema_snapshot, v.schema_digest)
              IS DISTINCT FROM
              ROW(s.schema_version, s.schema_snapshot_format_version, s.schema_snapshot, s.schema_digest)
    ) THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_SCHEMA_MISMATCH'
            USING ERRCODE = 'check_violation';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM subject_versions v
        LEFT JOIN subject_names n
          ON n.subject_version_id = v.id AND n.role = 'official_name'
        WHERE v.subject_id = p_subject_id
        GROUP BY v.id
        HAVING COUNT(n.id) <> 1
    ) THEN
        RAISE EXCEPTION 'SUBJECT_OFFICIAL_NAME_INVALID'
            USING ERRCODE = 'check_violation';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM subject_events e
        LEFT JOIN subject_versions v ON v.id = e.subject_version_id
        WHERE e.subject_id = p_subject_id
          AND (
              (e.event_type = 'version_committed'
               AND (e.subject_version_id IS NULL OR v.subject_id <> e.subject_id))
              OR
              (e.event_type <> 'version_committed' AND e.subject_version_id IS NOT NULL)
          )
    ) THEN
        RAISE EXCEPTION 'SUBJECT_VERSION_EVENT_INVALID'
            USING ERRCODE = 'check_violation';
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_validate_version_chain_from_subject() RETURNS trigger AS $$
BEGIN
    PERFORM subjects_assert_version_chain(NEW.id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_validate_version_chain_from_version() RETURNS trigger AS $$
BEGIN
    PERFORM subjects_assert_version_chain(NEW.subject_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_validate_version_chain_from_semantic() RETURNS trigger AS $$
DECLARE
    v_subject_id uuid;
BEGIN
    SELECT subject_id INTO v_subject_id
    FROM subject_versions WHERE id = NEW.subject_version_id;
    PERFORM subjects_assert_version_chain(v_subject_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_validate_version_chain_from_event() RETURNS trigger AS $$
BEGIN
    PERFORM subjects_assert_version_chain(NEW.subject_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS subjects_version_guard ON subject_versions;
CREATE TRIGGER subjects_version_guard
BEFORE INSERT OR UPDATE OR DELETE ON subject_versions
FOR EACH ROW EXECUTE FUNCTION subjects_guard_subject_version();

CREATE TRIGGER subjects_name_guard
BEFORE INSERT OR UPDATE OR DELETE ON subject_names
FOR EACH ROW EXECUTE FUNCTION subjects_guard_semantic();

CREATE TRIGGER subjects_product_guard
BEFORE INSERT OR UPDATE OR DELETE ON subject_products
FOR EACH ROW EXECUTE FUNCTION subjects_guard_semantic();

CREATE CONSTRAINT TRIGGER subjects_config_name_role_type
AFTER INSERT OR UPDATE ON subject_type_field_configs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_name_role_type();

CREATE CONSTRAINT TRIGGER subjects_version_chain_subject
AFTER INSERT OR UPDATE ON subjects
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_version_chain_from_subject();

CREATE CONSTRAINT TRIGGER subjects_version_chain_version
AFTER INSERT OR UPDATE ON subject_versions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_version_chain_from_version();

CREATE CONSTRAINT TRIGGER subjects_version_chain_name
AFTER INSERT OR UPDATE ON subject_names
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_version_chain_from_semantic();

CREATE CONSTRAINT TRIGGER subjects_version_chain_product
AFTER INSERT OR UPDATE ON subject_products
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_version_chain_from_semantic();

CREATE CONSTRAINT TRIGGER subjects_version_chain_event
AFTER INSERT OR UPDATE ON subject_events
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_version_chain_from_event();
"""


REMOVE_SQL = r"""
DROP TRIGGER IF EXISTS subjects_version_chain_event ON subject_events;
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

DROP TRIGGER IF EXISTS subjects_version_chain_product ON subject_products;
DROP TRIGGER IF EXISTS subjects_version_chain_name ON subject_names;
DROP TRIGGER IF EXISTS subjects_version_chain_version ON subject_versions;
DROP TRIGGER IF EXISTS subjects_version_chain_subject ON subjects;
DROP TRIGGER IF EXISTS subjects_config_name_role_type ON subject_type_field_configs;
DROP TRIGGER IF EXISTS subjects_product_guard ON subject_products;
DROP TRIGGER IF EXISTS subjects_name_guard ON subject_names;
DROP TRIGGER IF EXISTS subjects_version_guard ON subject_versions;
DROP FUNCTION IF EXISTS subjects_validate_version_chain_from_event();
DROP FUNCTION IF EXISTS subjects_validate_version_chain_from_semantic();
DROP FUNCTION IF EXISTS subjects_validate_version_chain_from_version();
DROP FUNCTION IF EXISTS subjects_validate_version_chain_from_subject();
DROP FUNCTION IF EXISTS subjects_assert_version_chain(uuid);
DROP FUNCTION IF EXISTS subjects_guard_semantic();
DROP FUNCTION IF EXISTS subjects_validate_name_role_type();
DROP FUNCTION IF EXISTS subjects_assert_name_role_type(uuid);
CREATE TRIGGER subjects_version_guard
BEFORE UPDATE OR DELETE ON subject_versions
FOR EACH ROW EXECUTE FUNCTION subjects_guard_subject_version();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(INSTALL_SQL)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REMOVE_SQL)


class Migration(migrations.Migration):
    dependencies = [("subjects", "0006_subject_versions_names_products")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
