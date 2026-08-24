from django.db import migrations


DROP_APPROVAL_BINDING_SQL = r"""
DROP TRIGGER IF EXISTS subjects_catalog_revision_approval ON subject_risk_catalog_revisions;
DROP FUNCTION IF EXISTS subjects_assert_catalog_revision();
"""


def remove_approval_binding(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_APPROVAL_BINDING_SQL)


class Migration(migrations.Migration):
    dependencies = [("subjects", "0013_subject_enrichment_postgresql_guards")]

    operations = [
        migrations.RunPython(remove_approval_binding, migrations.RunPython.noop),
    ]
