from django.db import migrations


REBUILD_CHANGE_GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION plans_guard_subscription_change() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'SUBSCRIPTION_CHANGE_DELETE_FORBIDDEN'; END IF;
    IF TG_OP = 'INSERT' THEN RETURN NEW; END IF;
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
"""


def rebuild_change_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REBUILD_CHANGE_GUARD_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0024_retire_multi_admin_approval"),
        ("plans", "0014_remove_renewal_approval_binding"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="subscriptionchange",
            name="source_approval",
        ),
        migrations.RunPython(rebuild_change_guard, migrations.RunPython.noop),
    ]
