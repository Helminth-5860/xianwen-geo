# ruff: noqa: E501
from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION questions_generation_job_guard() RETURNS trigger AS $$
DECLARE
    v_hold record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'QUESTION_GENERATION_JOB_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(
            NEW.user_id, NEW.subject_id, NEW.subject_version_id,
            NEW.input_distillation_set_id, NEW.subscription_id, NEW.quota_hold_id,
            NEW.billing_mode, NEW.expected_workspace_version, NEW.question_limit,
            NEW.input_subject_values, NEW.input_keywords, NEW.input_categories,
            NEW.input_tags, NEW.provider_key, NEW.model_key, NEW.adapter_version,
            NEW.prompt_version, NEW.input_digest, NEW.idempotency_key_version,
            NEW.idempotency_key_digest, NEW.request_digest, NEW.request_id,
            NEW.correlation_id, NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.user_id, OLD.subject_id, OLD.subject_version_id,
            OLD.input_distillation_set_id, OLD.subscription_id, OLD.quota_hold_id,
            OLD.billing_mode, OLD.expected_workspace_version, OLD.question_limit,
            OLD.input_subject_values, OLD.input_keywords, OLD.input_categories,
            OLD.input_tags, OLD.provider_key, OLD.model_key, OLD.adapter_version,
            OLD.prompt_version, OLD.input_digest, OLD.idempotency_key_version,
            OLD.idempotency_key_digest, OLD.request_digest, OLD.request_id,
            OLD.correlation_id, OLD.created_at
        ) THEN
            RAISE EXCEPTION 'QUESTION_GENERATION_JOB_FACTS_IMMUTABLE';
        END IF;
        IF OLD.status IN ('succeeded', 'failed', 'conflict', 'superseded') THEN
            RAISE EXCEPTION 'QUESTION_GENERATION_JOB_TERMINAL';
        END IF;
        IF NEW.version <> OLD.version + 1 OR NOT (
            (OLD.status = 'queued' AND NEW.status = 'running')
            OR (OLD.status = 'running' AND NEW.status IN (
                'running', 'retry_wait', 'succeeded', 'failed', 'conflict', 'superseded'
            ))
            OR (OLD.status = 'retry_wait' AND NEW.status = 'running')
        ) THEN
            RAISE EXCEPTION 'QUESTION_GENERATION_JOB_TRANSITION_INVALID';
        END IF;
    END IF;
    IF jsonb_typeof(NEW.input_subject_values) <> 'object'
       OR jsonb_typeof(NEW.input_keywords) <> 'array'
       OR jsonb_typeof(NEW.input_categories) <> 'array'
       OR jsonb_typeof(NEW.input_tags) <> 'array'
       OR jsonb_array_length(NEW.input_keywords) < 1
       OR jsonb_array_length(NEW.input_categories) < 1 THEN
        RAISE EXCEPTION 'QUESTION_GENERATION_INPUT_INVALID';
    END IF;
    IF NEW.quota_hold_id IS NOT NULL THEN
        SELECT user_id, quota_type, business_type, business_id, requested_amount,
               consumed_amount, released_amount, status
          INTO v_hold FROM quota_hold_groups WHERE id = NEW.quota_hold_id;
        IF NOT FOUND OR v_hold.user_id <> NEW.user_id
           OR v_hold.quota_type <> 'question_bank_regenerations'
           OR v_hold.business_type <> 'question_bank_generation'
           OR v_hold.business_id <> NEW.id OR v_hold.requested_amount <> 1 THEN
            RAISE EXCEPTION 'QUESTION_GENERATION_HOLD_INVALID';
        END IF;
    END IF;
    IF NEW.status = 'succeeded' THEN
        IF NOT EXISTS (SELECT 1 FROM question_generation_results WHERE job_id = NEW.id) THEN
            RAISE EXCEPTION 'QUESTION_GENERATION_SUCCESS_INVALID';
        END IF;
        IF NEW.quota_hold_id IS NOT NULL THEN
            IF v_hold.status <> 'settled' OR v_hold.consumed_amount <> 1
               OR v_hold.released_amount <> 0 THEN
                RAISE EXCEPTION 'QUESTION_GENERATION_SUCCESS_INVALID';
            END IF;
        END IF;
    ELSIF NEW.status IN ('failed', 'conflict', 'superseded') THEN
        IF NEW.quota_hold_id IS NOT NULL THEN
            IF v_hold.status <> 'settled' OR v_hold.consumed_amount <> 0
               OR v_hold.released_amount <> 1 THEN
                RAISE EXCEPTION 'QUESTION_GENERATION_RELEASE_INVALID';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER questions_generation_job_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON question_generation_jobs
FOR EACH ROW EXECUTE FUNCTION questions_generation_job_guard();

CREATE OR REPLACE FUNCTION questions_generation_result_guard() RETURNS trigger AS $$
DECLARE
    v_job record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'QUESTION_GENERATION_RESULT_IMMUTABLE';
    END IF;
    SELECT status, question_limit, expected_workspace_version INTO v_job
      FROM question_generation_jobs WHERE id = NEW.job_id;
    IF NOT FOUND OR v_job.status <> 'running'
       OR jsonb_typeof(NEW.output_snapshot) <> 'array'
       OR jsonb_array_length(NEW.output_snapshot) <> NEW.item_count
       OR NEW.item_count < 1 OR NEW.item_count > v_job.question_limit
       OR NEW.applied_workspace_version <> v_job.expected_workspace_version + 1 THEN
        RAISE EXCEPTION 'QUESTION_GENERATION_RESULT_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER questions_generation_result_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON question_generation_results
FOR EACH ROW EXECUTE FUNCTION questions_generation_result_guard();

CREATE OR REPLACE FUNCTION questions_append_only_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'QUESTION_BANK_HISTORY_IMMUTABLE';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER questions_generation_event_guard_trg
BEFORE UPDATE OR DELETE ON question_generation_events
FOR EACH ROW EXECUTE FUNCTION questions_append_only_guard();
CREATE TRIGGER questions_question_guard_trg
BEFORE UPDATE OR DELETE ON questions
FOR EACH ROW EXECUTE FUNCTION questions_append_only_guard();
CREATE TRIGGER questions_tag_link_guard_trg
BEFORE UPDATE OR DELETE ON question_tag_links
FOR EACH ROW EXECUTE FUNCTION questions_append_only_guard();
CREATE TRIGGER questions_keyword_link_guard_trg
BEFORE UPDATE OR DELETE ON question_keyword_links
FOR EACH ROW EXECUTE FUNCTION questions_append_only_guard();

CREATE OR REPLACE FUNCTION questions_workspace_guard() RETURNS trigger AS $$
DECLARE
    v_current record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'QUESTION_BANK_WORKSPACE_DELETE_FORBIDDEN';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        ROW(NEW.user_id, NEW.subject_id, NEW.created_at)
        IS DISTINCT FROM ROW(OLD.user_id, OLD.subject_id, OLD.created_at)
        OR NEW.version <> OLD.version + 1
    ) THEN
        RAISE EXCEPTION 'QUESTION_BANK_WORKSPACE_TRANSITION_INVALID';
    END IF;
    IF NEW.current_version_id IS NOT NULL THEN
        SELECT workspace_id, user_id, subject_id, version_no INTO v_current
          FROM question_bank_versions WHERE id = NEW.current_version_id;
        IF NOT FOUND OR v_current.workspace_id <> NEW.id
           OR v_current.user_id <> NEW.user_id OR v_current.subject_id <> NEW.subject_id
           OR v_current.version_no <> (
               SELECT max(version_no) FROM question_bank_versions WHERE workspace_id = NEW.id
           ) THEN
            RAISE EXCEPTION 'QUESTION_BANK_CURRENT_INVALID';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER questions_workspace_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON question_bank_workspaces
FOR EACH ROW EXECUTE FUNCTION questions_workspace_guard();

CREATE OR REPLACE FUNCTION questions_version_guard() RETURNS trigger AS $$
DECLARE
    v_workspace record;
    v_distillation record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'QUESTION_BANK_VERSION_IMMUTABLE';
    END IF;
    SELECT user_id, subject_id, draft_subject_version_id, draft_distillation_set_id
      INTO v_workspace FROM question_bank_workspaces WHERE id = NEW.workspace_id;
    SELECT user_id, subject_id, subject_version_id INTO v_distillation
      FROM distillation_sets WHERE id = NEW.distillation_set_id;
    IF NOT FOUND OR v_workspace.user_id <> NEW.user_id
       OR v_workspace.subject_id <> NEW.subject_id
       OR v_distillation.user_id <> NEW.user_id
       OR v_distillation.subject_id <> NEW.subject_id
       OR v_distillation.subject_version_id <> NEW.subject_version_id
       OR v_workspace.draft_subject_version_id <> NEW.subject_version_id
       OR v_workspace.draft_distillation_set_id <> NEW.distillation_set_id
       OR NEW.version_no <> COALESCE((
           SELECT max(version_no) + 1 FROM question_bank_versions
            WHERE workspace_id = NEW.workspace_id
       ), 1) THEN
        RAISE EXCEPTION 'QUESTION_BANK_VERSION_BINDING_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER questions_version_guard_trg
BEFORE INSERT OR UPDATE OR DELETE ON question_bank_versions
FOR EACH ROW EXECUTE FUNCTION questions_version_guard();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS questions_version_guard_trg ON question_bank_versions;
DROP TRIGGER IF EXISTS questions_workspace_guard_trg ON question_bank_workspaces;
DROP TRIGGER IF EXISTS questions_keyword_link_guard_trg ON question_keyword_links;
DROP TRIGGER IF EXISTS questions_tag_link_guard_trg ON question_tag_links;
DROP TRIGGER IF EXISTS questions_question_guard_trg ON questions;
DROP TRIGGER IF EXISTS questions_generation_event_guard_trg ON question_generation_events;
DROP TRIGGER IF EXISTS questions_generation_result_guard_trg ON question_generation_results;
DROP TRIGGER IF EXISTS questions_generation_job_guard_trg ON question_generation_jobs;
DROP FUNCTION IF EXISTS questions_version_guard();
DROP FUNCTION IF EXISTS questions_workspace_guard();
DROP FUNCTION IF EXISTS questions_append_only_guard();
DROP FUNCTION IF EXISTS questions_generation_result_guard();
DROP FUNCTION IF EXISTS questions_generation_job_guard();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("questions", "0004_questionbankversion_question_questionbankworkspace_and_more")
    ]
    operations = [migrations.RunPython(install, reverse)]
