import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def backfill_customer_ownership(apps, schema_editor):
    User = apps.get_model("users", "User")
    AdminProfile = apps.get_model("admin_rbac", "AdminProfile")
    CustomerAssignment = apps.get_model("admin_rbac", "CustomerAssignment")

    eligible = AdminProfile.objects.filter(
        user__is_superuser=False,
        role__isnull=False,
    ).order_by("created_at", "id")

    for customer in User.objects.filter(is_staff=False, is_superuser=False).order_by("id"):
        assignment = CustomerAssignment.objects.filter(customer_id=customer.pk).first()
        if (
            assignment is not None
            and assignment.owner_admin_id is not None
            and eligible.filter(pk=assignment.owner_admin_id).exists()
        ):
            continue

        candidates = list(eligible.filter(user__tenant_id=customer.tenant_id)[:2])
        if len(candidates) != 1:
            raise RuntimeError(
                "ADMIN ownership backfill requires exactly one eligible non-super ADMIN "
                f"for USER {customer.pk}; found {len(candidates)}."
            )
        owner = candidates[0]
        CustomerAssignment.objects.update_or_create(
            customer_id=customer.pk,
            defaults={
                "owner_admin_id": owner.pk,
                "assigned_by_id": None,
                "assigned_at": timezone.now(),
            },
        )

    invalid = User.objects.filter(is_staff=False, is_superuser=False).filter(
        models.Q(customer_assignment__isnull=True)
        | models.Q(customer_assignment__owner_admin__isnull=True)
        | models.Q(customer_assignment__owner_admin__user__is_superuser=True)
        | models.Q(customer_assignment__owner_admin__role__isnull=True)
    )
    if invalid.exists():
        raise RuntimeError("ADMIN ownership backfill left invalid or unowned USER records.")


def keep_backfilled_ownership(apps, schema_editor):
    # Ownership rows are valid business data and are intentionally retained on
    # schema rollback.  The following AlterField restores nullable compatibility.
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("admin_rbac", "0021_seed_stage3_operations_permissions"),
        ("users", "0011_tenant_user_tenant"),
    ]

    operations = [
        migrations.RunPython(backfill_customer_ownership, keep_backfilled_ownership),
        migrations.AlterField(
            model_name="customerassignment",
            name="owner_admin",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="customer_assignments",
                to="admin_rbac.adminprofile",
            ),
        ),
    ]
