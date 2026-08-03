from django.db import migrations


GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION plans_guard_subscription() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SUBSCRIPTION_DELETE_FORBIDDEN';
    END IF;
    IF ROW(
        NEW.user_id, NEW.source_type, NEW.source_application_id, NEW.source_change_id,
        NEW.plan_id, NEW.plan_version_id, NEW.plan_version_no,
        NEW.entitlement_snapshot, NEW.entitlement_digest,
        NEW.starts_at, NEW.ends_at, NEW.cycle_anchor_day, NEW.is_trial,
        NEW.opened_by_id, NEW.opening_note, NEW.activated_at, NEW.request_id
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.source_type, OLD.source_application_id, OLD.source_change_id,
        OLD.plan_id, OLD.plan_version_id, OLD.plan_version_no,
        OLD.entitlement_snapshot, OLD.entitlement_digest,
        OLD.starts_at, OLD.ends_at, OLD.cycle_anchor_day, OLD.is_trial,
        OLD.opened_by_id, OLD.opening_note, OLD.activated_at, OLD.request_id
    ) THEN
        RAISE EXCEPTION 'SUBSCRIPTION_IMMUTABLE';
    END IF;
    IF OLD.status IN ('expired', 'terminated') THEN
        RAISE EXCEPTION 'SUBSCRIPTION_TERMINAL';
    END IF;
    IF NEW.status NOT IN ('active', 'expired', 'terminated') THEN
        RAISE EXCEPTION 'SUBSCRIPTION_STATE_CONFLICT';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'SUBSCRIPTION_VERSION_CONFLICT';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION plans_guard_subscription_change() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;
    IF ROW(
        NEW.user_id, NEW.from_subscription_id, NEW.target_plan_id,
        NEW.target_plan_version_id, NEW.target_plan_version_no,
        NEW.target_entitlement_digest, NEW.change_type, NEW.quota_policy,
        NEW.effective_at, NEW.reason, NEW.unavailable_reason, NEW.requested_by_id,
        NEW.idempotency_key_version, NEW.idempotency_key_digest,
        NEW.idempotency_scope_digest, NEW.request_digest, NEW.request_id, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.from_subscription_id, OLD.target_plan_id,
        OLD.target_plan_version_id, OLD.target_plan_version_no,
        OLD.target_entitlement_digest, OLD.change_type, OLD.quota_policy,
        OLD.effective_at, OLD.reason, OLD.unavailable_reason, OLD.requested_by_id,
        OLD.idempotency_key_version, OLD.idempotency_key_digest,
        OLD.idempotency_scope_digest, OLD.request_digest, OLD.request_id, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_IMMUTABLE';
    END IF;
    IF OLD.status IN ('executed', 'cancelled') THEN
        RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_TERMINAL';
    END IF;
    IF OLD.status = 'scheduled' AND NEW.status NOT IN ('scheduled', 'executed', 'cancelled') THEN
        RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_STATE_CONFLICT';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_VERSION_CONFLICT';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION plans_guard_subscription_change_event() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_EVENT_IMMUTABLE';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION plans_validate_change_link() RETURNS trigger AS $$
DECLARE
    linked subscriptions%%ROWTYPE;
BEGIN
    IF NEW.status = 'executed' THEN
        SELECT * INTO linked FROM subscriptions WHERE source_change_id = NEW.id;
        IF NOT FOUND
           OR linked.source_type <> 'plan_change'
           OR linked.user_id <> NEW.user_id
           OR linked.plan_id <> NEW.target_plan_id
           OR linked.plan_version_id <> NEW.target_plan_version_id THEN
            RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_TARGET_MISMATCH';
        END IF;
    ELSIF EXISTS (SELECT 1 FROM subscriptions WHERE source_change_id = NEW.id) THEN
        RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_TARGET_PREMATURE';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS plans_subscription_guard ON subscriptions;
CREATE TRIGGER plans_subscription_guard
BEFORE UPDATE OR DELETE ON subscriptions
FOR EACH ROW EXECUTE FUNCTION plans_guard_subscription();

CREATE TRIGGER plans_subscription_change_guard
BEFORE UPDATE OR DELETE ON subscription_changes
FOR EACH ROW EXECUTE FUNCTION plans_guard_subscription_change();

CREATE TRIGGER plans_subscription_change_event_append_only
BEFORE UPDATE OR DELETE ON subscription_change_events
FOR EACH ROW EXECUTE FUNCTION plans_guard_subscription_change_event();

CREATE CONSTRAINT TRIGGER plans_subscription_change_link
AFTER INSERT OR UPDATE ON subscription_changes
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION plans_validate_change_link();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS plans_subscription_change_link ON subscription_changes;
DROP TRIGGER IF EXISTS plans_subscription_change_event_append_only ON subscription_change_events;
DROP TRIGGER IF EXISTS plans_subscription_change_guard ON subscription_changes;
DROP FUNCTION IF EXISTS plans_validate_change_link();
DROP FUNCTION IF EXISTS plans_guard_subscription_change_event();
DROP FUNCTION IF EXISTS plans_guard_subscription_change();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("plans", "0010_plan_change_guards")]
    operations = [migrations.RunPython(install, reverse)]
