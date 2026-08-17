from django.db import migrations


PERMISSIONS = (
    ("menu.admin.models", "模型运行配置菜单", "models", "menu", 91),
    ("models.list", "模型运行配置列表", "models", "action", 1110),
    ("models.manage", "管理模型运行配置", "models", "action", 1120),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    for key, name, module, permission_type, sort_order in PERMISSIONS:
        Permission.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "module": module,
                "permission_type": permission_type,
                "sort_order": sort_order,
                "superuser_only": False,
                "status": "active",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("admin_rbac", "0018_seed_question_catalog_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
