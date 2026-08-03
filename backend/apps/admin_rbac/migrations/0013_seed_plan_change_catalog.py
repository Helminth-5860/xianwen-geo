# XW-0114 code-owned permission and risk rows intentionally use a no-op reverse.

from django.db import migrations


def seed(apps, schema_editor):
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    RiskAction = apps.get_model("admin_rbac", "RiskAction")
    RiskPolicy = apps.get_model("admin_rbac", "RiskPolicy")
    RiskAction.objects.update(catalog_version=6)
    Permission.objects.update_or_create(
        key="subscriptions.change",
        defaults={
            "name": "变更或取消订阅套餐",
            "module": "subscriptions",
            "permission_type": "action",
            "description": "",
            "status": "active",
            "sort_order": 855,
            "superuser_only": False,
        },
    )
    actions = (
        ("subscription.change", "变更订阅套餐", "subscription"),
        ("subscription.change.cancel", "取消订阅续费排期", "subscription_change"),
    )
    for key, name, target_type in actions:
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
                "catalog_version": 6,
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
    dependencies = [("admin_rbac", "0012_seed_quota_catalog")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
