import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

GENERATION_GUARD_SQL = r"""
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
            NEW.include_regional, NEW.regions, NEW.generation_mode,
            NEW.requested_categories, NEW.requested_intents, NEW.region_mode,
            NEW.input_subject_values, NEW.historical_exclusions,
            NEW.provider_key, NEW.model_key, NEW.adapter_version,
            NEW.prompt_version, NEW.input_digest,
            NEW.idempotency_key_version, NEW.idempotency_key_digest,
            NEW.request_digest, NEW.request_id, NEW.correlation_id,
            NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.user_id, OLD.subject_id, OLD.subject_version_id,
            OLD.keyword_set_id, OLD.subscription_id, OLD.quota_hold_id,
            OLD.billing_mode, OLD.expected_keyword_set_version,
            OLD.target_count, OLD.include_short, OLD.include_long_tail,
            OLD.include_regional, OLD.regions, OLD.generation_mode,
            OLD.requested_categories, OLD.requested_intents, OLD.region_mode,
            OLD.input_subject_values, OLD.historical_exclusions,
            OLD.provider_key, OLD.model_key, OLD.adapter_version,
            OLD.prompt_version, OLD.input_digest,
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
"""


LEGACY_GENERATION_GUARD_SQL = r"""
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
"""


def backfill_legacy_metadata(apps, schema_editor):
    model = apps.get_model("keywords", "KeywordDraftItem")
    rows = model.objects.exclude(search_intent__isnull=True).exclude(search_intent="")
    for row in rows.iterator(chunk_size=500):
        row.search_intents = [row.search_intent]
        row.save(update_fields=["search_intents"])


def refresh_generation_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GENERATION_GUARD_SQL)


def restore_generation_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(LEGACY_GENERATION_GUARD_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("keywords", "0007_distillation_postgresql_guards"),
        ("plans", "0016_internal_test_subscription_source"),
        ("quotas", "0013_quotaholdgroup_test_account_bypass"),
        ("subjects", "0017_promote_saved_subjects"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="KeywordAssetPreference",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("display_text", models.CharField(blank=True, max_length=500)),
                ("business_category", models.CharField(blank=True, max_length=128)),
                (
                    "search_intents",
                    models.JSONField(blank=True, default=None, null=True),
                ),
                (
                    "region_selections",
                    models.JSONField(blank=True, default=None, null=True),
                ),
                ("enabled", models.BooleanField(default=True)),
                ("usable_for_questions", models.BooleanField(default=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source_keyword",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="asset_preferences",
                        to="keywords.keyword",
                    ),
                ),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="keyword_asset_preferences",
                        to="subjects.subject",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="keyword_asset_preferences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "keyword_asset_preferences",
                "ordering": ("subject_id", "source_keyword_id"),
            },
        ),
        migrations.RemoveConstraint(
            model_name="keyword",
            name="keyword_formal_region_level_valid",
        ),
        migrations.RemoveConstraint(
            model_name="keyworddraftitem",
            name="keyword_draft_region_level_valid",
        ),
        migrations.AddField(
            model_name="keyword",
            name="notes",
            field=models.CharField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name="keyword",
            name="regions",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="keyword",
            name="search_intents",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="keyword",
            name="source",
            field=models.CharField(
                choices=[
                    ("legacy", "历史数据"),
                    ("manual", "手工添加"),
                    ("bulk", "批量添加"),
                    ("smart_generation", "智能生成"),
                    ("custom_generation", "自定义生成"),
                ],
                default="legacy",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="keyworddraftitem",
            name="notes",
            field=models.CharField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name="keyworddraftitem",
            name="regions",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="keyworddraftitem",
            name="search_intents",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="keyworddraftitem",
            name="source",
            field=models.CharField(
                choices=[
                    ("legacy", "历史数据"),
                    ("manual", "手工添加"),
                    ("bulk", "批量添加"),
                    ("smart_generation", "智能生成"),
                    ("custom_generation", "自定义生成"),
                ],
                default="legacy",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="keywordgenerationjob",
            name="generation_mode",
            field=models.CharField(
                choices=[("smart", "智能关键词"), ("custom", "自定义关键词")],
                default="smart",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="keywordgenerationjob",
            name="region_mode",
            field=models.CharField(
                choices=[
                    ("unrestricted", "不限地域"),
                    ("subject", "使用当前主体服务区域"),
                    ("custom", "自定义地域"),
                ],
                default="unrestricted",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="keywordgenerationjob",
            name="requested_categories",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="keywordgenerationjob",
            name="requested_intents",
            field=models.JSONField(default=list),
        ),
        migrations.AlterField(
            model_name="keyword",
            name="region_level",
            field=models.CharField(
                blank=True,
                choices=[
                    ("country", "国家/地区"),
                    ("province", "省/州"),
                    ("city", "城市"),
                    ("district", "区县"),
                    ("street", "乡镇/街道"),
                    ("custom", "自定义"),
                ],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="keyworddraftitem",
            name="region_level",
            field=models.CharField(
                blank=True,
                choices=[
                    ("country", "国家/地区"),
                    ("province", "省/州"),
                    ("city", "城市"),
                    ("district", "区县"),
                    ("street", "乡镇/街道"),
                    ("custom", "自定义"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="keyword",
            constraint=models.CheckConstraint(
                condition=models.Q(region_level="")
                | models.Q(
                    region_level__in=(
                        "country",
                        "province",
                        "city",
                        "district",
                        "street",
                        "custom",
                    )
                ),
                name="keyword_formal_region_level_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="keyworddraftitem",
            constraint=models.CheckConstraint(
                condition=models.Q(region_level="")
                | models.Q(
                    region_level__in=(
                        "country",
                        "province",
                        "city",
                        "district",
                        "street",
                        "custom",
                    )
                ),
                name="keyword_draft_region_level_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="keywordgenerationjob",
            constraint=models.CheckConstraint(
                condition=models.Q(generation_mode__in=("smart", "custom"))
                & models.Q(region_mode__in=("unrestricted", "subject", "custom")),
                name="keyword_generation_modes_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="keywordassetpreference",
            constraint=models.UniqueConstraint(
                fields=("subject", "source_keyword"),
                name="keyword_asset_preference_unique",
            ),
        ),
        migrations.RunPython(backfill_legacy_metadata, migrations.RunPython.noop),
        migrations.RunPython(refresh_generation_guard, restore_generation_guard),
    ]
