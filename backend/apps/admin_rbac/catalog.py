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
    CatalogPermission("menu.admin.audit", "操作记录菜单", "audit", "menu", 60, True),
    CatalogPermission("menu.admin.risk-policies", "风险策略菜单", "risk", "menu", 70, True),
    CatalogPermission("menu.admin.plans", "套餐管理菜单", "plans", "menu", 80),
    CatalogPermission(
        "menu.admin.plan-applications", "套餐申请菜单", "plan_applications", "menu", 85
    ),
    CatalogPermission("admin.dashboard.view", "查看后台工作台", "admin", "action", 90),
    CatalogPermission("users.list", "用户列表", "users", "action", 100),
    CatalogPermission("users.view", "用户详情", "users", "action", 110),
    CatalogPermission("users.freeze", "禁用或恢复用户", "users", "action", 130),
    CatalogPermission("users.history.view", "账号变更记录", "users", "action", 140),
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
    CatalogPermission("audit.list", "操作记录列表", "audit", "action", 500, True),
    CatalogPermission("audit.view", "操作记录详情", "audit", "action", 510, True),
    CatalogPermission("risk_policy.view", "风险策略查看", "risk", "action", 520, True),
    CatalogPermission("risk_policy.update", "风险策略修改", "risk", "action", 530, True),
    CatalogPermission("plans.list", "套餐列表", "plans", "action", 600),
    CatalogPermission("plans.view", "套餐详情", "plans", "action", 610),
    CatalogPermission("plans.create", "创建套餐", "plans", "action", 620),
    CatalogPermission("plans.update", "修改套餐资料", "plans", "action", 630),
    CatalogPermission("plans.copy", "复制套餐", "plans", "action", 640),
    CatalogPermission("plans.online", "上架套餐", "plans", "action", 650),
    CatalogPermission("plans.offline", "下架套餐", "plans", "action", 660),
    CatalogPermission("plans.archive", "归档套餐", "plans", "action", 670),
    CatalogPermission("plan_versions.list", "套餐版本列表", "plans", "action", 680),
    CatalogPermission("plan_versions.view", "套餐版本详情", "plans", "action", 690),
    CatalogPermission("plan_versions.create", "创建套餐版本", "plans", "action", 700),
    CatalogPermission("plan_versions.update", "修改套餐草稿版本", "plans", "action", 710),
    CatalogPermission("plan_versions.publish", "发布套餐版本", "plans", "action", 720),
    CatalogPermission("plan_versions.retire", "退役套餐版本", "plans", "action", 730),
    CatalogPermission("plan_limits.view", "查看套餐限制", "plans", "action", 740),
    CatalogPermission("plan_limits.update", "修改套餐限制", "plans", "action", 750),
    CatalogPermission("plan_applications.list", "套餐申请列表", "plan_applications", "action", 760),
    CatalogPermission("plan_applications.view", "套餐申请详情", "plan_applications", "action", 770),
    CatalogPermission(
        "plan_applications.contact", "联系套餐申请", "plan_applications", "action", 780
    ),
    CatalogPermission(
        "plan_applications.close", "关闭套餐申请", "plan_applications", "action", 790
    ),
    CatalogPermission("menu.admin.subscriptions", "订阅管理菜单", "subscriptions", "menu", 86),
    CatalogPermission("subscriptions.list", "订阅列表", "subscriptions", "action", 800),
    CatalogPermission("subscriptions.view", "订阅详情", "subscriptions", "action", 810),
    CatalogPermission("subscriptions.open", "开通正式订阅", "subscriptions", "action", 820),
    CatalogPermission("subscriptions.grant_trial", "发放试用订阅", "subscriptions", "action", 830),
    CatalogPermission("subscriptions.terminate", "终止订阅", "subscriptions", "action", 840),
    CatalogPermission(
        "subscriptions.override_version", "替换申请套餐版本", "subscriptions", "action", 850
    ),
    CatalogPermission("subscriptions.change", "变更或取消订阅套餐", "subscriptions", "action", 855),
    CatalogPermission(
        "menu.admin.quotas", "\u989d\u5ea6\u7ba1\u7406\u83dc\u5355", "quotas", "menu", 87
    ),
    CatalogPermission(
        "quotas.list", "\u989d\u5ea6\u8d26\u6237\u5217\u8868", "quotas", "action", 860
    ),
    CatalogPermission(
        "quotas.ledger.view", "\u989d\u5ea6\u6d41\u6c34\u67e5\u770b", "quotas", "action", 870
    ),
    CatalogPermission(
        "quotas.adjust", "\u989d\u5ea6\u4eba\u5de5\u8c03\u6574", "quotas", "action", 880
    ),
    CatalogPermission("menu.admin.subject-types", "主体类型管理菜单", "subject_types", "menu", 88),
    CatalogPermission("subject_types.list", "主体类型列表", "subject_types", "action", 890),
    CatalogPermission("subject_types.view", "主体类型详情", "subject_types", "action", 900),
    CatalogPermission("subject_types.create", "创建主体类型", "subject_types", "action", 910),
    CatalogPermission("subject_types.update", "修改主体类型", "subject_types", "action", 920),
    CatalogPermission("subject_types.disable", "启停主体类型", "subject_types", "action", 930),
    CatalogPermission("subject_fields.list", "主体字段列表", "subject_types", "action", 940),
    CatalogPermission("subject_fields.create", "创建主体字段", "subject_types", "action", 950),
    CatalogPermission("subject_fields.update", "修改主体字段", "subject_types", "action", 960),
    CatalogPermission(
        "menu.admin.subject-risk",
        "\u4e3b\u4f53\u98ce\u9669\u5ba1\u6838\u83dc\u5355",
        "subject_risk",
        "menu",
        89,
    ),
    CatalogPermission(
        "subject_risk.catalog.view",
        "\u67e5\u770b\u4e3b\u4f53\u98ce\u9669\u76ee\u5f55",
        "subject_risk",
        "action",
        970,
    ),
    CatalogPermission(
        "subject_risk.catalog.update",
        "\u7ef4\u62a4\u4e3b\u4f53\u98ce\u9669\u8349\u7a3f",
        "subject_risk",
        "action",
        980,
    ),
    CatalogPermission(
        "subject_risk.catalog.publish",
        "\u53d1\u5e03\u4e3b\u4f53\u98ce\u9669\u76ee\u5f55",
        "subject_risk",
        "action",
        990,
    ),
    CatalogPermission(
        "subject_reviews.list",
        "\u4e3b\u4f53\u5ba1\u6838\u5217\u8868",
        "subject_risk",
        "action",
        1000,
    ),
    CatalogPermission(
        "subject_reviews.view",
        "\u4e3b\u4f53\u5ba1\u6838\u8be6\u60c5",
        "subject_risk",
        "action",
        1010,
    ),
    CatalogPermission(
        "subject_reviews.review",
        "\u5ba1\u6838\u4e3b\u4f53\u8d44\u6599",
        "subject_risk",
        "action",
        1020,
    ),
    CatalogPermission(
        "menu.admin.question-categories",
        "问题分类管理菜单",
        "question_catalog",
        "menu",
        90,
    ),
    CatalogPermission(
        "question_categories.list", "问题分类列表", "question_catalog", "action", 1030
    ),
    CatalogPermission(
        "question_categories.create", "创建问题分类", "question_catalog", "action", 1040
    ),
    CatalogPermission(
        "question_categories.update", "修改问题分类", "question_catalog", "action", 1050
    ),
    CatalogPermission(
        "question_categories.disable", "启停问题分类", "question_catalog", "action", 1060
    ),
    CatalogPermission("question_tags.list", "问题辅助标签列表", "question_catalog", "action", 1070),
    CatalogPermission(
        "question_tags.create", "创建问题辅助标签", "question_catalog", "action", 1080
    ),
    CatalogPermission(
        "question_tags.update", "修改问题辅助标签", "question_catalog", "action", 1090
    ),
    CatalogPermission(
        "question_tags.disable", "启停问题辅助标签", "question_catalog", "action", 1100
    ),
    CatalogPermission("menu.admin.models", "模型运行配置菜单", "models", "menu", 91),
    CatalogPermission("models.list", "模型运行配置列表", "models", "action", 1110),
    CatalogPermission("models.manage", "管理模型运行配置", "models", "action", 1120),
    CatalogPermission(
        "api_credentials.manage", "管理模型 API 密钥", "models", "action", 1130, True
    ),
    CatalogPermission("menu.admin.operations", "商用运营与发布菜单", "operations", "menu", 1140),
    CatalogPermission("operations.dashboard.view", "查看运营工作台", "operations", "action", 1150),
    CatalogPermission(
        "operations.customers.view", "查看客户运营档案", "operations", "action", 1160
    ),
    CatalogPermission(
        "operations.customers.manage", "管理客户运营档案", "operations", "action", 1170
    ),
    CatalogPermission("operations.tasks.view", "查看业务任务中心", "operations", "action", 1180),
    CatalogPermission("operations.tasks.manage", "执行安全任务操作", "operations", "action", 1190),
    CatalogPermission(
        "operations.moderation.view", "查看内容审核队列", "operations", "action", 1200
    ),
    CatalogPermission("operations.moderation.manage", "处理内容审核", "operations", "action", 1210),
    CatalogPermission("operations.announcements.manage", "管理公告", "operations", "action", 1220),
    CatalogPermission("operations.feedback.manage", "处理用户反馈", "operations", "action", 1230),
    CatalogPermission("operations.support_view", "发起只读协助查看", "operations", "action", 1240),
    CatalogPermission("operations.exports", "导出运营数据", "operations", "action", 1250, True),
    CatalogPermission("release.readiness.view", "查看发布就绪状态", "operations", "action", 1260),
    CatalogPermission("operations.alerts.view", "查看系统告警", "operations", "action", 1270),
    CatalogPermission(
        "operations.alerts.manage", "确认和解决系统告警", "operations", "action", 1280
    ),
    CatalogPermission(
        "operations.backups.view", "查看备份与恢复证据", "operations", "action", 1290
    ),
    CatalogPermission(
        "operations.retention.view", "查看数据保留任务", "operations", "action", 1300
    ),
)

CATALOG_BY_KEY = {item.key: item for item in PERMISSION_CATALOG}
