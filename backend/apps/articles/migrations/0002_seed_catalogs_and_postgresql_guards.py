import uuid

from django.db import migrations


ARTICLE_TYPES = (
    (
        "11111111-0601-4000-8000-000000000001",
        "brand_story",
        "品牌故事",
        "以已确认主体事实讲述品牌定位、历程与价值。",
        ["subject", "document", "web"],
        ["website", "wechat"],
        {"sections": ["标题", "摘要", "品牌背景", "核心价值", "行动建议"]},
    ),
    (
        "11111111-0601-4000-8000-000000000002",
        "industry_insight",
        "行业洞察",
        "基于可核验资料形成行业观点与解释。",
        ["subject", "document", "web"],
        ["website", "zhihu", "wechat"],
        {"sections": ["标题", "摘要", "背景", "关键洞察", "结论"]},
    ),
    (
        "11111111-0601-4000-8000-000000000003",
        "product_guide",
        "产品指南",
        "围绕已确认产品资料生成使用与选择指南。",
        ["subject", "document", "web"],
        ["website", "xiaohongshu"],
        {"sections": ["标题", "适用人群", "核心能力", "选择建议", "常见问题"]},
    ),
    (
        "11111111-0601-4000-8000-000000000004",
        "faq_article",
        "问答文章",
        "将常见问题组织为清晰、可引用的回答。",
        ["subject", "document", "web"],
        ["website", "zhihu"],
        {"sections": ["标题", "问题摘要", "逐项回答", "结论"]},
    ),
)

CHANNELS = (
    (
        "22222222-0701-4000-8000-000000000001",
        "website",
        "企业官网",
        "https://www.google.com/",
        "owned_media",
        {"title": "清晰准确", "structure": "完整长文", "tone": "专业", "tags": False, "external_links": "允许可核验来源"},
    ),
    (
        "22222222-0701-4000-8000-000000000002",
        "wechat",
        "微信公众平台",
        "https://mp.weixin.qq.com/",
        "social_content",
        {"title": "简洁有信息量", "structure": "导语、分节、总结", "tone": "专业易读", "tags": False, "external_links": "按平台规则"},
    ),
    (
        "22222222-0701-4000-8000-000000000003",
        "zhihu",
        "知乎",
        "https://www.zhihu.com/",
        "knowledge_community",
        {"title": "问题导向", "structure": "结论先行、论据、总结", "tone": "理性解释", "tags": True, "external_links": "克制使用"},
    ),
    (
        "22222222-0701-4000-8000-000000000004",
        "xiaohongshu",
        "小红书",
        "https://www.xiaohongshu.com/",
        "social_content",
        {"title": "短而具体", "structure": "要点列表", "tone": "自然友好", "tags": True, "external_links": "不主动添加"},
    ),
)


def seed_catalogs(apps, schema_editor):
    ArticleType = apps.get_model("articles", "ArticleType")
    ArticleTemplateVersion = apps.get_model("articles", "ArticleTemplateVersion")
    PublishingChannel = apps.get_model("articles", "PublishingChannel")
    ChannelTemplateVersion = apps.get_model("articles", "ChannelTemplateVersion")
    for order, (pk, key, name, description, sources, channels, structure) in enumerate(ARTICLE_TYPES):
        article_type = ArticleType.objects.create(
            id=uuid.UUID(pk),
            key=key,
            name=name,
            description=description,
            applicable_subject_types=[],
            status="active",
            sort_order=order,
        )
        ArticleTemplateVersion.objects.create(
            article_type=article_type,
            version_no=1,
            prompt_version=f"article-{key}-v1",
            structure=structure,
            network_policy="optional",
            citation_required=True,
            allowed_source_types=sources,
            recommended_channel_keys=channels,
            is_current=True,
        )
    for order, (pk, key, name, url, channel_type, rules) in enumerate(CHANNELS):
        channel = PublishingChannel.objects.create(
            id=uuid.UUID(pk),
            key=key,
            name=name,
            official_url=url,
            channel_type=channel_type,
            description="仅提供官方页面导航、适配稿和即时链接检测；系统不代登录或发布。",
            applicable_article_types=[],
            image_ratios=["1:1", "16:9"],
            enabled=True,
            sort_order=order,
        )
        ChannelTemplateVersion.objects.create(
            channel=channel,
            version_no=1,
            rules=rules,
            prompt_version=f"channel-{key}-v1",
            is_current=True,
        )


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    sql = r"""
    CREATE OR REPLACE FUNCTION article_immutable_guard() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'immutable article evidence';
    END; $$ LANGUAGE plpgsql;

    DO $$ DECLARE table_name text; BEGIN
      FOREACH table_name IN ARRAY ARRAY[
        'article_template_versions', 'channel_template_versions',
        'article_generation_results', 'article_quality_checks',
        'article_moderation_reviews', 'article_exports', 'publication_link_checks'
      ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I_immutable ON %I', table_name, table_name);
        EXECUTE format('CREATE TRIGGER %I_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION article_immutable_guard()', table_name, table_name);
      END LOOP;
    END $$;

    CREATE OR REPLACE FUNCTION article_pack_guard() RETURNS trigger AS $$
    BEGIN
      IF OLD.status = 'confirmed' AND (
        NEW.user_id IS DISTINCT FROM OLD.user_id OR
        NEW.subject_id IS DISTINCT FROM OLD.subject_id OR
        NEW.subject_version_id IS DISTINCT FROM OLD.subject_version_id OR
        NEW.article_type_id IS DISTINCT FROM OLD.article_type_id OR
        NEW.template_version_id IS DISTINCT FROM OLD.template_version_id OR
        NEW.frozen_snapshot IS DISTINCT FROM OLD.frozen_snapshot OR
        NEW.snapshot_digest IS DISTINCT FROM OLD.snapshot_digest OR
        NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at OR
        NEW.status IS DISTINCT FROM OLD.status OR
        NEW.conflict_status IS DISTINCT FROM OLD.conflict_status OR
        NEW.conflicts IS DISTINCT FROM OLD.conflicts
      ) THEN RAISE EXCEPTION 'confirmed source pack is immutable'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER article_source_packs_guard BEFORE UPDATE ON article_source_packs
      FOR EACH ROW EXECUTE FUNCTION article_pack_guard();

    CREATE OR REPLACE FUNCTION article_source_item_guard() RETURNS trigger AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM article_source_packs WHERE id = OLD.source_pack_id AND status = 'confirmed')
      THEN RAISE EXCEPTION 'confirmed source item is immutable'; END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER article_source_items_guard BEFORE UPDATE OR DELETE ON article_source_items
      FOR EACH ROW EXECUTE FUNCTION article_source_item_guard();

    CREATE OR REPLACE FUNCTION article_job_guard() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'article jobs cannot be deleted'; END IF;
      IF NEW.article_id IS DISTINCT FROM OLD.article_id OR
         NEW.operation IS DISTINCT FROM OLD.operation OR
         NEW.subscription_id IS DISTINCT FROM OLD.subscription_id OR
         NEW.quota_hold_id IS DISTINCT FROM OLD.quota_hold_id OR
         NEW.source_pack_snapshot IS DISTINCT FROM OLD.source_pack_snapshot OR
         NEW.source_pack_digest IS DISTINCT FROM OLD.source_pack_digest OR
         NEW.input_snapshot IS DISTINCT FROM OLD.input_snapshot OR
         NEW.input_digest IS DISTINCT FROM OLD.input_digest OR
         NEW.provider_key IS DISTINCT FROM OLD.provider_key OR
         NEW.model_key IS DISTINCT FROM OLD.model_key OR
         NEW.provider_model_id IS DISTINCT FROM OLD.provider_model_id OR
         NEW.adapter_version IS DISTINCT FROM OLD.adapter_version OR
         NEW.prompt_version IS DISTINCT FROM OLD.prompt_version OR
         NEW.schema_version IS DISTINCT FROM OLD.schema_version OR
         NEW.idempotency_key_digest IS DISTINCT FROM OLD.idempotency_key_digest OR
         NEW.request_digest IS DISTINCT FROM OLD.request_digest OR
         NEW.request_id IS DISTINCT FROM OLD.request_id OR
         NEW.created_at IS DISTINCT FROM OLD.created_at
      THEN RAISE EXCEPTION 'article job provenance is immutable'; END IF;
      IF OLD.status IN ('succeeded', 'failed') THEN RAISE EXCEPTION 'terminal article job is immutable'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER article_generation_jobs_guard BEFORE UPDATE OR DELETE ON article_generation_jobs
      FOR EACH ROW EXECUTE FUNCTION article_job_guard();

    CREATE OR REPLACE FUNCTION article_ai_original_guard() RETURNS trigger AS $$
    BEGIN
      IF OLD.ai_original_content <> '' AND (
        NEW.ai_original_title IS DISTINCT FROM OLD.ai_original_title OR
        NEW.ai_original_content IS DISTINCT FROM OLD.ai_original_content OR
        NEW.ai_citations IS DISTINCT FROM OLD.ai_citations
      ) THEN RAISE EXCEPTION 'AI original article evidence is immutable'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER articles_ai_original_guard BEFORE UPDATE ON articles
      FOR EACH ROW EXECUTE FUNCTION article_ai_original_guard();
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [("articles", "0001_initial")]
    operations = [
        migrations.RunPython(seed_catalogs, migrations.RunPython.noop),
        migrations.RunPython(install_guards, migrations.RunPython.noop),
    ]
