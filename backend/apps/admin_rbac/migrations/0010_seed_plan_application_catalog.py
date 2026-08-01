# XW-0111 code-owned catalog rows intentionally use a no-op reverse.

from django.db import migrations


PERMISSIONS = (
    ("menu.admin.plan-applications", "套餐申请菜单", "menu", 85),
    ("plan_applications.list", "套餐申请列表", "action", 760),
    ("plan_applications.view", "套餐申请详情", "action", 770),
    ("plan_applications.contact", "联系套餐申请", "action", 780),
    ("plan_applications.close", "关闭套餐申请", "action", 790),
)

ACTIONS = (
    ("plan_application.contact", "联系套餐申请"),
    ("plan_application.close", "关闭套餐申请"),
)


def seed(apps, schema_editor):
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    RiskAction = apps.get_model("admin_rbac", "RiskAction")
    RiskPolicy = apps.get_model("admin_rbac", "RiskPolicy")
    RiskAction.objects.update(catalog_version=3)
    for key, name, permission_type, sort_order in PERMISSIONS:
        Permission.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": "plan_applications",
                "permission_type": permission_type,
                "description": "",
                "status": "active",
                "sort_order": sort_order,
                "superuser_only": False,
            },
        )
    for key, name in ACTIONS:
        action, _ = RiskAction.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": "plan_applications",
                "target_type": "plan_application",
                "supported_modes": ["confirm", "password", "two_person"],
                "default_mode": "confirm",
                "minimum_mode": "confirm",
                "handler_key": key,
                "status": "active",
                "catalog_version": 3,
            },
        )
        RiskPolicy.objects.get_or_create(action=action, defaults={"current_mode": "confirm"})


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0009_seed_plan_catalog"),
        ("plans", "0005_plan_application_guards"),
    ]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
