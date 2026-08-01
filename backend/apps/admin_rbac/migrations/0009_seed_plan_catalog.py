# Generated for XW-0110. Code-owned catalog rows are intentionally not reversed.

from django.db import migrations


ACTIONS = (
    ("plan.create", "创建套餐", "plan", ["confirm", "password", "two_person"], "confirm", "confirm"),
    ("plan.update", "修改套餐", "plan", ["confirm", "password", "two_person"], "confirm", "confirm"),
    ("plan.version.create", "创建套餐版本", "plan_version", ["confirm", "password", "two_person"], "confirm", "confirm"),
    ("plan.version.update", "修改套餐版本", "plan_version", ["confirm", "password", "two_person"], "confirm", "confirm"),
    ("plan.version.publish", "发布套餐版本", "plan_version", ["password", "two_person"], "password", "password"),
    ("plan.online", "上架套餐", "plan", ["password", "two_person"], "password", "password"),
    ("plan.offline", "下架套餐", "plan", ["password", "two_person"], "password", "password"),
    ("plan.version.retire", "退役套餐版本", "plan_version", ["password", "two_person"], "password", "password"),
    ("plan.archive", "归档套餐", "plan", ["password", "two_person"], "two_person", "password"),
    ("plan.copy", "复制套餐", "plan", ["confirm", "password", "two_person"], "confirm", "confirm"),
)

PERMISSIONS = (
    ("menu.admin.plans", "套餐管理菜单", "menu", 80),
    ("plans.list", "套餐列表", "action", 600),
    ("plans.view", "套餐详情", "action", 610),
    ("plans.create", "创建套餐", "action", 620),
    ("plans.update", "修改套餐资料", "action", 630),
    ("plans.copy", "复制套餐", "action", 640),
    ("plans.online", "上架套餐", "action", 650),
    ("plans.offline", "下架套餐", "action", 660),
    ("plans.archive", "归档套餐", "action", 670),
    ("plan_versions.list", "套餐版本列表", "action", 680),
    ("plan_versions.view", "套餐版本详情", "action", 690),
    ("plan_versions.create", "创建套餐版本", "action", 700),
    ("plan_versions.update", "修改套餐草稿版本", "action", 710),
    ("plan_versions.publish", "发布套餐版本", "action", 720),
    ("plan_versions.retire", "退役套餐版本", "action", 730),
    ("plan_limits.view", "查看套餐限制", "action", 740),
    ("plan_limits.update", "修改套餐限制", "action", 750),
)


def seed(apps, schema_editor):
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    RiskAction = apps.get_model("admin_rbac", "RiskAction")
    RiskPolicy = apps.get_model("admin_rbac", "RiskPolicy")
    RiskAction.objects.update(catalog_version=2)
    for key, name, target_type, supported, default, minimum in ACTIONS:
        action, _ = RiskAction.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": "plans",
                "target_type": target_type,
                "supported_modes": supported,
                "default_mode": default,
                "minimum_mode": minimum,
                "handler_key": key,
                "status": "active",
                "catalog_version": 2,
            },
        )
        RiskPolicy.objects.get_or_create(action=action, defaults={"current_mode": default})
    for key, name, permission_type, sort_order in PERMISSIONS:
        Permission.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": "plans",
                "permission_type": permission_type,
                "description": "",
                "status": "active",
                "sort_order": sort_order,
                "superuser_only": False,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0008_approvalrequest_approval_requester_not_rejecter_and_more"),
        ("plans", "0003_postgresql_immutability_triggers"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
