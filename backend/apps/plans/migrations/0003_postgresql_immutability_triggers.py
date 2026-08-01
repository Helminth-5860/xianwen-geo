from django.db import migrations


CREATE_SQL = r"""
CREATE OR REPLACE FUNCTION plans_guard_version_immutable() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status IN ('published', 'retired') THEN
            RAISE EXCEPTION 'PLAN_IMMUTABLE' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'retired' THEN
        RAISE EXCEPTION 'PLAN_IMMUTABLE' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'published' THEN
        IF NEW.status <> 'retired'
           OR NEW.plan_id IS DISTINCT FROM OLD.plan_id
           OR NEW.version_no IS DISTINCT FROM OLD.version_no
           OR NEW.valid_days IS DISTINCT FROM OLD.valid_days
           OR NEW.queue_priority IS DISTINCT FROM OLD.queue_priority
           OR NEW.effective_config IS DISTINCT FROM OLD.effective_config
           OR NEW.config_digest IS DISTINCT FROM OLD.config_digest
           OR NEW.snapshot_generated_at IS DISTINCT FROM OLD.snapshot_generated_at
           OR NEW.published_at IS DISTINCT FROM OLD.published_at
           OR NEW.published_by_id IS DISTINCT FROM OLD.published_by_id
        THEN
            RAISE EXCEPTION 'PLAN_IMMUTABLE' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER plans_version_immutable
BEFORE UPDATE OR DELETE ON plan_versions
FOR EACH ROW EXECUTE FUNCTION plans_guard_version_immutable();

CREATE OR REPLACE FUNCTION plans_guard_child_immutable() RETURNS trigger AS $$
DECLARE
    parent_id uuid;
    parent_status varchar;
BEGIN
    parent_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.plan_version_id ELSE NEW.plan_version_id END;
    SELECT status INTO parent_status FROM plan_versions WHERE id = parent_id;
    IF parent_status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'PLAN_IMMUTABLE' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER plans_limit_immutable
BEFORE INSERT OR UPDATE OR DELETE ON plan_limits
FOR EACH ROW EXECUTE FUNCTION plans_guard_child_immutable();

CREATE TRIGGER plans_model_permission_immutable
BEFORE INSERT OR UPDATE OR DELETE ON plan_model_permissions
FOR EACH ROW EXECUTE FUNCTION plans_guard_child_immutable();
"""

DROP_SQL = r"""
DROP TRIGGER IF EXISTS plans_model_permission_immutable ON plan_model_permissions;
DROP TRIGGER IF EXISTS plans_limit_immutable ON plan_limits;
DROP TRIGGER IF EXISTS plans_version_immutable ON plan_versions;
DROP FUNCTION IF EXISTS plans_guard_child_immutable();
DROP FUNCTION IF EXISTS plans_guard_version_immutable();
"""


def create_triggers(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(CREATE_SQL)


def drop_triggers(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(DROP_SQL)


class Migration(migrations.Migration):
    dependencies = [("plans", "0002_seed_limit_catalog")]
    operations = [migrations.RunPython(create_triggers, drop_triggers)]
