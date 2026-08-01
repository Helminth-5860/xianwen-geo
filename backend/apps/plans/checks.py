from django.core.checks import CheckMessage, Error, Warning, register
from django.db import OperationalError, ProgrammingError

from .catalog import LIMIT_BY_KEY, LIMIT_CATALOG


@register()
def plan_catalog_checks(app_configs, **kwargs):
    errors: list[CheckMessage] = []
    if len(LIMIT_BY_KEY) != len(LIMIT_CATALOG):
        errors.append(Error("套餐限制键目录存在重复 key。", id="plans.E001"))
    try:
        from .models import Plan, PlanLimitDefinition, PlanVersion

        rows = {item.key: item for item in PlanLimitDefinition.objects.all()}
        for definition in LIMIT_CATALOG:
            current = rows.get(definition.key)
            if current is None:
                errors.append(
                    Warning(
                        f"套餐限制键尚未同步：{definition.key}",
                        hint="运行 sync_plan_catalog --apply。",
                        id="plans.W001",
                    )
                )
            elif current.semantic_digest != definition.semantic_digest:
                errors.append(
                    Error(
                        f"套餐限制键机器语义漂移：{definition.key}",
                        id="plans.E002",
                    )
                )
        plans = Plan.objects.select_related("current_published_version")
        for plan in plans.iterator():
            current_version = plan.current_published_version
            if plan.status == Plan.Status.DRAFT and current_version is not None:
                errors.append(Error(f"草稿套餐 current pointer 非空：{plan.pk}", id="plans.E003"))
            elif plan.status == Plan.Status.PUBLISHED and (
                current_version is None
                or current_version.plan_id != plan.pk
                or current_version.status != PlanVersion.Status.PUBLISHED
            ):
                errors.append(Error(f"已上架套餐 current pointer 无效：{plan.pk}", id="plans.E004"))
            elif (
                plan.status == Plan.Status.OFFLINE
                and current_version is not None
                and (
                    current_version.plan_id != plan.pk
                    or current_version.status != PlanVersion.Status.PUBLISHED
                )
            ):
                errors.append(Error(f"下架套餐 current pointer 无效：{plan.pk}", id="plans.E005"))
            elif plan.status == Plan.Status.ARCHIVED and current_version is not None:
                errors.append(Error(f"归档套餐 current pointer 非空：{plan.pk}", id="plans.E006"))
    except (OperationalError, ProgrammingError):
        return errors
    return errors
