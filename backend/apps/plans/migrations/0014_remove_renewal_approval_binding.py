from django.db import migrations


DROP_APPROVAL_BINDING_SQL = r"""
DROP TRIGGER IF EXISTS plans_renewal_approval_binding ON subscription_changes;
DROP FUNCTION IF EXISTS plans_validate_renewal_approval();
"""


def remove_approval_binding(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_APPROVAL_BINDING_SQL)


class Migration(migrations.Migration):
    dependencies = [("plans", "0013_lifecycle_postgresql_guards")]

    operations = [
        migrations.RunPython(remove_approval_binding, migrations.RunPython.noop),
    ]
