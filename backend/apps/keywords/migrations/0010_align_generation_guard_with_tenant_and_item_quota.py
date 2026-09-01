from importlib import import_module

from django.db import migrations


_previous = import_module(
    "apps.keywords.migrations.0008_keyword_center_metadata_and_assets"
)
PREVIOUS_GENERATION_GUARD_SQL = _previous.GENERATION_GUARD_SQL


def _replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError("关键词生成数据库校验规则无法安全升级。")
    return source.replace(old, new, 1)


GENERATION_GUARD_SQL = PREVIOUS_GENERATION_GUARD_SQL
GENERATION_GUARD_SQL = _replace_once(
    GENERATION_GUARD_SQL,
    """    v_subject_user uuid;
    v_subject_current uuid;
""",
    """    v_subject_user uuid;
    v_subject_tenant uuid;
    v_user_tenant uuid;
    v_subject_current uuid;
""",
)
GENERATION_GUARD_SQL = _replace_once(
    GENERATION_GUARD_SQL,
    """    SELECT user_id, current_version_id
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
""",
    """    SELECT user_id, tenant_id, current_version_id
      INTO v_subject_user, v_subject_tenant, v_subject_current
      FROM subjects WHERE id = NEW.subject_id;
    SELECT tenant_id INTO v_user_tenant
      FROM users WHERE id = NEW.user_id;
    SELECT subject_id INTO v_subject_version_subject
      FROM subject_versions WHERE id = NEW.subject_version_id;
    SELECT user_id INTO v_subscription_user
      FROM subscriptions WHERE id = NEW.subscription_id;
    IF v_subject_user IS NULL
       OR (
           v_subject_tenant IS NULL
           AND v_subject_user <> NEW.user_id
       )
       OR (
           v_subject_tenant IS NOT NULL
           AND (v_user_tenant IS NULL OR v_user_tenant <> v_subject_tenant)
       )
       OR (
           TG_OP = 'INSERT'
           AND (v_subject_current IS NULL OR v_subject_current <> NEW.subject_version_id)
       )
""",
)
GENERATION_GUARD_SQL = _replace_once(
    GENERATION_GUARD_SQL,
    """           OR v_hold.quota_type <> 'keyword_regenerations'
           OR v_hold.business_type <> 'keyword_generation'
           OR v_hold.business_id <> NEW.id OR v_hold.requested_amount <> 1 THEN
""",
    """           OR v_hold.quota_type <> 'keyword_generated_items'
           OR v_hold.business_type <> 'keyword_generation'
           OR v_hold.business_id <> NEW.id
           OR v_hold.requested_amount <> NEW.target_count THEN
""",
)
GENERATION_GUARD_SQL = _replace_once(
    GENERATION_GUARD_SQL,
    """            IF v_hold.status <> 'settled' OR v_hold.consumed_amount <> 1
               OR v_hold.released_amount <> 0 THEN
""",
    """            IF v_hold.status <> 'settled'
               OR v_hold.consumed_amount + v_hold.released_amount
                  <> v_hold.requested_amount THEN
""",
)
GENERATION_GUARD_SQL = _replace_once(
    GENERATION_GUARD_SQL,
    """            IF v_hold.status <> 'settled' OR v_hold.consumed_amount <> 0
               OR v_hold.released_amount <> 1 THEN
""",
    """            IF v_hold.status <> 'settled' OR v_hold.consumed_amount <> 0
               OR v_hold.released_amount <> v_hold.requested_amount THEN
""",
)


def install_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GENERATION_GUARD_SQL)


def restore_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(PREVIOUS_GENERATION_GUARD_SQL)


class Migration(migrations.Migration):
    dependencies = [("keywords", "0009_fix_distillation_free_initial_guard")]

    operations = [migrations.RunPython(install_guard, restore_guard)]
