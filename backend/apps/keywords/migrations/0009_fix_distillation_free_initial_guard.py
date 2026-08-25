from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION keywords_distillation_job_guard() RETURNS trigger AS $$
DECLARE
    v_subject_user uuid;
    v_subject_current uuid;
    v_input record;
    v_subscription_user uuid;
    v_hold record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DISTILLATION_JOB_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(
            NEW.user_id, NEW.subject_id, NEW.subject_version_id,
            NEW.input_keyword_set_version_id, NEW.subscription_id,
            NEW.quota_hold_id, NEW.billing_mode, NEW.expected_workspace_version,
            NEW.input_subject_values, NEW.input_keywords, NEW.provider_key,
            NEW.model_key, NEW.adapter_version, NEW.prompt_version,
            NEW.input_digest, NEW.idempotency_key_version,
            NEW.idempotency_key_digest, NEW.request_digest, NEW.request_id,
            NEW.correlation_id, NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.user_id, OLD.subject_id, OLD.subject_version_id,
            OLD.input_keyword_set_version_id, OLD.subscription_id,
            OLD.quota_hold_id, OLD.billing_mode, OLD.expected_workspace_version,
            OLD.input_subject_values, OLD.input_keywords, OLD.provider_key,
            OLD.model_key, OLD.adapter_version, OLD.prompt_version,
            OLD.input_digest, OLD.idempotency_key_version,
            OLD.idempotency_key_digest, OLD.request_digest, OLD.request_id,
            OLD.correlation_id, OLD.created_at
        ) THEN
            RAISE EXCEPTION 'DISTILLATION_JOB_FACTS_IMMUTABLE';
        END IF;
        IF OLD.status IN ('succeeded', 'failed', 'conflict', 'superseded') THEN
            RAISE EXCEPTION 'DISTILLATION_JOB_TERMINAL';
        END IF;
        IF NEW.version <> OLD.version + 1 OR NOT (
            (OLD.status = 'queued' AND NEW.status = 'running')
            OR (OLD.status = 'running' AND NEW.status IN (
                'running', 'retry_wait', 'succeeded', 'failed', 'conflict', 'superseded'
            ))
            OR (OLD.status = 'retry_wait' AND NEW.status = 'running')
        ) THEN
            RAISE EXCEPTION 'DISTILLATION_JOB_TRANSITION_INVALID';
        END IF;
    END IF;

    SELECT user_id, current_version_id
      INTO v_subject_user, v_subject_current
      FROM subjects WHERE id = NEW.subject_id;
    SELECT user_id, subject_id, subject_version_id
      INTO v_input
      FROM keyword_set_versions WHERE id = NEW.input_keyword_set_version_id;
    SELECT user_id INTO v_subscription_user
      FROM subscriptions WHERE id = NEW.subscription_id;
    IF v_subject_user IS NULL OR v_subject_user <> NEW.user_id
       OR (TG_OP = 'INSERT' AND v_subject_current <> NEW.subject_version_id)
       OR NOT FOUND OR v_input.user_id <> NEW.user_id
       OR v_input.subject_id <> NEW.subject_id
       OR v_input.subject_version_id <> NEW.subject_version_id
       OR v_subscription_user IS NULL OR v_subscription_user <> NEW.user_id
       OR jsonb_typeof(NEW.input_subject_values) <> 'object'
       OR jsonb_typeof(NEW.input_keywords) <> 'array'
       OR jsonb_array_length(NEW.input_keywords) < 1 THEN
        RAISE EXCEPTION 'DISTILLATION_JOB_BINDING_INVALID';
    END IF;
    IF NEW.quota_hold_id IS NOT NULL THEN
        SELECT user_id, quota_type, business_type, business_id,
               requested_amount, consumed_amount, released_amount, status
          INTO v_hold FROM quota_hold_groups WHERE id = NEW.quota_hold_id;
        IF NOT FOUND OR v_hold.user_id <> NEW.user_id
           OR v_hold.quota_type <> 'distillation_regenerations'
           OR v_hold.business_type <> 'keyword_distillation'
           OR v_hold.business_id <> NEW.id OR v_hold.requested_amount <> 1 THEN
            RAISE EXCEPTION 'DISTILLATION_HOLD_INVALID';
        END IF;
    END IF;
    IF NEW.status = 'succeeded' THEN
        IF NOT EXISTS (SELECT 1 FROM distillation_results WHERE job_id = NEW.id) THEN
            RAISE EXCEPTION 'DISTILLATION_SUCCESS_INVALID';
        END IF;
        IF NEW.quota_hold_id IS NOT NULL THEN
            IF v_hold.status <> 'settled' OR v_hold.consumed_amount <> 1
               OR v_hold.released_amount <> 0 THEN
                RAISE EXCEPTION 'DISTILLATION_SUCCESS_INVALID';
            END IF;
        END IF;
    ELSIF NEW.status IN ('failed', 'conflict', 'superseded') THEN
        IF NEW.quota_hold_id IS NOT NULL THEN
            IF v_hold.status <> 'settled' OR v_hold.consumed_amount <> 0
               OR v_hold.released_amount <> 1 THEN
                RAISE EXCEPTION 'DISTILLATION_RELEASE_INVALID';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


class Migration(migrations.Migration):
    dependencies = [("keywords", "0008_keyword_center_metadata_and_assets")]

    operations = [migrations.RunPython(install, migrations.RunPython.noop)]
