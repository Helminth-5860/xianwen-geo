import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("geo", "0012_geodetectionjob_user_removed_at"),
        ("media_inquiries", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StrategyExecutionPlan",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "package_code",
                    models.CharField(
                        choices=[
                            ("basic", "基础改善"),
                            ("focused", "重点提升"),
                            ("comprehensive", "全面建设"),
                            ("custom", "自定义"),
                        ],
                        max_length=24,
                    ),
                ),
                ("items", models.JSONField(default=list)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "执行中"),
                            ("completed", "已完成"),
                            ("cancelled", "已取消"),
                        ],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("media_total", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("request_digest", models.CharField(max_length=64)),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "paid_media_inquiry",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="strategy_execution_plans",
                        to="media_inquiries.paidmediainquiry",
                    ),
                ),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="strategy_execution_plans",
                        to="geo.georeport",
                    ),
                ),
                (
                    "strategy",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_plan",
                        to="geo.strategyreport",
                    ),
                ),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="strategy_execution_plans",
                        to="subjects.subject",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="strategy_execution_plans",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "strategy_execution_plans",
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["user", "subject", "created_at"],
                        name="strategy_plan_owner_idx",
                    ),
                    models.Index(
                        fields=["status", "created_at"],
                        name="strategy_plan_status_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("package_code__in", ("basic", "focused", "comprehensive", "custom"))
                        ),
                        name="strategy_plan_package_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("status__in", ("active", "completed", "cancelled"))),
                        name="strategy_plan_status_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("media_total__gte", 0)),
                        name="strategy_plan_media_total_nonnegative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("version__gte", 1)),
                        name="strategy_plan_version_gte_1",
                    ),
                ],
            },
        )
    ]
