from django.db import migrations


INSTALL_SQL = r"""
CREATE UNIQUE INDEX subject_type_key_ci_unique
ON subject_types (lower(key));

CREATE UNIQUE INDEX subject_common_field_key_ci_unique
ON subject_field_definitions (lower(field_key))
WHERE scope = 'common';

CREATE UNIQUE INDEX subject_custom_field_key_ci_unique
ON subject_field_definitions (owner_subject_type_id, lower(field_key))
WHERE scope = 'custom';

CREATE UNIQUE INDEX subject_field_option_key_ci_unique
ON subject_field_options (field_config_id, lower(option_key));

CREATE OR REPLACE FUNCTION subjects_reject_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'subject catalog rows are immutable and cannot be deleted'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_type() RETURNS trigger AS $$
BEGIN
    IF NEW.key !~ '^[a-z][a-z0-9_]{0,63}$' THEN
        RAISE EXCEPTION 'invalid subject type key'
            USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.key IS DISTINCT FROM OLD.key OR
        NEW.is_builtin IS DISTINCT FROM OLD.is_builtin
    ) THEN
        RAISE EXCEPTION 'subject type machine semantics are immutable'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_definition() RETURNS trigger AS $$
BEGIN
    IF NEW.field_key !~ '^[a-z][a-z0-9_]{0,63}$' THEN
        RAISE EXCEPTION 'invalid subject field key'
            USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.field_key IS DISTINCT FROM OLD.field_key OR
        NEW.field_type IS DISTINCT FROM OLD.field_type OR
        NEW.scope IS DISTINCT FROM OLD.scope OR
        NEW.owner_subject_type_id IS DISTINCT FROM OLD.owner_subject_type_id OR
        NEW.is_builtin IS DISTINCT FROM OLD.is_builtin
    ) THEN
        RAISE EXCEPTION 'subject field machine semantics are immutable'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_config() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND (
        NEW.subject_type_id IS DISTINCT FROM OLD.subject_type_id OR
        NEW.field_definition_id IS DISTINCT FROM OLD.field_definition_id
    ) THEN
        RAISE EXCEPTION 'subject field config binding is immutable'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_guard_option() RETURNS trigger AS $$
BEGIN
    IF NEW.option_key !~ '^[a-z][a-z0-9_]{0,63}$' THEN
        RAISE EXCEPTION 'invalid subject option key'
            USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.field_config_id IS DISTINCT FROM OLD.field_config_id OR
        NEW.option_key IS DISTINCT FROM OLD.option_key
    ) THEN
        RAISE EXCEPTION 'subject option machine semantics are immutable'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_assert_schema(p_subject_type_id uuid)
RETURNS void AS $$
DECLARE
    v_status text;
    v_config record;
    v_text text;
    v_item jsonb;
BEGIN
    SELECT status INTO v_status
    FROM subject_types
    WHERE id = p_subject_type_id;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM subject_type_field_configs c
        JOIN subject_field_definitions d ON d.id = c.field_definition_id
        WHERE c.subject_type_id = p_subject_type_id
          AND d.scope = 'custom'
          AND d.owner_subject_type_id IS DISTINCT FROM p_subject_type_id
    ) THEN
        RAISE EXCEPTION 'custom field belongs to another subject type'
            USING ERRCODE = 'check_violation';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM subject_type_field_configs c
        JOIN subject_field_definitions d ON d.id = c.field_definition_id
        WHERE c.subject_type_id = p_subject_type_id
        GROUP BY lower(d.field_key)
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'field keys must be unique in a subject schema'
            USING ERRCODE = 'unique_violation';
    END IF;

    IF v_status = 'active' THEN
        IF (
            SELECT count(*)
            FROM subject_type_field_configs c
            WHERE c.subject_type_id = p_subject_type_id
              AND c.enabled
              AND c.required
              AND c.name_role = 'official_name'
        ) <> 1 THEN
            RAISE EXCEPTION 'active schema requires exactly one required official name'
                USING ERRCODE = 'check_violation';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM subject_type_field_configs c
            WHERE c.subject_type_id = p_subject_type_id
              AND c.enabled
              AND c.name_role <> 'none'
            GROUP BY c.name_role
            HAVING count(*) > 1
        ) THEN
            RAISE EXCEPTION 'active schema name roles must be unique'
                USING ERRCODE = 'unique_violation';
        END IF;
    END IF;

    FOR v_config IN
        SELECT c.id, c.enabled, c.default_value, d.field_type
        FROM subject_type_field_configs c
        JOIN subject_field_definitions d ON d.id = c.field_definition_id
        WHERE c.subject_type_id = p_subject_type_id
    LOOP
        IF v_config.field_type NOT IN ('single', 'multi', 'select') AND EXISTS (
            SELECT 1 FROM subject_field_options o WHERE o.field_config_id = v_config.id
        ) THEN
            RAISE EXCEPTION 'non-choice fields cannot have options'
                USING ERRCODE = 'check_violation';
        END IF;

        IF v_config.enabled AND v_config.field_type IN ('single', 'multi', 'select')
           AND NOT EXISTS (
               SELECT 1 FROM subject_field_options o
               WHERE o.field_config_id = v_config.id AND o.enabled
           ) THEN
            RAISE EXCEPTION 'enabled choice fields require an enabled option'
                USING ERRCODE = 'check_violation';
        END IF;

        IF v_config.default_value IS NULL OR v_config.default_value = 'null'::jsonb THEN
            CONTINUE;
        END IF;

        IF v_config.field_type IN ('text', 'textarea') THEN
            IF jsonb_typeof(v_config.default_value) <> 'string' THEN
                RAISE EXCEPTION 'text defaults must be strings'
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_config.field_type = 'number' THEN
            IF jsonb_typeof(v_config.default_value) <> 'number' THEN
                RAISE EXCEPTION 'number defaults must be JSON numbers'
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_config.field_type = 'date' THEN
            IF jsonb_typeof(v_config.default_value) <> 'string' THEN
                RAISE EXCEPTION 'date defaults must be strings'
                    USING ERRCODE = 'check_violation';
            END IF;
            v_text := v_config.default_value #>> '{}';
            IF v_text !~ '^\d{4}-\d{2}-\d{2}$'
               OR to_char(to_date(v_text, 'YYYY-MM-DD'), 'YYYY-MM-DD') <> v_text THEN
                RAISE EXCEPTION 'date defaults must use YYYY-MM-DD'
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_config.field_type = 'url' THEN
            IF jsonb_typeof(v_config.default_value) <> 'string'
               OR (v_config.default_value #>> '{}') !~* '^https?://[^[:space:]]+$' THEN
                RAISE EXCEPTION 'URL defaults must use HTTP or HTTPS'
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_config.field_type IN ('single', 'select') THEN
            IF jsonb_typeof(v_config.default_value) <> 'string'
               OR NOT EXISTS (
                   SELECT 1 FROM subject_field_options o
                   WHERE o.field_config_id = v_config.id
                     AND o.enabled
                     AND o.option_key = (v_config.default_value #>> '{}')
               ) THEN
                RAISE EXCEPTION 'choice default must reference an enabled option'
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_config.field_type = 'multi' THEN
            IF jsonb_typeof(v_config.default_value) <> 'array' THEN
                RAISE EXCEPTION 'multi defaults must be arrays'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM jsonb_array_elements(v_config.default_value) item
                WHERE jsonb_typeof(item) <> 'string'
            ) THEN
                RAISE EXCEPTION 'multi defaults must contain option keys'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF (
                SELECT count(*) FROM jsonb_array_elements_text(v_config.default_value)
            ) <> (
                SELECT count(DISTINCT item) FROM jsonb_array_elements_text(v_config.default_value) item
            ) OR EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(v_config.default_value) item
                WHERE NOT EXISTS (
                    SELECT 1 FROM subject_field_options o
                    WHERE o.field_config_id = v_config.id
                      AND o.enabled
                      AND o.option_key = item
                )
            ) THEN
                RAISE EXCEPTION 'multi defaults must reference unique enabled options'
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_config.field_type IN ('image', 'file') THEN
            RAISE EXCEPTION 'image and file defaults must be null'
                USING ERRCODE = 'check_violation';
        ELSE
            RAISE EXCEPTION 'unsupported field type'
                USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_validate_schema_from_type() RETURNS trigger AS $$
BEGIN
    PERFORM subjects_assert_schema(NEW.id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_validate_schema_from_config() RETURNS trigger AS $$
BEGIN
    PERFORM subjects_assert_schema(NEW.subject_type_id);
    IF TG_OP = 'UPDATE' AND OLD.subject_type_id IS DISTINCT FROM NEW.subject_type_id THEN
        PERFORM subjects_assert_schema(OLD.subject_type_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION subjects_validate_schema_from_option() RETURNS trigger AS $$
DECLARE
    v_subject_type_id uuid;
BEGIN
    SELECT subject_type_id INTO v_subject_type_id
    FROM subject_type_field_configs
    WHERE id = NEW.field_config_id;
    PERFORM subjects_assert_schema(v_subject_type_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER subjects_type_guard
BEFORE INSERT OR UPDATE ON subject_types
FOR EACH ROW EXECUTE FUNCTION subjects_guard_type();

CREATE TRIGGER subjects_definition_guard
BEFORE INSERT OR UPDATE ON subject_field_definitions
FOR EACH ROW EXECUTE FUNCTION subjects_guard_definition();

CREATE TRIGGER subjects_config_guard
BEFORE UPDATE ON subject_type_field_configs
FOR EACH ROW EXECUTE FUNCTION subjects_guard_config();

CREATE TRIGGER subjects_option_guard
BEFORE INSERT OR UPDATE ON subject_field_options
FOR EACH ROW EXECUTE FUNCTION subjects_guard_option();

CREATE TRIGGER subjects_type_no_delete
BEFORE DELETE ON subject_types
FOR EACH ROW EXECUTE FUNCTION subjects_reject_delete();

CREATE TRIGGER subjects_definition_no_delete
BEFORE DELETE ON subject_field_definitions
FOR EACH ROW EXECUTE FUNCTION subjects_reject_delete();

CREATE TRIGGER subjects_config_no_delete
BEFORE DELETE ON subject_type_field_configs
FOR EACH ROW EXECUTE FUNCTION subjects_reject_delete();

CREATE TRIGGER subjects_option_no_delete
BEFORE DELETE ON subject_field_options
FOR EACH ROW EXECUTE FUNCTION subjects_reject_delete();

CREATE CONSTRAINT TRIGGER subjects_type_schema_consistency
AFTER INSERT OR UPDATE ON subject_types
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_schema_from_type();

CREATE CONSTRAINT TRIGGER subjects_config_schema_consistency
AFTER INSERT OR UPDATE ON subject_type_field_configs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_schema_from_config();

CREATE CONSTRAINT TRIGGER subjects_option_schema_consistency
AFTER INSERT OR UPDATE ON subject_field_options
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION subjects_validate_schema_from_option();
"""


REMOVE_SQL = r"""
DROP TRIGGER IF EXISTS subjects_option_schema_consistency ON subject_field_options;
DROP TRIGGER IF EXISTS subjects_config_schema_consistency ON subject_type_field_configs;
DROP TRIGGER IF EXISTS subjects_type_schema_consistency ON subject_types;
DROP TRIGGER IF EXISTS subjects_option_no_delete ON subject_field_options;
DROP TRIGGER IF EXISTS subjects_config_no_delete ON subject_type_field_configs;
DROP TRIGGER IF EXISTS subjects_definition_no_delete ON subject_field_definitions;
DROP TRIGGER IF EXISTS subjects_type_no_delete ON subject_types;
DROP TRIGGER IF EXISTS subjects_option_guard ON subject_field_options;
DROP TRIGGER IF EXISTS subjects_config_guard ON subject_type_field_configs;
DROP TRIGGER IF EXISTS subjects_definition_guard ON subject_field_definitions;
DROP TRIGGER IF EXISTS subjects_type_guard ON subject_types;
DROP FUNCTION IF EXISTS subjects_validate_schema_from_option();
DROP FUNCTION IF EXISTS subjects_validate_schema_from_config();
DROP FUNCTION IF EXISTS subjects_validate_schema_from_type();
DROP FUNCTION IF EXISTS subjects_assert_schema(uuid);
DROP FUNCTION IF EXISTS subjects_guard_option();
DROP FUNCTION IF EXISTS subjects_guard_config();
DROP FUNCTION IF EXISTS subjects_guard_definition();
DROP FUNCTION IF EXISTS subjects_guard_type();
DROP FUNCTION IF EXISTS subjects_reject_delete();
DROP INDEX IF EXISTS subject_field_option_key_ci_unique;
DROP INDEX IF EXISTS subject_custom_field_key_ci_unique;
DROP INDEX IF EXISTS subject_common_field_key_ci_unique;
DROP INDEX IF EXISTS subject_type_key_ci_unique;
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(INSTALL_SQL)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REMOVE_SQL)


class Migration(migrations.Migration):
    dependencies = [("subjects", "0002_seed_builtin_subject_catalog")]

    operations = [migrations.RunPython(install_guards, remove_guards)]
