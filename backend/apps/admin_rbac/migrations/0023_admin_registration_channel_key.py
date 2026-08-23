import uuid

from django.db import migrations, models


def populate_registration_channel_keys(apps, schema_editor):
    AdminProfile = apps.get_model("admin_rbac", "AdminProfile")
    for profile in AdminProfile.objects.filter(registration_channel_key__isnull=True).iterator():
        profile.registration_channel_key = uuid.uuid4()
        profile.save(update_fields=["registration_channel_key"])


def clear_registration_channel_keys(apps, schema_editor):
    AdminProfile = apps.get_model("admin_rbac", "AdminProfile")
    AdminProfile.objects.update(registration_channel_key=None)


class Migration(migrations.Migration):

    dependencies = [
        ("admin_rbac", "0022_enforce_admin_customer_ownership"),
    ]

    operations = [
        migrations.AddField(
            model_name="adminprofile",
            name="registration_channel_key",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(
            populate_registration_channel_keys,
            clear_registration_channel_keys,
        ),
        migrations.AlterField(
            model_name="adminprofile",
            name="registration_channel_key",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
