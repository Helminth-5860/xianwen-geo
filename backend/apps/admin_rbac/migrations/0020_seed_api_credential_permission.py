from django.db import migrations


PERMISSION = (
    "api_credentials.manage",
    "管理模型 API 密钥",
    "models",
    "action",
    1130,
    True,
)


def seed_permission(apps, schema_editor):
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    key, name, module, permission_type, sort_order, superuser_only = PERMISSION
    Permission.objects.get_or_create(
        key=key,
        defaults={
            "name": name,
            "module": module,
            "permission_type": permission_type,
            "sort_order": sort_order,
            "superuser_only": superuser_only,
            "status": "active",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("admin_rbac", "0019_seed_ai_model_permissions")]
    operations = [migrations.RunPython(seed_permission, migrations.RunPython.noop)]
