from django.db import migrations


def remove_user_account_review_catalog(apps, schema_editor):
    AdminPermission = apps.get_model("admin_rbac", "AdminPermission")
    AdminRolePermission = apps.get_model("admin_rbac", "AdminRolePermission")
    RiskAction = apps.get_model("admin_rbac", "RiskAction")
    RiskPolicy = apps.get_model("admin_rbac", "RiskPolicy")

    AdminRolePermission.objects.filter(permission__key="users.review").delete()
    AdminPermission.objects.filter(key="users.review").delete()
    RiskPolicy.objects.filter(action_id="user.review.reject").delete()
    RiskAction.objects.filter(key="user.review.reject").delete()
    AdminPermission.objects.filter(key="users.freeze").update(name="禁用或恢复用户")
    AdminPermission.objects.filter(key="users.history.view").update(name="账号变更记录")
    RiskAction.objects.filter(key="user.freeze").update(name="禁用用户")


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0025_remove_multi_admin_approval_schema"),
    ]

    operations = [
        migrations.RunPython(remove_user_account_review_catalog, migrations.RunPython.noop),
    ]
