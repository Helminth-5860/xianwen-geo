from django.db import migrations

PERMISSIONS = (
    ("menu.admin.question-categories", "问题分类管理菜单", "question_catalog", "menu", 90),
    ("question_categories.list", "问题分类列表", "question_catalog", "action", 1030),
    ("question_categories.create", "创建问题分类", "question_catalog", "action", 1040),
    ("question_categories.update", "修改问题分类", "question_catalog", "action", 1050),
    ("question_categories.disable", "启停问题分类", "question_catalog", "action", 1060),
    ("question_tags.list", "问题辅助标签列表", "question_catalog", "action", 1070),
    ("question_tags.create", "创建问题辅助标签", "question_catalog", "action", 1080),
    ("question_tags.update", "修改问题辅助标签", "question_catalog", "action", 1090),
    ("question_tags.disable", "启停问题辅助标签", "question_catalog", "action", 1100),
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
    dependencies = [("admin_rbac", "0017_seed_subject_risk_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
