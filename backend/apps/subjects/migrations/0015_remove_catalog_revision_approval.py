from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0024_retire_multi_admin_approval"),
        ("subjects", "0014_remove_catalog_approval_binding"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="subjectriskcatalogrevision",
            name="approval_request",
        ),
    ]
