from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.plans.catalog import MODEL_KEYS
from apps.plans.models import Plan, PlanLimitDefinition, PlanVersion
from apps.plans.services import (
    create_plan_version,
    publish_plan_version,
    update_plan_version,
)

STANDARD_PLANS = (
    {
        "code": "free-trial",
        "name": "新用户免费体验",
        "description": "完整体验显问GEO核心流程",
        "price": Decimal("0.00"),
        "is_trial": True,
        "is_recommended": False,
        "sort_order": 10,
        "models": 3,
        "questions": 5,
        "quotas": (1, 5, 5, 3, 1, 1, 1, 1, 3, 1, 100, 100),
    },
    {
        "code": "starter-1980",
        "name": "入门版",
        "description": "适合开始持续建设GEO内容与信源的团队",
        "price": Decimal("1980.00"),
        "is_trial": False,
        "is_recommended": False,
        "sort_order": 20,
        "models": 8,
        "questions": 10,
        "quotas": (20, 500, 500, 100, 10, 10, 10, 10, 50, 10, 5000, 5000),
    },
    {
        "code": "professional-6980",
        "name": "专业版",
        "description": "适合需要规模化检测、内容生产与持续优化的团队",
        "price": Decimal("6980.00"),
        "is_trial": False,
        "is_recommended": True,
        "sort_order": 30,
        "models": 8,
        "questions": 20,
        "quotas": (60, 3000, 3000, 300, 30, 30, 30, 30, 200, 30, 20000, 20000),
    },
    {
        "code": "advanced-12980",
        "name": "高阶版",
        "description": "适合多渠道、高频次GEO运营与内容建设的团队",
        "price": Decimal("12980.00"),
        "is_trial": False,
        "is_recommended": False,
        "sort_order": 40,
        "models": 8,
        "questions": 30,
        "quotas": (120, 8000, 8000, 600, 60, 60, 60, 60, 500, 60, 50000, 50000),
    },
)

QUOTA_KEYS = (
    "geo_detection_runs",
    "article_generations",
    "auto_publish_count",
    "image_generations",
    "source_index_scans",
    "negative_index_scans",
    "website_audits",
    "website_generations",
    "video_script_generations",
    "competitor_comparisons",
    "keyword_generated_items",
    "question_generated_items",
)


def _limit_values(item: dict) -> list[dict]:
    definitions = PlanLimitDefinition.objects.filter(
        storage_kind="plan_limit", status="active"
    ).order_by("sort_order", "key")
    overrides = dict(zip(QUOTA_KEYS, item["quotas"], strict=True))
    overrides.update(
        {
            "allow_user_model_selection": True,
            "max_models_per_detection": item["models"],
            "max_questions_per_detection": item["questions"],
            "concurrent_detection_jobs": 1,
            # These historical regeneration controls are kept only for old
            # feature paths and are not exposed as customer package balances.
            "distillation_regenerations_per_cycle": 9_223_372_036_854_775_807,
            "strategy_regenerations_per_cycle": 9_223_372_036_854_775_807,
            "outline_regenerations_per_cycle": 9_223_372_036_854_775_807,
            "local_ai_edits_per_cycle": 9_223_372_036_854_775_807,
            "quality_rechecks_per_cycle": 9_223_372_036_854_775_807,
            "expiry_quota_policy": {},
        }
    )
    return [
        {"key": definition.key, "value": overrides.get(definition.key, definition.default_value)}
        for definition in definitions
    ]


def _model_permissions(default_count: int) -> list[dict]:
    return [
        {
            "model_key": key,
            "sort_order": index * 10,
            "selected_by_default": index < default_count,
        }
        for index, key in enumerate(MODEL_KEYS)
    ]


class Command(BaseCommand):
    help = "创建或增量更新四个标准年度套餐；历史版本保持不可变。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="应用标准套餐同步。")

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["apply"]:
            self.stdout.write("使用 --apply 后才会写入标准套餐。")
            return
        for item in STANDARD_PLANS:
            plan = Plan.objects.filter(code=item["code"]).first()
            desired_limits = _limit_values(item)
            desired_limit_map = {row["key"]: row["value"] for row in desired_limits}
            desired_models = _model_permissions(item["models"])
            if plan is None:
                plan = Plan.objects.create(
                    id=uuid.uuid4(),
                    code=item["code"],
                    name=item["name"],
                    description=item["description"],
                    price_display_mode=Plan.PriceDisplayMode.FIXED,
                    display_price=item["price"],
                    display_currency="CNY",
                    is_trial=item["is_trial"],
                    is_recommended=item["is_recommended"],
                    sort_order=item["sort_order"],
                )
            else:
                metadata = {
                    "name": item["name"],
                    "description": item["description"],
                    "price_display_mode": Plan.PriceDisplayMode.FIXED,
                    "display_price": item["price"],
                    "is_trial": item["is_trial"],
                    "is_recommended": item["is_recommended"],
                    "sort_order": item["sort_order"],
                }
                changed_fields = [
                    field for field, value in metadata.items() if getattr(plan, field) != value
                ]
                if changed_fields:
                    for field, value in metadata.items():
                        setattr(plan, field, value)
                    plan.version += 1
                    plan.save(update_fields=(*changed_fields, "version", "updated_at"))
            draft = plan.versions.filter(status=PlanVersion.Status.DRAFT).first()
            current = plan.current_published_version
            if draft is None and current is not None:
                current_models = list(
                    current.model_permissions.order_by("sort_order", "model_key").values(
                        "model_key", "sort_order", "selected_by_default"
                    )
                )
                current_limits = (current.effective_config or {}).get("limits", {})
                if (
                    current.valid_days == 365
                    and current_limits == desired_limit_map
                    and current_models == desired_models
                ):
                    self.stdout.write(f"无需更新：{item['name']}")
                    continue
            if draft is None:
                draft = create_plan_version(
                    plan_id=plan.pk,
                    actor=None,
                    expected_plan_version=plan.version,
                )
                plan.refresh_from_db()
            update_plan_version(
                version_id=draft.pk,
                actor=None,
                expected_version=draft.version,
                valid_days=365,
                queue_priority=100,
                limits=desired_limits,
                model_permissions=desired_models,
            )
            draft.refresh_from_db()
            publish_plan_version(
                version_id=draft.pk,
                actor=None,
                expected_version=draft.version,
                confirm_informal_composite=True,
            )
            self.stdout.write(self.style.SUCCESS(f"已同步：{item['name']}"))
