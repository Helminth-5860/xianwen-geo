# ruff: noqa: E501
from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION keywords_subject_actor_allowed(
    p_subject_id uuid,
    p_actor_id uuid
) RETURNS boolean AS $$
    SELECT EXISTS (
        SELECT 1
          FROM subjects s
          JOIN users u ON u.id = p_actor_id
         WHERE s.id = p_subject_id
           AND (
               (s.tenant_id IS NULL AND s.user_id = p_actor_id)
               OR (s.tenant_id IS NOT NULL AND u.tenant_id = s.tenant_id)
           )
    );
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION keywords_distillation_job_guard() RETURNS trigger AS $$
DECLARE
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

    SELECT current_version_id INTO v_subject_current
      FROM subjects WHERE id = NEW.subject_id;
    SELECT user_id, subject_id, subject_version_id
      INTO v_input
      FROM keyword_set_versions WHERE id = NEW.input_keyword_set_version_id;
    SELECT user_id INTO v_subscription_user
      FROM subscriptions WHERE id = NEW.subscription_id;
    IF NOT keywords_subject_actor_allowed(NEW.subject_id, NEW.user_id)
       OR v_subject_current IS NULL
       OR (TG_OP = 'INSERT' AND v_subject_current <> NEW.subject_version_id)
       OR v_input.subject_id IS NULL
       OR NOT keywords_subject_actor_allowed(NEW.subject_id, v_input.user_id)
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

CREATE OR REPLACE FUNCTION keywords_distillation_workspace_guard() RETURNS trigger AS $$
DECLARE
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
    SELECT user_id, subject_id INTO v_input
      FROM keyword_set_versions WHERE id = NEW.draft_input_version_id;
    SELECT j.user_id, j.subject_id, j.input_keyword_set_version_id,
           r.applied_workspace_version
      INTO v_result
      FROM distillation_results r
      JOIN distillation_jobs j ON j.id = r.job_id
     WHERE r.id = NEW.draft_source_result_id;
    IF NOT keywords_subject_actor_allowed(NEW.subject_id, NEW.user_id)
       OR v_input.subject_id IS NULL
       OR NOT keywords_subject_actor_allowed(NEW.subject_id, v_input.user_id)
       OR v_input.subject_id <> NEW.subject_id
       OR v_result.subject_id IS NULL
       OR NOT keywords_subject_actor_allowed(NEW.subject_id, v_result.user_id)
       OR v_result.subject_id <> NEW.subject_id
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
           OR v_current.subject_id <> NEW.subject_id
           OR NOT keywords_subject_actor_allowed(NEW.subject_id, v_current.user_id) THEN
            RAISE EXCEPTION 'DISTILLATION_WORKSPACE_CURRENT_INVALID';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

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
    IF NOT FOUND
       OR v_workspace.subject_id <> NEW.subject_id
       OR NOT keywords_subject_actor_allowed(NEW.subject_id, v_workspace.user_id)
       OR v_input.subject_id <> NEW.subject_id
       OR NOT keywords_subject_actor_allowed(NEW.subject_id, v_input.user_id)
       OR v_input.subject_version_id <> NEW.subject_version_id
       OR v_result.subject_id <> NEW.subject_id
       OR NOT keywords_subject_actor_allowed(NEW.subject_id, v_result.user_id)
       OR v_result.input_keyword_set_version_id <> NEW.input_keyword_set_version_id
       OR NOT keywords_subject_actor_allowed(NEW.subject_id, NEW.user_id) THEN
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
"""


REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION keywords_distillation_job_guard() RETURNS trigger AS $$
DECLARE
    v_subject_user uuid;
    v_subject_current uuid;
    v_input record;
    v_subscription_user uuid;
    v_hold record;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'DISTILLATION_JOB_DELETE_FORBIDDEN'; END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.user_id, NEW.subject_id, NEW.subject_version_id,
            NEW.input_keyword_set_version_id, NEW.subscription_id, NEW.quota_hold_id,
            NEW.billing_mode, NEW.expected_workspace_version, NEW.input_subject_values,
            NEW.input_keywords, NEW.provider_key, NEW.model_key, NEW.adapter_version,
            NEW.prompt_version, NEW.input_digest, NEW.idempotency_key_version,
            NEW.idempotency_key_digest, NEW.request_digest, NEW.request_id,
            NEW.correlation_id, NEW.created_at)
        IS DISTINCT FROM ROW(OLD.user_id, OLD.subject_id, OLD.subject_version_id,
            OLD.input_keyword_set_version_id, OLD.subscription_id, OLD.quota_hold_id,
            OLD.billing_mode, OLD.expected_workspace_version, OLD.input_subject_values,
            OLD.input_keywords, OLD.provider_key, OLD.model_key, OLD.adapter_version,
            OLD.prompt_version, OLD.input_digest, OLD.idempotency_key_version,
            OLD.idempotency_key_digest, OLD.request_digest, OLD.request_id,
            OLD.correlation_id, OLD.created_at) THEN
            RAISE EXCEPTION 'DISTILLATION_JOB_FACTS_IMMUTABLE';
        END IF;
        IF OLD.status IN ('succeeded', 'failed', 'conflict', 'superseded') THEN
            RAISE EXCEPTION 'DISTILLATION_JOB_TERMINAL';
        END IF;
        IF NEW.version <> OLD.version + 1 OR NOT (
            (OLD.status = 'queued' AND NEW.status = 'running')
            OR (OLD.status = 'running' AND NEW.status IN (
                'running', 'retry_wait', 'succeeded', 'failed', 'conflict', 'superseded'))
            OR (OLD.status = 'retry_wait' AND NEW.status = 'running')) THEN
            RAISE EXCEPTION 'DISTILLATION_JOB_TRANSITION_INVALID';
        END IF;
    END IF;
    SELECT user_id, current_version_id INTO v_subject_user, v_subject_current
      FROM subjects WHERE id = NEW.subject_id;
    SELECT user_id, subject_id, subject_version_id INTO v_input
      FROM keyword_set_versions WHERE id = NEW.input_keyword_set_version_id;
    SELECT user_id INTO v_subscription_user FROM subscriptions WHERE id = NEW.subscription_id;
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
        SELECT user_id, quota_type, business_type, business_id, requested_amount,
               consumed_amount, released_amount, status
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
        IF NEW.quota_hold_id IS NOT NULL AND (
            v_hold.status <> 'settled' OR v_hold.consumed_amount <> 1
            OR v_hold.released_amount <> 0) THEN
            RAISE EXCEPTION 'DISTILLATION_SUCCESS_INVALID';
        END IF;
    ELSIF NEW.status IN ('failed', 'conflict', 'superseded') THEN
        IF NEW.quota_hold_id IS NOT NULL AND (
            v_hold.status <> 'settled' OR v_hold.consumed_amount <> 0
            OR v_hold.released_amount <> 1) THEN
            RAISE EXCEPTION 'DISTILLATION_RELEASE_INVALID';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION keywords_distillation_workspace_guard() RETURNS trigger AS $$
DECLARE
    v_subject_user uuid;
    v_input record;
    v_result record;
    v_current record;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'DISTILLATION_WORKSPACE_DELETE_FORBIDDEN'; END IF;
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
           r.applied_workspace_version INTO v_result
      FROM distillation_results r JOIN distillation_jobs j ON j.id = r.job_id
     WHERE r.id = NEW.draft_source_result_id;
    IF v_subject_user IS NULL OR v_subject_user <> NEW.user_id
       OR v_input.user_id <> NEW.user_id OR v_input.subject_id <> NEW.subject_id
       OR v_result.user_id <> NEW.user_id OR v_result.subject_id <> NEW.subject_id
       OR v_result.input_keyword_set_version_id <> NEW.draft_input_version_id
       OR v_result.applied_workspace_version > NEW.version
       OR ((TG_OP = 'INSERT' OR NEW.draft_source_result_id <> OLD.draft_source_result_id)
           AND v_result.applied_workspace_version <> NEW.version) THEN
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

DROP FUNCTION IF EXISTS keywords_subject_actor_allowed(uuid, uuid);
"""


class Migration(migrations.Migration):
    dependencies = [("keywords", "0011_align_keyword_asset_guards_with_tenant")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
