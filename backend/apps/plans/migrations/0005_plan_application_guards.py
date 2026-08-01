from django.db import migrations


CREATE_SQL = r"""
CREATE OR REPLACE FUNCTION plans_guard_application_binding() RETURNS trigger AS $$
BEGIN
    IF NEW.applicant_id IS DISTINCT FROM OLD.applicant_id
       OR NEW.plan_id IS DISTINCT FROM OLD.plan_id
       OR NEW.requested_plan_version_id IS DISTINCT FROM OLD.requested_plan_version_id
       OR NEW.requested_version_no IS DISTINCT FROM OLD.requested_version_no
       OR NEW.requested_config_digest IS DISTINCT FROM OLD.requested_config_digest
       OR NEW.public_plan_snapshot IS DISTINCT FROM OLD.public_plan_snapshot
       OR NEW.source IS DISTINCT FROM OLD.source
       OR NEW.idempotency_key_digest IS DISTINCT FROM OLD.idempotency_key_digest
       OR NEW.request_digest IS DISTINCT FROM OLD.request_digest
       OR NEW.request_id IS DISTINCT FROM OLD.request_id
    THEN
        RAISE EXCEPTION 'PLAN_APPLICATION_IMMUTABLE'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER plans_application_binding_immutable
BEFORE UPDATE ON plan_applications
FOR EACH ROW EXECUTE FUNCTION plans_guard_application_binding();

CREATE OR REPLACE FUNCTION plans_guard_application_event_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'PLAN_APPLICATION_EVENT_IMMUTABLE'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER plans_application_event_append_only
BEFORE UPDATE OR DELETE ON plan_application_events
FOR EACH ROW EXECUTE FUNCTION plans_guard_application_event_append_only();
"""

DROP_SQL = r"""
DROP TRIGGER IF EXISTS plans_application_event_append_only ON plan_application_events;
DROP FUNCTION IF EXISTS plans_guard_application_event_append_only();
DROP TRIGGER IF EXISTS plans_application_binding_immutable ON plan_applications;
DROP FUNCTION IF EXISTS plans_guard_application_binding();
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
    dependencies = [("plans", "0004_planapplication_planapplicationevent_and_more")]
    operations = [migrations.RunPython(create_triggers, drop_triggers)]
