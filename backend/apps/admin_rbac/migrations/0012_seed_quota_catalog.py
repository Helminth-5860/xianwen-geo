# XW-0113 code-owned quota catalog rows intentionally use a no-op reverse.

from django.db import migrations


PERMISSIONS = (
    ("menu.admin.quotas", "\u989d\u5ea6\u7ba1\u7406\u83dc\u5355", "menu", 87),
    ("quotas.list", "\u989d\u5ea6\u8d26\u6237\u5217\u8868", "action", 860),
    ("quotas.ledger.view", "\u989d\u5ea6\u6d41\u6c34\u67e5\u770b", "action", 870),
    ("quotas.adjust", "\u989d\u5ea6\u4eba\u5de5\u8c03\u6574", "action", 880),
)

ACTIONS = (
    ("quota.grant", "\u989d\u5ea6\u8d60\u9001"),
    ("quota.compensate", "\u989d\u5ea6\u8865\u507f"),
    ("quota.manual_deduct", "\u989d\u5ea6\u4eba\u5de5\u6263\u51cf"),
)


def seed(apps, schema_editor):
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    RiskAction = apps.get_model("admin_rbac", "RiskAction")
    RiskPolicy = apps.get_model("admin_rbac", "RiskPolicy")
    RiskAction.objects.update(catalog_version=5)
    for key, name, permission_type, sort_order in PERMISSIONS:
        Permission.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": "quotas",
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
                "module": "quotas",
                "target_type": "quota_account",
                "supported_modes": ["two_person"],
                "default_mode": "two_person",
                "minimum_mode": "two_person",
                "handler_key": key,
                "status": "active",
                "catalog_version": 5,
            },
        )
        policy, _ = RiskPolicy.objects.get_or_create(
            action=action, defaults={"current_mode": "two_person"}
        )
        if policy.current_mode != "two_person":
            policy.current_mode = "two_person"
            policy.version += 1
            policy.save(update_fields=["current_mode", "version", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0011_seed_subscription_catalog"),
        ("quotas", "0003_backfill_subscription_accounts"),
    ]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
