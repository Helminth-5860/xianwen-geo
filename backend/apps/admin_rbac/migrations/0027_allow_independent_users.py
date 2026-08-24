import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def ensure_assignment_rows(apps, schema_editor):
    User = apps.get_model("users", "User")
    CustomerAssignment = apps.get_model("admin_rbac", "CustomerAssignment")

    assigned_ids = CustomerAssignment.objects.values_list("customer_id", flat=True)
    missing_ids = (
        User.objects.filter(
            is_staff=False,
            is_superuser=False,
        )
        .exclude(pk__in=assigned_ids)
        .values_list("pk", flat=True)
    )
    CustomerAssignment.objects.bulk_create(
        [CustomerAssignment(customer_id=user_id) for user_id in missing_ids],
        batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0026_remove_user_account_review_catalog"),
        ("users", "0012_remove_account_review"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customerassignment",
            name="owner_admin",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="customer_assignments",
                to="admin_rbac.adminprofile",
            ),
        ),
        migrations.RunPython(ensure_assignment_rows, migrations.RunPython.noop),
    ]
