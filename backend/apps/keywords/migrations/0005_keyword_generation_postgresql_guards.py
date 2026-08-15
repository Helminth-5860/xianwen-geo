from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION keywords_generation_job_guard() RETURNS trigger AS $$
DECLARE
    v_subject_user uuid;
    v_subject_current uuid;
    v_subject_version_subject uuid;
    v_set record;
    v_subscription_user uuid;
    v_hold record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'KEYWORD_GENERATION_JOB_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(
            NEW.user_id, NEW.subject_id, NEW.subject_version_id,
            NEW.keyword_set_id, NEW.subscription_id, NEW.quota_hold_id,
            NEW.billing_mode, NEW.expected_keyword_set_version,
            NEW.target_count, NEW.include_short, NEW.include_long_tail,
            NEW.include_regional, NEW.regions, NEW.input_subject_values,
            NEW.historical_exclusions, NEW.provider_key, NEW.model_key,
            NEW.adapter_version, NEW.prompt_version, NEW.input_digest,
            NEW.idempotency_key_version, NEW.idempotency_key_digest,
            NEW.request_digest, NEW.request_id, NEW.correlation_id,
            NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.user_id, OLD.subject_id, OLD.subject_version_id,
            OLD.keyword_set_id, OLD.subscription_id, OLD.quota_hold_id,
            OLD.billing_mode, OLD.expected_keyword_set_version,
            OLD.target_count, OLD.include_short, OLD.include_long_tail,
            OLD.include_regional, OLD.regions, OLD.input_subject_values,
            OLD.historical_exclusions, OLD.provider_key, OLD.model_key,
            OLD.adapter_version, OLD.prompt_version, OLD.input_digest,
            OLD.idempotency_key_version, OLD.idempotency_key_digest,
            OLD.request_digest, OLD.request_id, OLD.correlation_id,
            OLD.created_at
        ) THEN
            RAISE EXCEPTION 'KEYWORD_GENERATION_FACTS_IMMUTABLE';
        END IF;
        IF OLD.status IN ('succeeded', 'failed', 'conflict', 'superseded') THEN
            RAISE EXCEPTION 'KEYWORD_GENERATION_TERMINAL';
        END IF;
        IF NEW.version <> OLD.version + 1 OR NOT (
            (OLD.status = 'queued' AND NEW.status = 'running')
            OR (OLD.status = 'running' AND NEW.status IN (
                'running', 'retry_wait', 'succeeded', 'failed', 'conflict', 'superseded'
            ))
            OR (OLD.status = 'retry_wait' AND NEW.status = 'running')
        ) THEN
            RAISE EXCEPTION 'KEYWORD_GENERATION_TRANSITION_INVALID';
        END IF;
    END IF;

    SELECT user_id, current_version_id
      INTO v_subject_user, v_subject_current
      FROM subjects WHERE id = NEW.subject_id;
    SELECT subject_id INTO v_subject_version_subject
      FROM subject_versions WHERE id = NEW.subject_version_id;
    SELECT user_id INTO v_subscription_user
      FROM subscriptions WHERE id = NEW.subscription_id;
    IF v_subject_user IS NULL OR v_subject_user <> NEW.user_id
       OR (
           TG_OP = 'INSERT'
           AND (v_subject_current IS NULL OR v_subject_current <> NEW.subject_version_id)
       )
       OR v_subject_version_subject IS NULL
       OR v_subject_version_subject <> NEW.subject_id
       OR v_subscription_user IS NULL OR v_subscription_user <> NEW.user_id THEN
        RAISE EXCEPTION 'KEYWORD_GENERATION_BINDING_INVALID';
    END IF;
    IF NEW.keyword_set_id IS NULL THEN
        IF NEW.expected_keyword_set_version <> 0 THEN
            RAISE EXCEPTION 'KEYWORD_GENERATION_SET_VERSION_INVALID';
        END IF;
    ELSE
        SELECT user_id, subject_id, version INTO v_set
          FROM keyword_sets WHERE id = NEW.keyword_set_id;
        IF NOT FOUND OR v_set.user_id <> NEW.user_id
           OR v_set.subject_id <> NEW.subject_id
           OR (
               TG_OP = 'INSERT'
               AND v_set.version <> NEW.expected_keyword_set_version
           ) THEN
            RAISE EXCEPTION 'KEYWORD_GENERATION_SET_VERSION_INVALID';
        END IF;
    END IF;
    IF NEW.quota_hold_id IS NOT NULL THEN
        SELECT user_id, quota_type, business_type, business_id,
               requested_amount, consumed_amount, released_amount, status
          INTO v_hold FROM quota_hold_groups WHERE id = NEW.quota_hold_id;
        IF NOT FOUND OR v_hold.user_id <> NEW.user_id
           OR v_hold.quota_type <> 'keyword_regenerations'
           OR v_hold.business_type <> 'keyword_generation'
           OR v_hold.business_id <> NEW.id OR v_hold.requested_amount <> 1 THEN
            RAISE EXCEPTION 'KEYWORD_GENERATION_HOLD_INVALID';
        END IF;
    END IF;
    IF NEW.status = 'succeeded' THEN
        IF NOT EXISTS (
            SELECT 1 FROM keyword_generation_results WHERE job_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'KEYWORD_GENERATION_SUCCESS_INVALID';
        END IF;
        IF NEW.quota_hold_id IS NOT NULL THEN
            IF v_hold.status <> 'settled' OR v_hold.consumed_amount <> 1
               OR v_hold.released_amount <> 0 THEN
                RAISE EXCEPTION 'KEYWORD_GENERATION_SUCCESS_INVALID';
            END IF;
        END IF;
    ELSIF NEW.status IN ('failed', 'conflict', 'superseded') THEN
        IF NEW.quota_hold_id IS NOT NULL THEN
            IF v_hold.status <> 'settled' OR v_hold.consumed_amount <> 0
               OR v_hold.released_amount <> 1 THEN
                RAISE EXCEPTION 'KEYWORD_GENERATION_RELEASE_INVALID';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_generation_job_guard_trg
ON keyword_generation_jobs;
CREATE TRIGGER keywords_generation_job_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON keyword_generation_jobs
FOR EACH ROW EXECUTE FUNCTION keywords_generation_job_guard();

CREATE OR REPLACE FUNCTION keywords_generation_result_guard() RETURNS trigger AS $$
DECLARE
    v_job record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'KEYWORD_GENERATION_RESULT_IMMUTABLE';
    END IF;
    SELECT status, target_count, expected_keyword_set_version INTO v_job
      FROM keyword_generation_jobs WHERE id = NEW.job_id;
    IF NOT FOUND OR v_job.status <> 'running'
       OR jsonb_typeof(NEW.output_snapshot) <> 'array'
       OR jsonb_array_length(NEW.output_snapshot) <> NEW.item_count
       OR NEW.item_count <> v_job.target_count
       OR NEW.applied_keyword_set_version
          <> v_job.expected_keyword_set_version + 1 THEN
        RAISE EXCEPTION 'KEYWORD_GENERATION_RESULT_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_generation_result_guard_trg
ON keyword_generation_results;
CREATE TRIGGER keywords_generation_result_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON keyword_generation_results
FOR EACH ROW EXECUTE FUNCTION keywords_generation_result_guard();

CREATE OR REPLACE FUNCTION keywords_generation_event_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'KEYWORD_GENERATION_EVENT_IMMUTABLE';
    END IF;
    IF jsonb_typeof(NEW.safe_summary) <> 'object'
       OR NOT EXISTS (
           SELECT 1 FROM keyword_generation_jobs WHERE id = NEW.job_id
       ) THEN
        RAISE EXCEPTION 'KEYWORD_GENERATION_EVENT_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_generation_event_guard_trg
ON keyword_generation_events;
CREATE TRIGGER keywords_generation_event_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON keyword_generation_events
FOR EACH ROW EXECUTE FUNCTION keywords_generation_event_guard();

CREATE OR REPLACE FUNCTION keywords_assert_base_graph() RETURNS trigger AS $$
DECLARE
    v_cycle boolean;
BEGIN
    IF EXISTS (
        SELECT 1
          FROM keywords item
          JOIN keywords base ON base.id = item.base_keyword_id
         WHERE item.keyword_set_version_id = NEW.keyword_set_version_id
           AND (
               item.id = item.base_keyword_id
               OR base.keyword_set_version_id <> item.keyword_set_version_id
           )
    ) THEN
        RAISE EXCEPTION 'KEYWORD_BASE_BINDING_INVALID';
    END IF;
    WITH RECURSIVE walk(origin, current_id, next_id, path, cycle) AS (
        SELECT id, id, base_keyword_id, ARRAY[id], false
          FROM keywords
         WHERE keyword_set_version_id = NEW.keyword_set_version_id
        UNION ALL
        SELECT walk.origin, base.id, base.base_keyword_id,
               walk.path || base.id, base.id = ANY(walk.path)
          FROM walk
          JOIN keywords base ON base.id = walk.next_id
         WHERE walk.next_id IS NOT NULL AND NOT walk.cycle
    )
    SELECT COALESCE(bool_or(cycle), false) INTO v_cycle FROM walk;
    IF v_cycle THEN
        RAISE EXCEPTION 'KEYWORD_BASE_CYCLE_INVALID';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_base_graph_guard_trg ON keywords;
CREATE CONSTRAINT TRIGGER keywords_base_graph_guard_trg
AFTER INSERT ON keywords
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION keywords_assert_base_graph();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS keywords_base_graph_guard_trg ON keywords;
DROP TRIGGER IF EXISTS keywords_generation_event_guard_trg
ON keyword_generation_events;
DROP TRIGGER IF EXISTS keywords_generation_result_guard_trg
ON keyword_generation_results;
DROP TRIGGER IF EXISTS keywords_generation_job_guard_trg
ON keyword_generation_jobs;
DROP FUNCTION IF EXISTS keywords_assert_base_graph();
DROP FUNCTION IF EXISTS keywords_generation_event_guard();
DROP FUNCTION IF EXISTS keywords_generation_result_guard();
DROP FUNCTION IF EXISTS keywords_generation_job_guard();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("keywords", "0004_keywordgenerationevent_keyword_generation_event_type_valid"),
        ("quotas", "0011_remove_quotaaccount_quota_account_unique_batch_and_more"),
    ]
    operations = [migrations.RunPython(install, reverse)]
