# XW-0112 code-owned catalog rows intentionally use a no-op reverse.

from django.db import migrations


PERMISSIONS = (
    ("menu.admin.subscriptions", "订阅管理菜单", "menu", 86),
    ("subscriptions.list", "订阅列表", "action", 800),
    ("subscriptions.view", "订阅详情", "action", 810),
    ("subscriptions.open", "开通正式订阅", "action", 820),
    ("subscriptions.grant_trial", "发放试用订阅", "action", 830),
    ("subscriptions.terminate", "终止订阅", "action", 840),
    ("subscriptions.override_version", "替换申请套餐版本", "action", 850),
)

ACTIONS = (
    ("subscription.open", "开通正式订阅", "plan_application"),
    ("subscription.grant_trial", "发放试用订阅", "user"),
    ("subscription.terminate", "终止订阅", "subscription"),
)


def seed(apps, schema_editor):
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    RiskAction = apps.get_model("admin_rbac", "RiskAction")
    RiskPolicy = apps.get_model("admin_rbac", "RiskPolicy")
    RiskAction.objects.update(catalog_version=4)
    for key, name, permission_type, sort_order in PERMISSIONS:
        Permission.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": "subscriptions",
                "permission_type": permission_type,
                "description": "",
                "status": "active",
                "sort_order": sort_order,
                "superuser_only": False,
            },
        )
    for key, name, target_type in ACTIONS:
        action, _ = RiskAction.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": "subscriptions",
                "target_type": target_type,
                "supported_modes": ["two_person"],
                "default_mode": "two_person",
                "minimum_mode": "two_person",
                "handler_key": key,
                "status": "active",
                "catalog_version": 4,
            },
        )
        policy, _ = RiskPolicy.objects.get_or_create(
            action=action,
            defaults={"current_mode": "two_person"},
        )
        if policy.current_mode != "two_person":
            policy.current_mode = "two_person"
            policy.version += 1
            policy.save(update_fields=["current_mode", "version", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0010_seed_plan_application_catalog"),
        ("plans", "0007_subscription_guards"),
        ("users", "0006_notification_related_subscription_and_more"),
    ]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
