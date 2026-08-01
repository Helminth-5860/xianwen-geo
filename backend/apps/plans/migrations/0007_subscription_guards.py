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
    IF OLD.status IN ('closed', 'cancelled', 'activated')
       AND NEW.status IS DISTINCT FROM OLD.status
    THEN
        RAISE EXCEPTION 'PLAN_APPLICATION_TERMINAL'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'contacted'
       AND NEW.status NOT IN ('contacted', 'closed', 'cancelled', 'activated')
    THEN
        RAISE EXCEPTION 'PLAN_APPLICATION_STATE_CONFLICT'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'pending'
       AND NEW.status NOT IN ('pending', 'contacted', 'closed', 'cancelled', 'activated')
    THEN
        RAISE EXCEPTION 'PLAN_APPLICATION_STATE_CONFLICT'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'activated'
       AND (NEW.activated_at IS DISTINCT FROM OLD.activated_at
            OR NEW.activated_by_id IS DISTINCT FROM OLD.activated_by_id)
    THEN
        RAISE EXCEPTION 'PLAN_APPLICATION_ACTIVATION_IMMUTABLE'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION plans_guard_subscription() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SUBSCRIPTION_DELETE_FORBIDDEN'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.source_application_id IS DISTINCT FROM OLD.source_application_id
       OR NEW.plan_id IS DISTINCT FROM OLD.plan_id
       OR NEW.plan_version_id IS DISTINCT FROM OLD.plan_version_id
       OR NEW.plan_version_no IS DISTINCT FROM OLD.plan_version_no
       OR NEW.entitlement_snapshot IS DISTINCT FROM OLD.entitlement_snapshot
       OR NEW.entitlement_digest IS DISTINCT FROM OLD.entitlement_digest
       OR NEW.starts_at IS DISTINCT FROM OLD.starts_at
       OR NEW.ends_at IS DISTINCT FROM OLD.ends_at
       OR NEW.cycle_anchor_day IS DISTINCT FROM OLD.cycle_anchor_day
       OR NEW.is_trial IS DISTINCT FROM OLD.is_trial
       OR NEW.opened_by_id IS DISTINCT FROM OLD.opened_by_id
       OR NEW.opening_note IS DISTINCT FROM OLD.opening_note
       OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
       OR NEW.request_id IS DISTINCT FROM OLD.request_id
    THEN
        RAISE EXCEPTION 'SUBSCRIPTION_IMMUTABLE'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status IN ('expired', 'terminated') THEN
        RAISE EXCEPTION 'SUBSCRIPTION_TERMINAL'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.status NOT IN ('active', 'expired', 'terminated') THEN
        RAISE EXCEPTION 'SUBSCRIPTION_STATE_CONFLICT'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'SUBSCRIPTION_VERSION_CONFLICT'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER plans_subscription_guard
BEFORE UPDATE OR DELETE ON subscriptions
FOR EACH ROW EXECUTE FUNCTION plans_guard_subscription();

CREATE OR REPLACE FUNCTION plans_guard_subscription_event() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'SUBSCRIPTION_EVENT_IMMUTABLE'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER plans_subscription_event_append_only
BEFORE UPDATE OR DELETE ON subscription_events
FOR EACH ROW EXECUTE FUNCTION plans_guard_subscription_event();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS plans_subscription_event_append_only ON subscription_events;
DROP FUNCTION IF EXISTS plans_guard_subscription_event();
DROP TRIGGER IF EXISTS plans_subscription_guard ON subscriptions;
DROP FUNCTION IF EXISTS plans_guard_subscription();

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
"""


def create_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(CREATE_SQL)


def reverse_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("plans", "0006_subscription_subscriptionevent_and_more")]
    operations = [migrations.RunPython(create_guards, reverse_guards)]
