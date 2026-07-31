from django.db import migrations


def create_superuser_policies(apps, schema_editor):
    User = apps.get_model("users", "User")
    Policy = apps.get_model("admin_rbac", "SuperuserSecurityPolicy")
    for user_id in User.objects.filter(is_superuser=True).values_list("id", flat=True):
        Policy.objects.get_or_create(user_id=user_id)


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0004_adminsecurityevent_roleipallowlistentry_and_more"),
        ("users", "0003_user_approved_by_user_session_version_and_more"),
    ]

    operations = [
        migrations.RunPython(create_superuser_policies, migrations.RunPython.noop),
    ]
