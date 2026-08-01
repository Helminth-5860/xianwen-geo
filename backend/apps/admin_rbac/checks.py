from django.core.checks import Warning, register
from django.db import OperationalError, ProgrammingError
from django.db.models import Q

from apps.users.models import User

from .models import AdminProfile, AdminRole


@register()
def admin_profile_invariants(app_configs, **kwargs):
    warnings: list[Warning] = []
    try:
        missing_profiles = User.objects.filter(
            Q(is_staff=True) | Q(is_superuser=True), admin_profile__isnull=True
        ).exists()
        invalid_superusers = (
            AdminProfile.objects.filter(user__is_superuser=True)
            .exclude(
                admin_status=AdminProfile.Status.ACTIVE,
                role__isnull=True,
                user__is_staff=True,
                user__is_active=True,
            )
            .exists()
        )
        invalid_ordinary_admins = (
            AdminProfile.objects.filter(
                user__is_superuser=False,
                admin_status=AdminProfile.Status.ACTIVE,
            )
            .filter(
                Q(role__isnull=True)
                | ~Q(role__status=AdminRole.Status.ACTIVE)
                | Q(user__is_staff=False)
                | Q(user__is_active=False)
            )
            .exists()
        )
    except (OperationalError, ProgrammingError):
        return warnings
    if missing_profiles:
        warnings.append(
            Warning(
                "存在缺少 AdminProfile 的 staff/superuser，后台权限将默认拒绝。",
                id="admin_rbac.W001",
            )
        )
    if invalid_ordinary_admins:
        warnings.append(
            Warning(
                "存在不满足角色、状态或 User 投影的启用普通管理员，后台权限将默认拒绝。",
                id="admin_rbac.W002",
            )
        )
    if invalid_superusers:
        warnings.append(
            Warning(
                "存在不满足 active、role=null 投影的超级管理员，后台权限将默认拒绝。",
                id="admin_rbac.W003",
            )
        )
    return warnings


@register()
def risk_catalog_invariants(app_configs, **kwargs):
    from django.core.checks import Error

    from .risk_catalog import CATALOG_VERSION, RISK_ACTION_CATALOG, mode_is_valid
    from .risk_handlers import HANDLER_REGISTRY
    from .risk_models import RiskAction

    errors = []
    definitions = {item.key: item for item in RISK_ACTION_CATALOG}
    if set(definitions) != set(HANDLER_REGISTRY):
        errors.append(Error("高风险目录与静态 Handler 注册表不一致。", id="admin_rbac.E010"))
    for definition in definitions.values():
        if (
            definition.default_mode not in definition.supported_modes
            or not mode_is_valid(definition, definition.default_mode)
            or definition.minimum_mode not in definition.supported_modes
        ):
            errors.append(
                Error(f"高风险动作 {definition.key} 的模式定义不合法。", id="admin_rbac.E011")
            )
    try:
        rows = {item.key: item for item in RiskAction.objects.all()}
    except (OperationalError, ProgrammingError):
        return errors
    for key, definition in definitions.items():
        row = rows.get(key)
        expected = {
            "name": definition.name,
            "module": definition.module,
            "target_type": definition.target_type,
            "supported_modes": list(definition.supported_modes),
            "default_mode": definition.default_mode,
            "minimum_mode": definition.minimum_mode,
            "handler_key": definition.handler_key,
            "catalog_version": CATALOG_VERSION,
        }
        if row is None or any(getattr(row, field) != value for field, value in expected.items()):
            errors.append(Error(f"高风险目录数据库记录发生漂移：{key}", id="admin_rbac.E012"))
    unmanaged = set(rows) - set(definitions)
    if unmanaged:
        errors.append(Error("数据库存在未受代码目录管理的高风险动作。", id="admin_rbac.E013"))
    return errors
