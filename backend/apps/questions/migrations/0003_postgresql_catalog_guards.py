# ruff: noqa: E501
from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION questions_catalog_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.is_builtin THEN
            RAISE EXCEPTION 'QUESTION_CATALOG_BUILTIN_DELETE_FORBIDDEN';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.key IS DISTINCT FROM OLD.key
       OR NEW.is_builtin IS DISTINCT FROM OLD.is_builtin THEN
        RAISE EXCEPTION 'QUESTION_CATALOG_IDENTITY_IMMUTABLE';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'QUESTION_CATALOG_VERSION_INVALID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS questions_category_guard_trg ON question_categories;
CREATE TRIGGER questions_category_guard_trg
BEFORE UPDATE OR DELETE ON question_categories
FOR EACH ROW EXECUTE FUNCTION questions_catalog_guard();

DROP TRIGGER IF EXISTS questions_tag_guard_trg ON question_tags;
CREATE TRIGGER questions_tag_guard_trg
BEFORE UPDATE OR DELETE ON question_tags
FOR EACH ROW EXECUTE FUNCTION questions_catalog_guard();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS questions_tag_guard_trg ON question_tags;
DROP TRIGGER IF EXISTS questions_category_guard_trg ON question_categories;
DROP FUNCTION IF EXISTS questions_catalog_guard();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("questions", "0002_seed_builtin_categories")]
    operations = [migrations.RunPython(install, reverse)]
