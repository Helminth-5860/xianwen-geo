from django.db import migrations, models


CATALOG = (
    ("menu.admin.dashboard", "后台工作台", "admin", "menu", 10, False),
    ("menu.admin.users", "用户管理菜单", "users", "menu", 20, False),
    ("menu.admin.admins", "管理员菜单", "admins", "menu", 30, True),
    ("menu.admin.roles", "角色菜单", "roles", "menu", 40, False),
    ("admin.dashboard.view", "查看后台工作台", "admin", "action", 90, False),
    ("users.list", "用户列表", "users", "action", 100, False),
    ("users.view", "用户详情", "users", "action", 110, False),
    ("users.review", "用户审核", "users", "action", 120, False),
    ("users.freeze", "用户冻结", "users", "action", 130, False),
    ("users.history.view", "审核历史", "users", "action", 140, False),
    ("users.assign", "客户负责人分配", "users", "action", 150, False),
    ("notifications.view", "通知查看", "notifications", "action", 160, False),
    ("admins.list", "管理员列表", "admins", "action", 200, True),
    ("admins.view", "管理员详情", "admins", "action", 210, True),
    ("admins.create", "创建管理员", "admins", "action", 220, True),
    ("admins.update", "修改管理员", "admins", "action", 230, True),
    ("admins.disable", "管理员状态管理", "admins", "action", 240, True),
    ("roles.list", "角色列表", "roles", "action", 300, False),
    ("roles.view", "角色详情", "roles", "action", 310, False),
    ("roles.create", "创建角色", "roles", "action", 320, True),
    ("roles.update", "修改角色", "roles", "action", 330, True),
    ("roles.disable", "停用角色", "roles", "action", 340, True),
)


def seed(apps, schema_editor):
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    Profile = apps.get_model("admin_rbac", "AdminProfile")
    User = apps.get_model("users", "User")
    for key, name, module, permission_type, sort_order, superuser_only in CATALOG:
        Permission.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": module,
                "permission_type": permission_type,
                "description": "",
                "status": "active",
                "sort_order": sort_order,
                "superuser_only": superuser_only,
            },
        )
    for user in User.objects.filter(is_staff=True):
        Profile.objects.update_or_create(
            user=user,
            defaults={
                "admin_status": "active" if user.is_superuser else "disabled",
                "role": None,
            },
        )

    User.objects.filter(is_staff=True, is_superuser=False).update(
        is_staff=False, session_version=models.F("session_version") + 1
    )


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0001_initial"),
        ("users", "0003_user_approved_by_user_session_version_and_more"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
