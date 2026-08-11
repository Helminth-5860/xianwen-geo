from django.db import migrations


PERMISSIONS = (
    ("menu.admin.subject-risk", "\u4e3b\u4f53\u98ce\u9669\u5ba1\u6838\u83dc\u5355", "subject_risk", "menu", 89),
    ("subject_risk.catalog.view", "\u67e5\u770b\u4e3b\u4f53\u98ce\u9669\u76ee\u5f55", "subject_risk", "action", 970),
    ("subject_risk.catalog.update", "\u7ef4\u62a4\u4e3b\u4f53\u98ce\u9669\u8349\u7a3f", "subject_risk", "action", 980),
    ("subject_risk.catalog.publish", "\u53d1\u5e03\u4e3b\u4f53\u98ce\u9669\u76ee\u5f55", "subject_risk", "action", 990),
    ("subject_reviews.list", "\u4e3b\u4f53\u5ba1\u6838\u5217\u8868", "subject_risk", "action", 1000),
    ("subject_reviews.view", "\u4e3b\u4f53\u5ba1\u6838\u8be6\u60c5", "subject_risk", "action", 1010),
    ("subject_reviews.review", "\u5ba1\u6838\u4e3b\u4f53\u8d44\u6599", "subject_risk", "action", 1020),
)


def seed(apps, schema_editor):
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    RiskAction = apps.get_model("admin_rbac", "RiskAction")
    RiskPolicy = apps.get_model("admin_rbac", "RiskPolicy")
    for key, name, module, permission_type, sort_order in PERMISSIONS:
        Permission.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": module,
                "permission_type": permission_type,
                "description": "",
                "status": "active",
                "sort_order": sort_order,
                "superuser_only": False,
            },
        )
    action, _ = RiskAction.objects.update_or_create(
        key="subject_risk.catalog.publish",
        defaults={
            "name": "\u53d1\u5e03\u4e3b\u4f53\u98ce\u9669\u76ee\u5f55",
            "module": "subject_risk",
            "target_type": "subject_risk_catalog",
            "supported_modes": ["two_person"],
            "default_mode": "two_person",
            "minimum_mode": "two_person",
            "handler_key": "subject_risk.catalog.publish",
            "status": "active",
            "catalog_version": 7,
        },
    )
    RiskPolicy.objects.update_or_create(
        action=action,
        defaults={"current_mode": "two_person"},
    )


class Migration(migrations.Migration):
    dependencies = [("admin_rbac", "0016_seed_subject_catalog_permissions")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
