-- 显问 GEO V1 数据库结构启动骨架
-- 说明：本文件用于明确核心表、唯一约束和不可变流水，不替代 Django migrations。
-- 生产环境必须通过 Django migration 创建和变更表。

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    phone varchar(32) NOT NULL UNIQUE,
    nickname varchar(100) NOT NULL,
    password_hash varchar(255) NOT NULL,
    approval_status varchar(32) NOT NULL DEFAULT 'pending',
    account_status varchar(32) NOT NULL DEFAULT 'active',
    approval_reason text,
    approved_at timestamptz,
    approved_by_id uuid,
    trial_ever_granted boolean NOT NULL DEFAULT false,
    cancel_requested_at timestamptz,
    cancel_effective_at timestamptz,
    last_login_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (approval_status IN ('pending','approved','rejected')),
    CHECK (account_status IN ('active','frozen','cancel_pending','cancelled'))
);

CREATE TABLE admin_roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(100) NOT NULL UNIQUE,
    description text NOT NULL DEFAULT '',
    customer_scope varchar(32) NOT NULL DEFAULT 'own',
    require_sms_2fa boolean NOT NULL DEFAULT false,
    ip_allowlist_enabled boolean NOT NULL DEFAULT false,
    status varchar(32) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE admin_users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    phone varchar(32) NOT NULL UNIQUE,
    display_name varchar(100) NOT NULL,
    password_hash varchar(255) NOT NULL,
    role_id uuid REFERENCES admin_roles(id),
    is_super_admin boolean NOT NULL DEFAULT false,
    status varchar(32) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE permissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    permission_key varchar(150) NOT NULL UNIQUE,
    description varchar(255) NOT NULL DEFAULT ''
);

CREATE TABLE admin_role_permissions (
    role_id uuid NOT NULL REFERENCES admin_roles(id) ON DELETE CASCADE,
    permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE plans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_key varchar(100) NOT NULL UNIQUE,
    name varchar(150) NOT NULL,
    description text NOT NULL DEFAULT '',
    display_price numeric(12,2),
    is_trial boolean NOT NULL DEFAULT false,
    status varchar(32) NOT NULL DEFAULT 'draft',
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE plan_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id uuid NOT NULL REFERENCES plans(id),
    version_no integer NOT NULL,
    valid_days integer NOT NULL,
    queue_priority integer NOT NULL DEFAULT 0,
    entitlement_snapshot jsonb NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'draft',
    published_at timestamptz,
    published_by_id uuid REFERENCES admin_users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (plan_id, version_no)
);

CREATE TABLE plan_limits (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_version_id uuid NOT NULL REFERENCES plan_versions(id) ON DELETE CASCADE,
    limit_key varchar(150) NOT NULL,
    integer_value bigint,
    boolean_value boolean,
    text_value text,
    json_value jsonb,
    UNIQUE (plan_version_id, limit_key)
);

CREATE TABLE user_subscriptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    plan_version_id uuid NOT NULL REFERENCES plan_versions(id),
    entitlement_snapshot jsonb NOT NULL,
    status varchar(32) NOT NULL,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    cycle_anchor_day smallint NOT NULL,
    is_trial boolean NOT NULL DEFAULT false,
    opened_by_id uuid REFERENCES admin_users(id),
    note text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (cycle_anchor_day BETWEEN 1 AND 31),
    CHECK (status IN ('pending','active','expired','terminated','overridden'))
);
CREATE UNIQUE INDEX one_active_subscription_per_user
ON user_subscriptions(user_id) WHERE status = 'active';

CREATE TABLE quota_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid,
    subscription_id uuid NOT NULL REFERENCES user_subscriptions(id),
    quota_type varchar(100) NOT NULL,
    batch_key varchar(100) NOT NULL,
    available bigint NOT NULL DEFAULT 0,
    frozen bigint NOT NULL DEFAULT 0,
    cycle_started_at timestamptz,
    cycle_ends_at timestamptz,
    expires_at timestamptz,
    status varchar(32) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (available >= 0),
    CHECK (frozen >= 0),
    UNIQUE (user_id, subject_id, subscription_id, quota_type, batch_key)
);

CREATE TABLE quota_holds (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    quota_account_id uuid NOT NULL REFERENCES quota_accounts(id),
    business_type varchar(100) NOT NULL,
    business_id uuid NOT NULL,
    requested_amount bigint NOT NULL,
    settled_amount bigint NOT NULL DEFAULT 0,
    refunded_amount bigint NOT NULL DEFAULT 0,
    status varchar(32) NOT NULL DEFAULT 'active',
    idempotency_key varchar(200) NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (requested_amount >= 0),
    CHECK (settled_amount >= 0),
    CHECK (refunded_amount >= 0)
);

CREATE TABLE quota_ledger_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid,
    subscription_id uuid REFERENCES user_subscriptions(id),
    quota_account_id uuid REFERENCES quota_accounts(id),
    quota_type varchar(100) NOT NULL,
    action varchar(50) NOT NULL,
    amount bigint NOT NULL,
    available_before bigint NOT NULL,
    available_after bigint NOT NULL,
    frozen_before bigint NOT NULL,
    frozen_after bigint NOT NULL,
    business_type varchar(100),
    business_id uuid,
    reason text NOT NULL DEFAULT '',
    actor_type varchar(32) NOT NULL,
    actor_id uuid,
    idempotency_key varchar(200) NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- 不提供 UPDATE/DELETE 业务接口；修正只能追加反向流水。

CREATE TABLE subject_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type_key varchar(100) NOT NULL UNIQUE,
    name varchar(150) NOT NULL,
    description text NOT NULL DEFAULT '',
    enabled boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE subject_field_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_type_id uuid NOT NULL REFERENCES subject_types(id),
    field_key varchar(150) NOT NULL,
    label varchar(150) NOT NULL,
    field_type varchar(50) NOT NULL,
    required boolean NOT NULL DEFAULT false,
    options jsonb,
    default_value jsonb,
    sort_order integer NOT NULL DEFAULT 0,
    used_for_ai boolean NOT NULL DEFAULT true,
    name_role varchar(50) NOT NULL DEFAULT 'none',
    enabled boolean NOT NULL DEFAULT true,
    UNIQUE (subject_type_id, field_key)
);

CREATE TABLE subjects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_type_id uuid NOT NULL REFERENCES subject_types(id),
    current_version_id uuid,
    status varchar(32) NOT NULL DEFAULT 'draft',
    review_status varchar(32) NOT NULL DEFAULT 'not_required',
    is_active boolean NOT NULL DEFAULT true,
    archived_at timestamptz,
    trashed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX subjects_user_status_idx ON subjects(user_id, status, created_at DESC);

CREATE TABLE subject_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    version_no integer NOT NULL,
    form_data jsonb NOT NULL,
    official_name varchar(255) NOT NULL,
    official_url text,
    completeness_percent numeric(5,2) NOT NULL DEFAULT 0,
    created_by_type varchar(32) NOT NULL,
    created_by_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (subject_id, version_no)
);
ALTER TABLE subjects ADD CONSTRAINT subjects_current_version_fk
FOREIGN KEY (current_version_id) REFERENCES subject_versions(id);

CREATE TABLE subject_names (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_version_id uuid NOT NULL REFERENCES subject_versions(id) ON DELETE CASCADE,
    name_text varchar(255) NOT NULL,
    name_type varchar(32) NOT NULL,
    counts_as_mention boolean NOT NULL DEFAULT true
);

CREATE TABLE subject_products (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_version_id uuid NOT NULL REFERENCES subject_versions(id) ON DELETE CASCADE,
    product_name varchar(255) NOT NULL,
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
    uniquely_identifies_subject boolean NOT NULL DEFAULT false,
    counts_as_mention boolean NOT NULL DEFAULT false
);

CREATE TABLE keyword_sets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    subject_version_id uuid NOT NULL REFERENCES subject_versions(id),
    version_no integer NOT NULL,
    generation_config jsonb NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'draft',
    is_current boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (subject_id, version_no)
);
CREATE UNIQUE INDEX one_current_keyword_set
ON keyword_sets(subject_id) WHERE is_current = true;

CREATE TABLE keywords (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    keyword_set_id uuid NOT NULL REFERENCES keyword_sets(id) ON DELETE CASCADE,
    keyword_text varchar(500) NOT NULL,
    structure_type varchar(32) NOT NULL DEFAULT 'general',
    is_regional boolean NOT NULL DEFAULT false,
    province varchar(100),
    city varchar(100),
    district varchar(100),
    custom_region varchar(150),
    base_keyword_id uuid REFERENCES keywords(id),
    search_intent varchar(100),
    business_category varchar(100),
    relevance_score numeric(5,2),
    priority varchar(16),
    ai_reason text,
    enabled boolean NOT NULL DEFAULT true,
    CHECK (structure_type IN ('short','long_tail','general'))
);

CREATE TABLE keyword_generation_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    subject_version_id uuid NOT NULL REFERENCES subject_versions(id),
    keyword_set_id uuid REFERENCES keyword_sets(id),
    subscription_id uuid NOT NULL REFERENCES user_subscriptions(id),
    quota_hold_id uuid REFERENCES quota_hold_groups(id),
    status varchar(16) NOT NULL,
    billing_mode varchar(16) NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    expected_keyword_set_version bigint NOT NULL,
    target_count integer NOT NULL,
    include_short boolean NOT NULL DEFAULT false,
    include_long_tail boolean NOT NULL DEFAULT false,
    include_regional boolean NOT NULL DEFAULT false,
    regions jsonb NOT NULL DEFAULT '[]'::jsonb,
    input_subject_values jsonb NOT NULL,
    historical_exclusions jsonb NOT NULL DEFAULT '[]'::jsonb,
    provider_key varchar(32) NOT NULL,
    model_key varchar(64) NOT NULL,
    adapter_version varchar(32) NOT NULL,
    prompt_version varchar(32) NOT NULL,
    input_digest varchar(64) NOT NULL,
    idempotency_key_digest varchar(64) NOT NULL UNIQUE,
    request_digest varchar(64) NOT NULL,
    generation uuid,
    attempts integer NOT NULL DEFAULT 0,
    retry_count integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    stable_error_code varchar(64) NOT NULL DEFAULT '',
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('queued','running','retry_wait','succeeded','failed','conflict','superseded')),
    CHECK ((billing_mode = 'free_initial' AND quota_hold_id IS NULL)
        OR (billing_mode = 'regeneration' AND quota_hold_id IS NOT NULL))
);
CREATE UNIQUE INDEX keyword_generation_one_open
ON keyword_generation_jobs(subject_id)
WHERE status IN ('queued','running','retry_wait');

CREATE TABLE keyword_generation_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL UNIQUE REFERENCES keyword_generation_jobs(id),
    output_snapshot jsonb NOT NULL,
    output_digest varchar(64) NOT NULL,
    item_count integer NOT NULL,
    applied_keyword_set_version bigint NOT NULL,
    provider_metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE keyword_generation_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES keyword_generation_jobs(id),
    event_type varchar(24) NOT NULL,
    stable_error_code varchar(64) NOT NULL DEFAULT '',
    safe_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    request_id uuid,
    correlation_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (event_type IN ('started','retry_scheduled','succeeded','failed','conflict','superseded'))
);

CREATE TABLE distillation_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    subject_version_id uuid NOT NULL REFERENCES subject_versions(id),
    input_keyword_set_version_id uuid NOT NULL REFERENCES keyword_set_versions(id),
    subscription_id uuid NOT NULL REFERENCES subscriptions(id),
    quota_hold_id uuid REFERENCES quota_hold_groups(id),
    status varchar(16) NOT NULL DEFAULT 'queued',
    billing_mode varchar(16) NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    expected_workspace_version bigint NOT NULL,
    input_subject_values jsonb NOT NULL,
    input_keywords jsonb NOT NULL,
    provider_key varchar(32) NOT NULL,
    model_key varchar(64) NOT NULL,
    adapter_version varchar(32) NOT NULL,
    prompt_version varchar(32) NOT NULL,
    input_digest varchar(64) NOT NULL,
    idempotency_key_digest varchar(64) NOT NULL UNIQUE,
    request_digest varchar(64) NOT NULL,
    generation uuid,
    attempts integer NOT NULL DEFAULT 0,
    retry_count integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    stable_error_code varchar(64) NOT NULL DEFAULT '',
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('queued','running','retry_wait','succeeded','failed','conflict','superseded')),
    CHECK ((billing_mode = 'free_initial' AND quota_hold_id IS NULL)
        OR (billing_mode = 'regeneration' AND quota_hold_id IS NOT NULL))
);
CREATE UNIQUE INDEX distillation_one_open_idx ON distillation_jobs(subject_id)
WHERE status IN ('queued','running','retry_wait');

CREATE TABLE distillation_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL UNIQUE REFERENCES distillation_jobs(id),
    output_snapshot jsonb NOT NULL,
    output_digest varchar(64) NOT NULL,
    item_count integer NOT NULL,
    applied_workspace_version bigint NOT NULL,
    provider_metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE distillation_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES distillation_jobs(id),
    event_type varchar(24) NOT NULL,
    stable_error_code varchar(64) NOT NULL DEFAULT '',
    safe_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    request_id uuid,
    correlation_id uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE distillation_workspaces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL UNIQUE REFERENCES subjects(id),
    draft_input_version_id uuid NOT NULL REFERENCES keyword_set_versions(id),
    draft_source_result_id uuid NOT NULL REFERENCES distillation_results(id),
    current_set_id uuid,
    version bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE distillation_sets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES distillation_workspaces(id),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    subject_version_id uuid NOT NULL REFERENCES subject_versions(id),
    input_keyword_set_version_id uuid NOT NULL REFERENCES keyword_set_versions(id),
    source_result_id uuid NOT NULL REFERENCES distillation_results(id),
    version_no bigint NOT NULL,
    content_digest varchar(64) NOT NULL,
    item_count integer NOT NULL,
    confirmed_by_id uuid REFERENCES users(id),
    confirmed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, version_no)
);
ALTER TABLE distillation_workspaces ADD CONSTRAINT distillation_workspace_current_fk
    FOREIGN KEY (current_set_id) REFERENCES distillation_sets(id);

CREATE TABLE distillation_draft_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES distillation_workspaces(id) ON DELETE CASCADE,
    source_keyword_id uuid NOT NULL REFERENCES keywords(id),
    action varchar(16) NOT NULL,
    canonical_keyword_id uuid REFERENCES keywords(id),
    merge_group_key uuid,
    ai_action varchar(16) NOT NULL,
    ai_canonical_keyword_id uuid REFERENCES keywords(id),
    ai_merge_group_key uuid,
    ai_reason varchar(1000) NOT NULL,
    user_reason varchar(1000) NOT NULL DEFAULT '',
    user_overridden boolean NOT NULL DEFAULT false,
    sort_order integer NOT NULL,
    UNIQUE (workspace_id, source_keyword_id),
    UNIQUE (workspace_id, sort_order),
    CHECK (action IN ('keep','merge','delete','low_value')),
    CHECK (ai_action IN ('keep','merge','delete','low_value'))
);

CREATE TABLE distillation_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    distillation_set_id uuid NOT NULL REFERENCES distillation_sets(id),
    source_keyword_id uuid NOT NULL REFERENCES keywords(id),
    action varchar(16) NOT NULL,
    canonical_keyword_id uuid REFERENCES keywords(id),
    merge_group_key uuid,
    ai_action varchar(16) NOT NULL,
    ai_canonical_keyword_id uuid REFERENCES keywords(id),
    ai_merge_group_key uuid,
    ai_reason varchar(1000) NOT NULL,
    user_reason varchar(1000) NOT NULL DEFAULT '',
    user_overridden boolean NOT NULL DEFAULT false,
    sort_order integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (distillation_set_id, source_keyword_id),
    UNIQUE (distillation_set_id, sort_order),
    CHECK (action IN ('keep','merge','delete','low_value')),
    CHECK (ai_action IN ('keep','merge','delete','low_value'))
);

CREATE TABLE question_categories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key varchar(100) NOT NULL UNIQUE,
    name varchar(150) NOT NULL,
    normalized_name varchar(150) NOT NULL UNIQUE,
    description varchar(500) NOT NULL DEFAULT '',
    generation_guidance varchar(2000) NOT NULL DEFAULT '',
    status varchar(16) NOT NULL DEFAULT 'active',
    sort_order integer NOT NULL DEFAULT 0,
    is_builtin boolean NOT NULL DEFAULT false,
    version bigint NOT NULL DEFAULT 1,
    created_by_id uuid REFERENCES users(id) ON DELETE SET NULL,
    updated_by_id uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('active','inactive')),
    CHECK (version >= 1)
);

CREATE TABLE question_category_subject_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id uuid NOT NULL REFERENCES question_categories(id) ON DELETE CASCADE,
    subject_type_id uuid NOT NULL REFERENCES subject_types(id) ON DELETE RESTRICT,
    UNIQUE (category_id, subject_type_id)
);

CREATE TABLE question_tags (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key varchar(100) NOT NULL UNIQUE,
    name varchar(150) NOT NULL,
    normalized_name varchar(150) NOT NULL UNIQUE,
    description varchar(500) NOT NULL DEFAULT '',
    status varchar(16) NOT NULL DEFAULT 'active',
    sort_order integer NOT NULL DEFAULT 0,
    is_builtin boolean NOT NULL DEFAULT false,
    version bigint NOT NULL DEFAULT 1,
    created_by_id uuid REFERENCES users(id) ON DELETE SET NULL,
    updated_by_id uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('active','inactive')),
    CHECK (version >= 1)
);

CREATE TABLE question_tag_subject_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tag_id uuid NOT NULL REFERENCES question_tags(id) ON DELETE CASCADE,
    subject_type_id uuid NOT NULL REFERENCES subject_types(id) ON DELETE RESTRICT,
    UNIQUE (tag_id, subject_type_id)
);

CREATE TABLE question_generation_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    subject_version_id uuid NOT NULL REFERENCES subject_versions(id),
    input_distillation_set_id uuid NOT NULL REFERENCES distillation_sets(id),
    subscription_id uuid NOT NULL REFERENCES user_subscriptions(id),
    quota_hold_id uuid REFERENCES quota_holds(id),
    status varchar(16) NOT NULL DEFAULT 'queued',
    billing_mode varchar(16) NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    expected_workspace_version bigint NOT NULL,
    question_limit integer NOT NULL,
    input_subject_values jsonb NOT NULL,
    input_keywords jsonb NOT NULL,
    input_categories jsonb NOT NULL,
    input_tags jsonb NOT NULL,
    provider_key varchar(32) NOT NULL,
    model_key varchar(64) NOT NULL,
    adapter_version varchar(32) NOT NULL,
    prompt_version varchar(32) NOT NULL,
    input_digest char(64) NOT NULL,
    idempotency_key_version smallint NOT NULL DEFAULT 1,
    idempotency_key_digest char(64) NOT NULL UNIQUE,
    request_digest char(64) NOT NULL,
    generation uuid,
    attempts integer NOT NULL DEFAULT 0,
    retry_count integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    stable_error_code varchar(64) NOT NULL DEFAULT '',
    request_id uuid,
    correlation_id uuid,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('queued','running','retry_wait','succeeded','failed','conflict','superseded')),
    CHECK (billing_mode IN ('free_initial','regeneration'))
);
CREATE UNIQUE INDEX question_generation_one_active_subject
    ON question_generation_jobs(subject_id)
    WHERE status IN ('queued','running','retry_wait');

CREATE TABLE question_generation_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL UNIQUE REFERENCES question_generation_jobs(id),
    output_snapshot jsonb NOT NULL,
    output_digest char(64) NOT NULL,
    item_count integer NOT NULL,
    applied_workspace_version bigint NOT NULL,
    provider_metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE question_bank_workspaces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL UNIQUE REFERENCES subjects(id),
    draft_subject_version_id uuid NOT NULL REFERENCES subject_versions(id),
    draft_distillation_set_id uuid NOT NULL REFERENCES distillation_sets(id),
    draft_source_result_id uuid REFERENCES question_generation_results(id),
    current_version_id uuid,
    version bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE question_draft_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES question_bank_workspaces(id),
    text varchar(1000) NOT NULL,
    matching_text varchar(1000) NOT NULL,
    primary_category_id uuid NOT NULL REFERENCES question_categories(id),
    priority varchar(16) NOT NULL,
    question_type varchar(24) NOT NULL,
    participates_in_scoring boolean NOT NULL DEFAULT true,
    ai_reason varchar(1000) NOT NULL DEFAULT '',
    tag_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    keyword_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    sort_order integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, matching_text),
    UNIQUE (workspace_id, sort_order),
    CHECK (priority IN ('high','medium','low')),
    CHECK (question_type IN ('natural','brand_directed'))
);

CREATE TABLE question_bank_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES question_bank_workspaces(id),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    subject_version_id uuid NOT NULL REFERENCES subject_versions(id),
    distillation_set_id uuid NOT NULL REFERENCES distillation_sets(id),
    source_result_id uuid REFERENCES question_generation_results(id),
    version_no bigint NOT NULL,
    content_digest char(64) NOT NULL,
    item_count integer NOT NULL,
    confirmed_by_id uuid NOT NULL REFERENCES users(id),
    confirmed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (subject_id, version_no)
);
ALTER TABLE question_bank_workspaces
    ADD CONSTRAINT question_bank_workspace_current_version_fk
    FOREIGN KEY (current_version_id) REFERENCES question_bank_versions(id);

CREATE TABLE questions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_bank_version_id uuid NOT NULL REFERENCES question_bank_versions(id),
    text varchar(1000) NOT NULL,
    matching_text varchar(1000) NOT NULL,
    primary_category_id uuid NOT NULL REFERENCES question_categories(id),
    primary_category_key varchar(100) NOT NULL,
    primary_category_name varchar(150) NOT NULL,
    primary_category_version bigint NOT NULL,
    priority varchar(16) NOT NULL,
    question_type varchar(24) NOT NULL,
    participates_in_scoring boolean NOT NULL DEFAULT true,
    ai_reason varchar(1000) NOT NULL DEFAULT '',
    sort_order integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (question_bank_version_id, matching_text),
    UNIQUE (question_bank_version_id, sort_order),
    CHECK (priority IN ('high','medium','low')),
    CHECK (question_type IN ('natural','brand_directed'))
);

CREATE TABLE question_tag_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id uuid NOT NULL REFERENCES questions(id),
    tag_id uuid NOT NULL REFERENCES question_tags(id),
    tag_key varchar(100) NOT NULL,
    tag_name varchar(150) NOT NULL,
    tag_version bigint NOT NULL,
    UNIQUE (question_id, tag_id)
);

CREATE TABLE question_keyword_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id uuid NOT NULL REFERENCES questions(id),
    keyword_id uuid NOT NULL REFERENCES keywords(id),
    keyword_text varchar(500) NOT NULL,
    UNIQUE (question_id, keyword_id)
);

CREATE TABLE question_generation_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES question_generation_jobs(id),
    event_type varchar(24) NOT NULL,
    stable_error_code varchar(64) NOT NULL DEFAULT '',
    safe_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    request_id uuid,
    correlation_id uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- XW-0305 migration guards make generation input/result/event facts and formal
-- question-bank history append-only, enforce job transitions, and validate
-- workspace/current-version ownership and continuous formal version numbers.

CREATE TABLE ai_providers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_key varchar(100) NOT NULL UNIQUE,
    name varchar(150) NOT NULL,
    enabled boolean NOT NULL DEFAULT true
);

CREATE TABLE ai_models (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id uuid NOT NULL REFERENCES ai_providers(id),
    model_key varchar(100) NOT NULL UNIQUE,
    display_name varchar(150) NOT NULL,
    purpose varchar(50) NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0
);

CREATE TABLE ai_model_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ai_model_id uuid NOT NULL REFERENCES ai_models(id),
    provider_model_id varchar(255) NOT NULL,
    api_version varchar(100),
    supports_web_search boolean NOT NULL DEFAULT false,
    capability_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- XW-0402 implemented schema override:
-- Django migrations `apps.ai.0001_initial` and `0002_seed_and_postgresql_guards`
-- are authoritative for the fixed eight detection providers/models and their
-- one-to-one `ai_model_runtime_configs`. Provider/model canonical identity is
-- immutable; mutable runtime fields include display override/order, provider
-- model ID/API version, enabled/network/failure policy, timeout/retry/backoff,
-- concurrency, CNY cost metadata, pause state and optimistic version. All seed
-- rows start disabled. No credential or secret reference is stored by XW-0402.

CREATE TABLE api_credentials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id uuid NOT NULL REFERENCES ai_providers(id),
    environment varchar(32) NOT NULL CHECK (environment IN ('staging', 'production')),
    secret_reference text NOT NULL,
    secret_mask varchar(100) NOT NULL,
    version_no integer NOT NULL CHECK (version_no >= 1),
    status varchar(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'replaced')),
    created_by_id uuid NOT NULL REFERENCES admin_users(id),
    replaced_by_id uuid REFERENCES admin_users(id),
    replaced_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider_id, environment, version_no)
);
-- XW-0403 的 Django migration 另加 provider/environment active 条件唯一约束和 PostgreSQL guards。
-- secret_reference 只允许保存应用层 Fernet 认证密文；轮换后旧版本 secret_reference 被擦除为空串。

CREATE TABLE api_credential_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_id uuid NOT NULL REFERENCES api_credentials(id),
    action varchar(16) NOT NULL,
    outcome varchar(16) NOT NULL,
    actor_id uuid REFERENCES admin_users(id),
    safe_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    stable_error_code varchar(64) NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);
-- 追加式安全审计；禁止保存明文、密文或 provider raw response。

CREATE TABLE scoring_rule_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_key varchar(100) NOT NULL,
    version_no integer NOT NULL,
    rule_config jsonb NOT NULL,
    scoring_model_version_id uuid REFERENCES ai_model_versions(id),
    status varchar(32) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (rule_key, version_no)
);

CREATE TABLE geo_detection_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    status varchar(32) NOT NULL DEFAULT 'queued',
    planned_question_count integer NOT NULL,
    planned_model_count integer NOT NULL,
    planned_detection_points integer NOT NULL,
    completed_calls integer NOT NULL DEFAULT 0,
    successful_calls integer NOT NULL DEFAULT 0,
    failed_calls integer NOT NULL DEFAULT 0,
    queue_priority integer NOT NULL DEFAULT 0,
    quota_hold_id uuid REFERENCES quota_holds(id),
    idempotency_key varchar(200) NOT NULL UNIQUE,
    queued_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    cancelled_at timestamptz
);
CREATE INDEX geo_jobs_queue_idx ON geo_detection_jobs(status, queue_priority DESC, queued_at ASC);

CREATE TABLE geo_detection_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    geo_detection_job_id uuid NOT NULL UNIQUE REFERENCES geo_detection_jobs(id) ON DELETE CASCADE,
    subject_version_id uuid NOT NULL REFERENCES subject_versions(id),
    keyword_set_id uuid REFERENCES keyword_sets(id),
    distillation_set_id uuid REFERENCES distillation_sets(id),
    question_bank_version_id uuid NOT NULL REFERENCES question_bank_versions(id),
    questions_snapshot jsonb NOT NULL,
    models_snapshot jsonb NOT NULL,
    prompt_versions_snapshot jsonb NOT NULL,
    scoring_rule_version_id uuid NOT NULL REFERENCES scoring_rule_versions(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_calls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    geo_detection_job_id uuid NOT NULL REFERENCES geo_detection_jobs(id),
    question_snapshot_key varchar(100) NOT NULL,
    ai_model_version_id uuid NOT NULL REFERENCES ai_model_versions(id),
    status varchar(32) NOT NULL DEFAULT 'queued',
    web_search_requested boolean NOT NULL DEFAULT false,
    web_search_used boolean NOT NULL DEFAULT false,
    degraded boolean NOT NULL DEFAULT false,
    attempt_count integer NOT NULL DEFAULT 0,
    provider_request_id varchar(255),
    latency_ms integer,
    error_category varchar(100),
    quota_settlement_status varchar(32) NOT NULL DEFAULT 'pending',
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (geo_detection_job_id, question_snapshot_key, ai_model_version_id)
);

CREATE TABLE model_responses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_call_id uuid NOT NULL UNIQUE REFERENCES model_calls(id) ON DELETE CASCADE,
    raw_text text NOT NULL,
    raw_payload jsonb,
    response_hash varchar(128) NOT NULL,
    evidence_excerpt text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE response_citations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_response_id uuid NOT NULL REFERENCES model_responses(id) ON DELETE CASCADE,
    title text,
    url text,
    source_name varchar(255),
    source_type varchar(64),
    access_status varchar(64),
    is_relevant boolean,
    checked_at timestamptz
);

CREATE TABLE score_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_call_id uuid NOT NULL UNIQUE REFERENCES model_calls(id) ON DELETE CASCADE,
    question_type varchar(32) NOT NULL,
    mentioned boolean,
    mention_score numeric(6,3),
    recommendation_score numeric(6,3),
    ranking_score numeric(6,3),
    accuracy_score numeric(6,3),
    sentiment_score numeric(6,3),
    citation_score numeric(6,3),
    total_score numeric(7,4) NOT NULL,
    evidence jsonb NOT NULL,
    scoring_rule_version_id uuid NOT NULL REFERENCES scoring_rule_versions(id),
    scoring_model_version_id uuid NOT NULL REFERENCES ai_model_versions(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geo_reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    geo_detection_job_id uuid NOT NULL UNIQUE REFERENCES geo_detection_jobs(id),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    geo_score numeric(7,4),
    geo_score_status varchar(32),
    geo_grade varchar(32),
    brand_score numeric(7,4),
    brand_score_status varchar(32),
    brand_grade varchar(32),
    exposure_index numeric(7,4),
    exposure_status varchar(32),
    exposure_grade varchar(32),
    formal_geo_model_count integer NOT NULL DEFAULT 0,
    formal_brand_model_count integer NOT NULL DEFAULT 0,
    report_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE articles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    subject_version_id uuid NOT NULL REFERENCES subject_versions(id),
    article_type_key varchar(100),
    custom_type varchar(150),
    title text,
    content text NOT NULL DEFAULT '',
    content_depth varchar(32) NOT NULL DEFAULT 'standard',
    status varchar(32) NOT NULL DEFAULT 'draft',
    moderation_status varchar(32) NOT NULL DEFAULT 'not_checked',
    current_quality_score numeric(7,4),
    autosaved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE article_comparison_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id uuid NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    original_content text NOT NULL,
    optimized_content text NOT NULL,
    optimization_type varchar(32) NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'pending_choice',
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- 用户选择后仅将选中内容写回 articles，候选按短期策略清理。

CREATE TABLE channel_adaptations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id uuid NOT NULL REFERENCES articles(id),
    channel_key varchar(100) NOT NULL,
    title text,
    content text NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'ready',
    quality_score numeric(7,4),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE images (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    article_id uuid REFERENCES articles(id),
    cos_object_key text NOT NULL,
    mime_type varchar(100) NOT NULL,
    byte_size bigint NOT NULL,
    width integer,
    height integer,
    saved_to_subject_library boolean NOT NULL DEFAULT false,
    moderation_status varchar(32) NOT NULL,
    trashed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE publication_link_checks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject_id uuid NOT NULL REFERENCES subjects(id),
    article_id uuid REFERENCES articles(id),
    channel_adaptation_id uuid REFERENCES channel_adaptations(id),
    channel_key varchar(100) NOT NULL,
    published_url text NOT NULL,
    result varchar(32) NOT NULL,
    detected_title text,
    match_summary text,
    failure_reason text,
    checked_at timestamptz NOT NULL DEFAULT now(),
    CHECK (result IN ('success','failed','unknown'))
);

CREATE TABLE admin_audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id uuid REFERENCES admin_users(id),
    action_key varchar(150) NOT NULL,
    object_type varchar(100),
    object_id uuid,
    before_summary jsonb,
    after_summary jsonb,
    reason text,
    ip_address inet,
    user_agent text,
    approval_request_id uuid,
    result varchar(32) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- 建议后续 migrations 继续创建：
-- user_sessions, login_events, sms_verification_codes, package_applications,
-- subscription_changes, customer_profiles, customer_statuses, customer_tags,
-- customer_contact_logs, customer_followups, risk_types, risk_rules, subject_reviews,
-- user_documents, document_versions, document_parse_jobs, document_parsed_versions,
-- web_source_imports, distillation_jobs,
-- question_keyword_links, api_credential_audit,
-- prompt_templates, prompt_template_versions, prompt_test_cases, prompt_test_runs,
-- model_call_attempts, api_cost_records, geo_detection_model_runs, model_scores,
-- competitor_entities, competitor_mentions, strategy_reports, strategy_notes,
-- article_types, article_template_versions, article_source_packs, article_source_items,
-- article_outlines, article_generation_jobs, article_quality_checks,
-- article_moderation_reviews, publishing_channels, channel_template_versions,
-- image_size_presets, image_style_presets, image_generation_jobs,
-- image_reference_links, image_moderation_reviews, image_derivatives,
-- report_exports, subject_white_label_configs, report_shares, report_share_access_logs,
-- notifications, notification_templates, announcements, announcement_targets,
-- user_feedback, feedback_attachments, support_view_requests, support_view_audit_logs,
-- system_settings, async_tasks, system_alerts, backup_records, retention_jobs, deletion_jobs.
