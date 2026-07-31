from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogPermission:
    key: str
    name: str
    module: str
    permission_type: str
    sort_order: int
    superuser_only: bool = False


PERMISSION_CATALOG = (
    CatalogPermission("menu.admin.dashboard", "后台工作台", "admin", "menu", 10),
    CatalogPermission("menu.admin.users", "用户管理菜单", "users", "menu", 20),
    CatalogPermission("menu.admin.admins", "管理员菜单", "admins", "menu", 30, True),
    CatalogPermission("menu.admin.roles", "角色菜单", "roles", "menu", 40),
    CatalogPermission("admin.dashboard.view", "查看后台工作台", "admin", "action", 90),
    CatalogPermission("users.list", "用户列表", "users", "action", 100),
    CatalogPermission("users.view", "用户详情", "users", "action", 110),
    CatalogPermission("users.review", "用户审核", "users", "action", 120),
    CatalogPermission("users.freeze", "用户冻结", "users", "action", 130),
    CatalogPermission("users.history.view", "审核历史", "users", "action", 140),
    CatalogPermission("users.assign", "客户负责人分配", "users", "action", 150),
    CatalogPermission("notifications.view", "通知查看", "notifications", "action", 160),
    CatalogPermission("admins.list", "管理员列表", "admins", "action", 200, True),
    CatalogPermission("admins.view", "管理员详情", "admins", "action", 210, True),
    CatalogPermission("admins.create", "创建管理员", "admins", "action", 220, True),
    CatalogPermission("admins.update", "修改管理员", "admins", "action", 230, True),
    CatalogPermission("admins.disable", "管理员状态管理", "admins", "action", 240, True),
    CatalogPermission("roles.list", "角色列表", "roles", "action", 300),
    CatalogPermission("roles.view", "角色详情", "roles", "action", 310),
    CatalogPermission("roles.create", "创建角色", "roles", "action", 320, True),
    CatalogPermission("roles.update", "修改角色", "roles", "action", 330, True),
    CatalogPermission("roles.disable", "停用角色", "roles", "action", 340, True),
)

CATALOG_BY_KEY = {item.key: item for item in PERMISSION_CATALOG}
