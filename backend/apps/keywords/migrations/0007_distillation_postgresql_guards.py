# ruff: noqa: E501
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
        IF NEW.quota_hold_id IS NOT NULL AND (
            v_hold.status <> 'settled' OR v_hold.consumed_amount <> 0
            OR v_hold.released_amount <> 1
        ) THEN
            RAISE EXCEPTION 'DISTILLATION_RELEASE_INVALID';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_distillation_job_guard_trg ON distillation_jobs;
CREATE TRIGGER keywords_distillation_job_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON distillation_jobs
FOR EACH ROW EXECUTE FUNCTION keywords_distillation_job_guard();

CREATE OR REPLACE FUNCTION keywords_distillation_result_guard() RETURNS trigger AS $$
DECLARE
    v_job record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'DISTILLATION_RESULT_IMMUTABLE';
    END IF;
    SELECT status, input_keywords, expected_workspace_version INTO v_job
      FROM distillation_jobs WHERE id = NEW.job_id;
    IF NOT FOUND OR v_job.status <> 'running'
       OR jsonb_typeof(NEW.output_snapshot) <> 'array'
       OR jsonb_array_length(NEW.output_snapshot) <> NEW.item_count
       OR NEW.item_count <> jsonb_array_length(v_job.input_keywords)
       OR NEW.applied_workspace_version <> v_job.expected_workspace_version + 1 THEN
        RAISE EXCEPTION 'DISTILLATION_RESULT_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_distillation_result_guard_trg ON distillation_results;
CREATE TRIGGER keywords_distillation_result_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON distillation_results
FOR EACH ROW EXECUTE FUNCTION keywords_distillation_result_guard();

CREATE OR REPLACE FUNCTION keywords_distillation_event_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'DISTILLATION_EVENT_IMMUTABLE';
    END IF;
    IF jsonb_typeof(NEW.safe_summary) <> 'object'
       OR NOT EXISTS (SELECT 1 FROM distillation_jobs WHERE id = NEW.job_id) THEN
        RAISE EXCEPTION 'DISTILLATION_EVENT_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_distillation_event_guard_trg ON distillation_events;
CREATE TRIGGER keywords_distillation_event_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON distillation_events
FOR EACH ROW EXECUTE FUNCTION keywords_distillation_event_guard();

CREATE OR REPLACE FUNCTION keywords_distillation_workspace_guard() RETURNS trigger AS $$
DECLARE
    v_subject_user uuid;
    v_input record;
    v_result record;
    v_current record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DISTILLATION_WORKSPACE_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.user_id, NEW.subject_id, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.user_id, OLD.subject_id, OLD.created_at)
           OR NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'DISTILLATION_WORKSPACE_TRANSITION_INVALID';
        END IF;
    END IF;
    SELECT user_id INTO v_subject_user FROM subjects WHERE id = NEW.subject_id;
    SELECT user_id, subject_id INTO v_input
      FROM keyword_set_versions WHERE id = NEW.draft_input_version_id;
    SELECT j.user_id, j.subject_id, j.input_keyword_set_version_id,
           r.applied_workspace_version
      INTO v_result
      FROM distillation_results r
      JOIN distillation_jobs j ON j.id = r.job_id
     WHERE r.id = NEW.draft_source_result_id;
    IF v_subject_user IS NULL OR v_subject_user <> NEW.user_id
       OR v_input.user_id <> NEW.user_id OR v_input.subject_id <> NEW.subject_id
       OR v_result.user_id <> NEW.user_id OR v_result.subject_id <> NEW.subject_id
       OR v_result.input_keyword_set_version_id <> NEW.draft_input_version_id
       OR v_result.applied_workspace_version > NEW.version
       OR (
           (TG_OP = 'INSERT' OR NEW.draft_source_result_id <> OLD.draft_source_result_id)
           AND v_result.applied_workspace_version <> NEW.version
       ) THEN
        RAISE EXCEPTION 'DISTILLATION_WORKSPACE_BINDING_INVALID';
    END IF;
    IF NEW.current_set_id IS NOT NULL THEN
        SELECT workspace_id, user_id, subject_id, version_no INTO v_current
          FROM distillation_sets WHERE id = NEW.current_set_id;
        IF NOT FOUND OR v_current.workspace_id <> NEW.id
           OR v_current.user_id <> NEW.user_id OR v_current.subject_id <> NEW.subject_id THEN
            RAISE EXCEPTION 'DISTILLATION_WORKSPACE_CURRENT_INVALID';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_distillation_workspace_guard_trg ON distillation_workspaces;
CREATE TRIGGER keywords_distillation_workspace_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON distillation_workspaces
FOR EACH ROW EXECUTE FUNCTION keywords_distillation_workspace_guard();

CREATE OR REPLACE FUNCTION keywords_distillation_draft_item_guard() RETURNS trigger AS $$
DECLARE
    v_input_version uuid;
    v_source_version uuid;
    v_canonical_version uuid;
BEGIN
    SELECT draft_input_version_id INTO v_input_version
      FROM distillation_workspaces WHERE id = NEW.workspace_id;
    SELECT keyword_set_version_id INTO v_source_version
      FROM keywords WHERE id = NEW.source_keyword_id;
    IF NEW.canonical_keyword_id IS NOT NULL THEN
        SELECT keyword_set_version_id INTO v_canonical_version
          FROM keywords WHERE id = NEW.canonical_keyword_id;
    END IF;
    IF v_input_version IS NULL OR v_source_version <> v_input_version
       OR (NEW.canonical_keyword_id IS NOT NULL AND v_canonical_version <> v_input_version)
       OR (NEW.ai_canonical_keyword_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM keywords
            WHERE id = NEW.ai_canonical_keyword_id
              AND keyword_set_version_id = v_input_version
       )) THEN
        RAISE EXCEPTION 'DISTILLATION_DRAFT_BINDING_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_distillation_draft_item_guard_trg ON distillation_draft_items;
CREATE TRIGGER keywords_distillation_draft_item_guard_trg
BEFORE INSERT OR UPDATE ON distillation_draft_items
FOR EACH ROW EXECUTE FUNCTION keywords_distillation_draft_item_guard();

CREATE OR REPLACE FUNCTION keywords_distillation_set_guard() RETURNS trigger AS $$
DECLARE
    v_workspace record;
    v_input record;
    v_result record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'DISTILLATION_SET_IMMUTABLE';
    END IF;
    SELECT user_id, subject_id INTO v_workspace
      FROM distillation_workspaces WHERE id = NEW.workspace_id;
    SELECT user_id, subject_id, subject_version_id INTO v_input
      FROM keyword_set_versions WHERE id = NEW.input_keyword_set_version_id;
    SELECT j.user_id, j.subject_id, j.input_keyword_set_version_id INTO v_result
      FROM distillation_results r
      JOIN distillation_jobs j ON j.id = r.job_id
     WHERE r.id = NEW.source_result_id;
    IF NOT FOUND OR v_workspace.user_id <> NEW.user_id
       OR v_workspace.subject_id <> NEW.subject_id
       OR v_input.user_id <> NEW.user_id OR v_input.subject_id <> NEW.subject_id
       OR v_input.subject_version_id <> NEW.subject_version_id
       OR v_result.user_id <> NEW.user_id OR v_result.subject_id <> NEW.subject_id
       OR v_result.input_keyword_set_version_id <> NEW.input_keyword_set_version_id THEN
        RAISE EXCEPTION 'DISTILLATION_SET_BINDING_INVALID';
    END IF;
    IF NEW.version_no <> COALESCE((
        SELECT max(version_no) + 1 FROM distillation_sets WHERE workspace_id = NEW.workspace_id
    ), 1) THEN
        RAISE EXCEPTION 'DISTILLATION_SET_VERSION_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_distillation_set_guard_trg ON distillation_sets;
CREATE TRIGGER keywords_distillation_set_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON distillation_sets
FOR EACH ROW EXECUTE FUNCTION keywords_distillation_set_guard();

CREATE OR REPLACE FUNCTION keywords_assert_distillation_set() RETURNS trigger AS $$
DECLARE
    v_set record;
BEGIN
    SELECT input_keyword_set_version_id, item_count INTO v_set
      FROM distillation_sets
     WHERE id = COALESCE(NEW.distillation_set_id, OLD.distillation_set_id);
    IF NOT FOUND OR (SELECT count(*) FROM distillation_items
                      WHERE distillation_set_id = COALESCE(NEW.distillation_set_id, OLD.distillation_set_id))
                    <> v_set.item_count
       OR EXISTS (
           SELECT 1 FROM distillation_items i
           JOIN keywords source ON source.id = i.source_keyword_id
           LEFT JOIN keywords canonical ON canonical.id = i.canonical_keyword_id
           LEFT JOIN keywords ai_canonical ON ai_canonical.id = i.ai_canonical_keyword_id
          WHERE i.distillation_set_id = COALESCE(NEW.distillation_set_id, OLD.distillation_set_id)
            AND (source.keyword_set_version_id <> v_set.input_keyword_set_version_id
                 OR (canonical.id IS NOT NULL AND canonical.keyword_set_version_id <> v_set.input_keyword_set_version_id)
                 OR (ai_canonical.id IS NOT NULL AND ai_canonical.keyword_set_version_id <> v_set.input_keyword_set_version_id))
       ) OR EXISTS (
           SELECT 1
             FROM distillation_items i
            WHERE i.distillation_set_id = COALESCE(NEW.distillation_set_id, OLD.distillation_set_id)
              AND i.action = 'merge'
            GROUP BY i.merge_group_key
           HAVING count(*) < 2 OR count(DISTINCT i.canonical_keyword_id) <> 1
              OR bool_and(i.canonical_keyword_id <> i.source_keyword_id)
       ) THEN
        RAISE EXCEPTION 'DISTILLATION_SET_ITEMS_INVALID';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION keywords_distillation_item_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'DISTILLATION_ITEM_IMMUTABLE';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS keywords_distillation_item_guard_trg ON distillation_items;
CREATE TRIGGER keywords_distillation_item_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON distillation_items
FOR EACH ROW EXECUTE FUNCTION keywords_distillation_item_guard();

DROP TRIGGER IF EXISTS keywords_distillation_set_items_guard_trg ON distillation_items;
CREATE CONSTRAINT TRIGGER keywords_distillation_set_items_guard_trg
AFTER INSERT ON distillation_items DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION keywords_assert_distillation_set();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS keywords_distillation_set_items_guard_trg ON distillation_items;
DROP TRIGGER IF EXISTS keywords_distillation_item_guard_trg ON distillation_items;
DROP TRIGGER IF EXISTS keywords_distillation_set_guard_trg ON distillation_sets;
DROP TRIGGER IF EXISTS keywords_distillation_draft_item_guard_trg ON distillation_draft_items;
DROP TRIGGER IF EXISTS keywords_distillation_workspace_guard_trg ON distillation_workspaces;
DROP TRIGGER IF EXISTS keywords_distillation_event_guard_trg ON distillation_events;
DROP TRIGGER IF EXISTS keywords_distillation_result_guard_trg ON distillation_results;
DROP TRIGGER IF EXISTS keywords_distillation_job_guard_trg ON distillation_jobs;
DROP FUNCTION IF EXISTS keywords_distillation_item_guard();
DROP FUNCTION IF EXISTS keywords_assert_distillation_set();
DROP FUNCTION IF EXISTS keywords_distillation_set_guard();
DROP FUNCTION IF EXISTS keywords_distillation_draft_item_guard();
DROP FUNCTION IF EXISTS keywords_distillation_workspace_guard();
DROP FUNCTION IF EXISTS keywords_distillation_event_guard();
DROP FUNCTION IF EXISTS keywords_distillation_result_guard();
DROP FUNCTION IF EXISTS keywords_distillation_job_guard();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("keywords", "0006_distillationjob_distillationevent_distillationresult_and_more"),
        ("quotas", "0011_remove_quotaaccount_quota_account_unique_batch_and_more"),
    ]
    operations = [migrations.RunPython(install, reverse)]
