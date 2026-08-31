from django.db import migrations


def seed_quota_refund(apps, schema_editor):
    RiskAction = apps.get_model("admin_rbac", "RiskAction")
    RiskPolicy = apps.get_model("admin_rbac", "RiskPolicy")

    RiskAction.objects.update(catalog_version=9)
    action, _ = RiskAction.objects.update_or_create(
        key="quota.refund",
        defaults={
            "name": "额度返还",
            "module": "quotas",
            "target_type": "quota_account",
            "supported_modes": ["confirm"],
            "default_mode": "confirm",
            "minimum_mode": "confirm",
            "handler_key": "quota.refund",
            "status": "active",
            "catalog_version": 9,
        },
    )
    policy, _ = RiskPolicy.objects.get_or_create(
        action=action,
        defaults={"current_mode": "confirm"},
    )
    if policy.current_mode != "confirm":
        policy.current_mode = "confirm"
        policy.version += 1
        policy.save(update_fields=("current_mode", "version", "updated_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0027_allow_independent_users"),
        ("quotas", "0015_add_quota_refund_action"),
    ]

    operations = [migrations.RunPython(seed_quota_refund, migrations.RunPython.noop)]
