# Generated for XW-0107. Catalog rows are code-owned and intentionally not reversed.

from django.db import migrations


ACTIONS = (
    ("admin.disable", "停用管理员", "admins", "admin_profile", ["password", "two_person"], "two_person", "password", "admin.disable"),
    ("admin.lock", "锁定管理员", "admins", "admin_profile", ["password", "two_person"], "password", "password", "admin.lock"),
    ("admin.role.change", "变更管理员角色", "admins", "admin_profile", ["password", "two_person"], "two_person", "password", "admin.role.change"),
    ("admin.force_logout", "强制管理员退出", "admins", "admin_profile", ["confirm", "password", "two_person"], "confirm", "confirm", "admin.force_logout"),
    ("role.permissions.replace", "替换角色权限", "roles", "admin_role", ["two_person"], "two_person", "two_person", "role.permissions.replace"),
    ("role.disable", "停用角色", "roles", "admin_role", ["password", "two_person"], "password", "password", "role.disable"),
    ("role.security.update", "更新角色登录安全策略", "roles", "admin_role", ["password"], "password", "password", "role.security.update"),
    ("role.ip_allowlist.update", "更新角色 IP 白名单", "roles", "admin_role", ["password"], "password", "password", "role.ip_allowlist.update"),
    ("superuser.ip_allowlist.update", "更新超级管理员 IP 白名单", "security", "superuser_policy", ["password"], "password", "password", "superuser.ip_allowlist.update"),
    ("customer.assignment.change", "变更客户负责人", "users", "customer_assignment", ["confirm", "password", "two_person"], "password", "confirm", "customer.assignment.change"),
    ("user.freeze", "冻结用户", "users", "user", ["confirm", "password", "two_person"], "confirm", "confirm", "user.freeze"),
    ("user.review.reject", "拒绝用户审核", "users", "user", ["confirm", "password", "two_person"], "confirm", "confirm", "user.review.reject"),
)

PERMISSIONS = (
    ("menu.admin.approvals", "高风险审批菜单", "approvals", "menu", 50, False),
    ("menu.admin.audit", "统一审计菜单", "audit", "menu", 60, True),
    ("menu.admin.risk-policies", "风险策略菜单", "risk", "menu", 70, True),
    ("approvals.list", "审批列表", "approvals", "action", 400, False),
    ("approvals.view", "审批详情", "approvals", "action", 410, False),
    ("approvals.request", "发起高风险审批", "approvals", "action", 420, False),
    ("approvals.approve", "批准高风险操作", "approvals", "action", 430, True),
    ("approvals.reject", "拒绝高风险操作", "approvals", "action", 440, True),
    ("approvals.cancel", "取消本人审批", "approvals", "action", 450, False),
    ("audit.list", "统一审计列表", "audit", "action", 500, True),
    ("audit.view", "统一审计详情", "audit", "action", 510, True),
    ("risk_policy.view", "风险策略查看", "risk", "action", 520, True),
    ("risk_policy.update", "风险策略修改", "risk", "action", 530, True),
)


def seed(apps, schema_editor):
    RiskAction = apps.get_model("admin_rbac", "RiskAction")
    RiskPolicy = apps.get_model("admin_rbac", "RiskPolicy")
    Permission = apps.get_model("admin_rbac", "AdminPermission")
    for key, name, module, target_type, supported, default, minimum, handler in ACTIONS:
        action, _ = RiskAction.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "module": module,
                "target_type": target_type,
                "supported_modes": supported,
                "default_mode": default,
                "minimum_mode": minimum,
                "handler_key": handler,
                "status": "active",
                "catalog_version": 1,
            },
        )
        RiskPolicy.objects.get_or_create(action=action, defaults={"current_mode": default})
    for key, name, module, permission_type, sort_order, superuser_only in PERMISSIONS:
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


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0006_riskaction_approvalrequest_riskpolicy_auditevent_and_more"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
