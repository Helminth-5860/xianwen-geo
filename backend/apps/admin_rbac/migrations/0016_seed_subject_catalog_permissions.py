from django.db import migrations

PERMISSIONS = (
    ("menu.admin.subject-types", "主体类型管理菜单", "subject_types", "menu", 88),
    ("subject_types.list", "主体类型列表", "subject_types", "action", 890),
    ("subject_types.view", "主体类型详情", "subject_types", "action", 900),
    ("subject_types.create", "创建主体类型", "subject_types", "action", 910),
    ("subject_types.update", "修改主体类型", "subject_types", "action", 920),
    ("subject_types.disable", "启停主体类型", "subject_types", "action", 930),
    ("subject_fields.list", "主体字段列表", "subject_types", "action", 940),
    ("subject_fields.create", "创建主体字段", "subject_types", "action", 950),
    ("subject_fields.update", "修改主体字段", "subject_types", "action", 960),
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
    dependencies = [
        ("admin_rbac", "0015_approvalrequest_approval_single_pending_subscription_cancel")
    ]

    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
