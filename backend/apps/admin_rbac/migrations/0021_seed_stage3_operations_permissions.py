from django.db import migrations

PERMISSIONS = (
    ("menu.admin.operations", "商用运营与发布菜单", "operations", "menu", 1140, False),
    ("operations.dashboard.view", "查看运营工作台", "operations", "action", 1150, False),
    ("operations.customers.view", "查看客户运营档案", "operations", "action", 1160, False),
    ("operations.customers.manage", "管理客户运营档案", "operations", "action", 1170, False),
    ("operations.tasks.view", "查看业务任务中心", "operations", "action", 1180, False),
    ("operations.tasks.manage", "执行安全任务操作", "operations", "action", 1190, False),
    ("operations.moderation.view", "查看内容审核队列", "operations", "action", 1200, False),
    ("operations.moderation.manage", "处理内容审核", "operations", "action", 1210, False),
    ("operations.announcements.manage", "管理公告", "operations", "action", 1220, False),
    ("operations.feedback.manage", "处理用户反馈", "operations", "action", 1230, False),
    ("operations.support_view", "发起只读协助查看", "operations", "action", 1240, False),
    ("operations.exports", "导出运营数据", "operations", "action", 1250, True),
    ("release.readiness.view", "查看发布就绪状态", "operations", "action", 1260, False),
    ("operations.alerts.view", "查看系统告警", "operations", "action", 1270, False),
    ("operations.alerts.manage", "确认和解决系统告警", "operations", "action", 1280, False),
    ("operations.backups.view", "查看备份与恢复证据", "operations", "action", 1290, False),
    ("operations.retention.view", "查看数据保留任务", "operations", "action", 1300, False),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    for key, name, module, permission_type, sort_order, superuser_only in PERMISSIONS:
        Permission.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": module,
                "permission_type": permission_type,
                "sort_order": sort_order,
                "superuser_only": superuser_only,
                "status": "active",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("admin_rbac", "0020_seed_api_credential_permission")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
