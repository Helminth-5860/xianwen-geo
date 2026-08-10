from django.db import migrations


GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION plans_guard_subscription() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'SUBSCRIPTION_DELETE_FORBIDDEN'; END IF;
    IF ROW(
        NEW.user_id, NEW.source_type, NEW.source_application_id, NEW.source_change_id,
        NEW.plan_id, NEW.plan_version_id, NEW.plan_version_no,
        NEW.entitlement_snapshot, NEW.entitlement_digest,
        NEW.starts_at, NEW.ends_at, NEW.cycle_anchor_day, NEW.cycle_anchor_time,
        NEW.is_trial, NEW.opened_by_id, NEW.opening_note, NEW.activated_at, NEW.request_id
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.source_type, OLD.source_application_id, OLD.source_change_id,
        OLD.plan_id, OLD.plan_version_id, OLD.plan_version_no,
        OLD.entitlement_snapshot, OLD.entitlement_digest,
        OLD.starts_at, OLD.ends_at, OLD.cycle_anchor_day, OLD.cycle_anchor_time,
        OLD.is_trial, OLD.opened_by_id, OLD.opening_note, OLD.activated_at, OLD.request_id
    ) THEN RAISE EXCEPTION 'SUBSCRIPTION_IMMUTABLE'; END IF;
    IF OLD.status IN ('expired', 'terminated') THEN RAISE EXCEPTION 'SUBSCRIPTION_TERMINAL'; END IF;
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
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_DELETE_FORBIDDEN'; END IF;
    IF TG_OP = 'INSERT' THEN RETURN NEW; END IF;
    IF ROW(
        NEW.user_id, NEW.from_subscription_id, NEW.target_plan_id,
        NEW.target_plan_version_id, NEW.target_plan_version_no,
        NEW.target_entitlement_digest, NEW.change_type, NEW.quota_policy,
        NEW.effective_at, NEW.reason, NEW.unavailable_reason, NEW.requested_by_id,
        NEW.source_approval_id, NEW.idempotency_key_version, NEW.idempotency_key_digest,
        NEW.idempotency_scope_digest, NEW.request_digest, NEW.request_id, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.user_id, OLD.from_subscription_id, OLD.target_plan_id,
        OLD.target_plan_version_id, OLD.target_plan_version_no,
        OLD.target_entitlement_digest, OLD.change_type, OLD.quota_policy,
        OLD.effective_at, OLD.reason, OLD.unavailable_reason, OLD.requested_by_id,
        OLD.source_approval_id, OLD.idempotency_key_version, OLD.idempotency_key_digest,
        OLD.idempotency_scope_digest, OLD.request_digest, OLD.request_id, OLD.created_at
    ) THEN RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_IMMUTABLE'; END IF;
    IF OLD.status IN ('executed', 'cancelled', 'failed') THEN
        RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_TERMINAL';
    END IF;
    IF OLD.status = 'scheduled' AND NEW.status NOT IN ('scheduled', 'executed', 'cancelled', 'failed') THEN
        RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_STATE_CONFLICT';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_VERSION_CONFLICT';
    END IF;
    IF NEW.retry_count < OLD.retry_count THEN RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_RETRY_REGRESSION'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION plans_validate_renewal_approval() RETURNS trigger AS $$
DECLARE approval approval_requests%%ROWTYPE;
BEGIN
    IF NEW.change_type = 'renewal' AND NEW.status IN ('scheduled', 'executed', 'failed') THEN
        SELECT * INTO approval FROM approval_requests WHERE id = NEW.source_approval_id;
        IF NOT FOUND OR approval.action_key <> 'subscription.change'
           OR approval.status <> 'executed'
           OR approval.execution_result->>'change_id' <> NEW.id::text THEN
            RAISE EXCEPTION 'RENEWAL_APPROVAL_BINDING_INVALID';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS plans_subscription_guard ON subscriptions;
CREATE TRIGGER plans_subscription_guard
BEFORE UPDATE OR DELETE ON subscriptions
FOR EACH ROW EXECUTE FUNCTION plans_guard_subscription();

DROP TRIGGER IF EXISTS plans_subscription_change_guard ON subscription_changes;
CREATE TRIGGER plans_subscription_change_guard
BEFORE UPDATE OR DELETE ON subscription_changes
FOR EACH ROW EXECUTE FUNCTION plans_guard_subscription_change();

CREATE CONSTRAINT TRIGGER plans_renewal_approval_binding
AFTER INSERT OR UPDATE ON subscription_changes
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION plans_validate_renewal_approval();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS plans_renewal_approval_binding ON subscription_changes;
DROP FUNCTION IF EXISTS plans_validate_renewal_approval();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("plans", "0012_remove_subscriptionchange_sub_change_status_valid_and_more")]
    operations = [migrations.RunPython(install, reverse)]
