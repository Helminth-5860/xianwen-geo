from django.db import migrations


MODELS = (
    ("deepseek", "DeepSeek", "deepseek", "DeepSeek", 10),
    ("doubao", "豆包", "doubao", "豆包", 20),
    ("qwen", "通义千问", "qwen", "通义千问", 30),
    ("hunyuan", "腾讯混元", "hunyuan", "腾讯混元", 40),
    ("wenxin", "百度文心", "wenxin", "百度文心", 50),
    ("kimi", "Kimi", "kimi", "Kimi", 60),
    ("glm", "智谱 GLM", "glm", "智谱 GLM", 70),
    ("spark", "讯飞星火", "spark", "讯飞星火", 80),
)


def seed_models(apps, schema_editor):
    Provider = apps.get_model("ai", "AIProvider")
    Model = apps.get_model("ai", "AIModel")
    RuntimeConfig = apps.get_model("ai", "AIModelRuntimeConfig")
    for provider_key, provider_name, model_key, display_name, order in MODELS:
        provider, _ = Provider.objects.update_or_create(
            provider_key=provider_key,
            defaults={"canonical_name": provider_name, "is_builtin": True},
        )
        model, _ = Model.objects.update_or_create(
            model_key=model_key,
            defaults={
                "provider": provider,
                "canonical_display_name": display_name,
                "canonical_order": order,
                "purpose": "geo_detection",
                "is_builtin": True,
            },
        )
        RuntimeConfig.objects.get_or_create(model=model, defaults={"sort_order": order})


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION xw_ai_provider_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'built-in AI providers cannot be deleted';
    END IF;
    IF NEW.provider_key IS DISTINCT FROM OLD.provider_key
       OR NEW.canonical_name IS DISTINCT FROM OLD.canonical_name
       OR NEW.is_builtin IS DISTINCT FROM OLD.is_builtin THEN
        RAISE EXCEPTION 'built-in AI provider identity is immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ai_provider_guard
BEFORE UPDATE OR DELETE ON ai_providers
FOR EACH ROW EXECUTE FUNCTION xw_ai_provider_guard();

CREATE OR REPLACE FUNCTION xw_ai_model_guard() RETURNS trigger AS $$
DECLARE
    linked_provider_key varchar(100);
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'built-in AI models cannot be deleted';
    END IF;
    SELECT provider_key INTO linked_provider_key FROM ai_providers WHERE id = NEW.provider_id;
    IF linked_provider_key IS DISTINCT FROM NEW.model_key THEN
        RAISE EXCEPTION 'AI model/provider identity mismatch';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.provider_id IS DISTINCT FROM OLD.provider_id
        OR NEW.model_key IS DISTINCT FROM OLD.model_key
        OR NEW.canonical_display_name IS DISTINCT FROM OLD.canonical_display_name
        OR NEW.canonical_order IS DISTINCT FROM OLD.canonical_order
        OR NEW.purpose IS DISTINCT FROM OLD.purpose
        OR NEW.is_builtin IS DISTINCT FROM OLD.is_builtin
    ) THEN
        RAISE EXCEPTION 'built-in AI model identity is immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ai_model_guard
BEFORE INSERT OR UPDATE OR DELETE ON ai_models
FOR EACH ROW EXECUTE FUNCTION xw_ai_model_guard();

CREATE OR REPLACE FUNCTION xw_ai_runtime_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'built-in AI runtime configs cannot be deleted';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.model_id IS DISTINCT FROM OLD.model_id THEN
            RAISE EXCEPTION 'AI runtime model binding is immutable';
        END IF;
        IF NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'AI runtime version must increment by exactly one';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ai_runtime_guard
BEFORE UPDATE OR DELETE ON ai_model_runtime_configs
FOR EACH ROW EXECUTE FUNCTION xw_ai_runtime_guard();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS ai_runtime_guard ON ai_model_runtime_configs;
DROP FUNCTION IF EXISTS xw_ai_runtime_guard();
DROP TRIGGER IF EXISTS ai_model_guard ON ai_models;
DROP FUNCTION IF EXISTS xw_ai_model_guard();
DROP TRIGGER IF EXISTS ai_provider_guard ON ai_providers;
DROP FUNCTION IF EXISTS xw_ai_provider_guard();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def reverse_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("ai", "0001_initial")]
    operations = [
        migrations.RunPython(seed_models, migrations.RunPython.noop),
        migrations.RunPython(install_guards, reverse_guards),
    ]
