import uuid

from django.db import migrations


SIZES = (
    ("71100000-0000-4000-8000-000000000001", "square_1_1", "方图 1:1", "1:1", 2048, 2048, "2048x2048"),
    ("71100000-0000-4000-8000-000000000002", "landscape_16_9", "横图 16:9", "16:9", 2560, 1440, "2560x1440"),
    ("71100000-0000-4000-8000-000000000003", "portrait_3_4", "竖图 3:4", "3:4", 1728, 2304, "1728x2304"),
)
STYLES = (
    ("71200000-0000-4000-8000-000000000001", "natural", "自然专业", "自然、专业、真实的商业视觉。{prompt}"),
    ("71200000-0000-4000-8000-000000000002", "editorial", "编辑插画", "现代编辑插画风格，层次清晰，避免文字和水印。{prompt}"),
    ("71200000-0000-4000-8000-000000000003", "infographic", "信息图视觉", "简洁的信息图视觉，构图清晰，不生成不可核验的数据文字。{prompt}"),
)


def seed_presets(apps, schema_editor):
    Size = apps.get_model("images", "ImageSizePreset")
    Style = apps.get_model("images", "ImageStylePreset")
    for order, (pk, key, name, ratio, width, height, provider_size) in enumerate(SIZES):
        Size.objects.create(
            id=uuid.UUID(pk),
            key=key,
            name=name,
            aspect_ratio=ratio,
            width=width,
            height=height,
            provider_params={"size": provider_size},
            applicable_channels=[],
            applicable_roles=[],
            status="active",
            sort_order=order,
        )
    for order, (pk, key, name, template) in enumerate(STYLES):
        Style.objects.create(
            id=uuid.UUID(pk),
            key=key,
            name=name,
            description="数据库版本化图片风格；用户提示词在服务端安全拼接。",
            prompt_template=template,
            applicable_roles=[],
            status="active",
            sort_order=order,
        )


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        r"""
        CREATE OR REPLACE FUNCTION xw_image_evidence_immutable() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'image evidence is immutable'; END; $$ LANGUAGE plpgsql;
        DO $$ DECLARE table_name text; BEGIN
          FOREACH table_name IN ARRAY ARRAY[
            'image_generation_results', 'image_reference_links',
            'image_moderation_reviews', 'image_derivatives', 'image_batch_downloads'
          ] LOOP
            EXECUTE format('CREATE TRIGGER %%I_immutable BEFORE UPDATE OR DELETE ON %%I FOR EACH ROW EXECUTE FUNCTION xw_image_evidence_immutable()', table_name, table_name);
          END LOOP;
        END $$;

        CREATE OR REPLACE FUNCTION xw_image_job_guard() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'image generation jobs cannot be deleted'; END IF;
          IF NEW.user_id IS DISTINCT FROM OLD.user_id OR
             NEW.subject_id IS DISTINCT FROM OLD.subject_id OR
             NEW.article_id IS DISTINCT FROM OLD.article_id OR
             NEW.generation_type IS DISTINCT FROM OLD.generation_type OR
             NEW.role IS DISTINCT FROM OLD.role OR
             NEW.prompt IS DISTINCT FROM OLD.prompt OR
             NEW.prompt_digest IS DISTINCT FROM OLD.prompt_digest OR
             NEW.size_preset_id IS DISTINCT FROM OLD.size_preset_id OR
             NEW.size_snapshot IS DISTINCT FROM OLD.size_snapshot OR
             NEW.style_preset_id IS DISTINCT FROM OLD.style_preset_id OR
             NEW.style_snapshot IS DISTINCT FROM OLD.style_snapshot OR
             NEW.reference_asset_id IS DISTINCT FROM OLD.reference_asset_id OR
             NEW.reference_document_version_id IS DISTINCT FROM OLD.reference_document_version_id OR
             NEW.reference_url IS DISTINCT FROM OLD.reference_url OR
             NEW.reference_snapshot IS DISTINCT FROM OLD.reference_snapshot OR
             NEW.runtime_config_id IS DISTINCT FROM OLD.runtime_config_id OR
             NEW.runtime_version IS DISTINCT FROM OLD.runtime_version OR
             NEW.provider_key IS DISTINCT FROM OLD.provider_key OR
             NEW.provider_model_id IS DISTINCT FROM OLD.provider_model_id OR
             NEW.api_version IS DISTINCT FROM OLD.api_version OR
             NEW.adapter_version IS DISTINCT FROM OLD.adapter_version OR
             NEW.prompt_version IS DISTINCT FROM OLD.prompt_version OR
             NEW.credential_binding_id IS DISTINCT FROM OLD.credential_binding_id OR
             NEW.credential_binding_version IS DISTINCT FROM OLD.credential_binding_version OR
             NEW.credential_id IS DISTINCT FROM OLD.credential_id OR
             NEW.credential_version IS DISTINCT FROM OLD.credential_version OR
             NEW.timeout_seconds IS DISTINCT FROM OLD.timeout_seconds OR
             NEW.retry_base_seconds IS DISTINCT FROM OLD.retry_base_seconds OR
             NEW.subscription_id IS DISTINCT FROM OLD.subscription_id OR
             NEW.quota_hold_id IS DISTINCT FROM OLD.quota_hold_id OR
             NEW.idempotency_key_digest IS DISTINCT FROM OLD.idempotency_key_digest OR
             NEW.request_digest IS DISTINCT FROM OLD.request_digest OR
             NEW.request_id IS DISTINCT FROM OLD.request_id OR
             NEW.created_at IS DISTINCT FROM OLD.created_at
          THEN RAISE EXCEPTION 'image generation provenance is immutable'; END IF;
          IF OLD.status IN ('succeeded', 'failed') THEN
            RAISE EXCEPTION 'terminal image generation job is immutable';
          END IF;
          IF NOT (
            OLD.status = NEW.status OR
            (OLD.status = 'queued' AND NEW.status IN ('running', 'failed')) OR
            (OLD.status = 'running' AND NEW.status IN ('retry_wait', 'succeeded', 'failed')) OR
            (OLD.status = 'retry_wait' AND NEW.status IN ('running', 'failed'))
          ) THEN RAISE EXCEPTION 'invalid image job transition'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER image_generation_jobs_guard BEFORE UPDATE OR DELETE ON image_generation_jobs
          FOR EACH ROW EXECUTE FUNCTION xw_image_job_guard();

        CREATE OR REPLACE FUNCTION xw_image_asset_guard() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'image assets cannot be deleted'; END IF;
          IF NEW.user_id IS DISTINCT FROM OLD.user_id OR
             NEW.subject_id IS DISTINCT FROM OLD.subject_id OR
             NEW.generation_job_id IS DISTINCT FROM OLD.generation_job_id OR
             NEW.source_image_id IS DISTINCT FROM OLD.source_image_id OR
             NEW.source_type IS DISTINCT FROM OLD.source_type OR
             NEW.role IS DISTINCT FROM OLD.role OR
             NEW.object_key IS DISTINCT FROM OLD.object_key OR
             NEW.width IS DISTINCT FROM OLD.width OR NEW.height IS DISTINCT FROM OLD.height OR
             NEW.mime_type IS DISTINCT FROM OLD.mime_type OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes OR
             NEW.sha256 IS DISTINCT FROM OLD.sha256 OR NEW.provider_key IS DISTINCT FROM OLD.provider_key OR
             NEW.provider_model_id IS DISTINCT FROM OLD.provider_model_id OR
             NEW.generation_capability IS DISTINCT FROM OLD.generation_capability OR
             NEW.adapter_version IS DISTINCT FROM OLD.adapter_version OR
             NEW.prompt_digest IS DISTINCT FROM OLD.prompt_digest OR
             NEW.source_provenance IS DISTINCT FROM OLD.source_provenance OR
             NEW.generated_at IS DISTINCT FROM OLD.generated_at OR
             NEW.available_at IS DISTINCT FROM OLD.available_at OR
             NEW.created_at IS DISTINCT FROM OLD.created_at
          THEN RAISE EXCEPTION 'image asset provenance is immutable'; END IF;
          IF NEW.version <> OLD.version + 1 THEN RAISE EXCEPTION 'image asset version must increment by one'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER images_guard BEFORE UPDATE OR DELETE ON images
          FOR EACH ROW EXECUTE FUNCTION xw_image_asset_guard();

        CREATE OR REPLACE FUNCTION xw_image_preset_guard() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'image presets cannot be deleted'; END IF;
          IF NEW.id IS DISTINCT FROM OLD.id OR NEW.key IS DISTINCT FROM OLD.key
          THEN RAISE EXCEPTION 'image preset identity is immutable'; END IF;
          IF NEW.version <> OLD.version + 1 THEN RAISE EXCEPTION 'image preset version must increment by one'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER image_size_presets_guard BEFORE UPDATE OR DELETE ON image_size_presets
          FOR EACH ROW EXECUTE FUNCTION xw_image_preset_guard();
        CREATE TRIGGER image_style_presets_guard BEFORE UPDATE OR DELETE ON image_style_presets
          FOR EACH ROW EXECUTE FUNCTION xw_image_preset_guard();
        """
    )


class Migration(migrations.Migration):
    dependencies = [("images", "0001_initial")]
    operations = [
        migrations.RunPython(seed_presets, migrations.RunPython.noop),
        migrations.RunPython(install_guards, migrations.RunPython.noop),
    ]
