import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("geo", "0013_strategy_execution_plan"),
        ("subjects", "0017_promote_saved_subjects"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubjectCompetitor",
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
                ("name", models.CharField(max_length=255)),
                ("normalized_name", models.CharField(max_length=255)),
                ("website", models.URLField(blank=True, default="", max_length=500)),
                ("website_domain", models.CharField(blank=True, default="", max_length=255)),
                (
                    "source",
                    models.CharField(
                        choices=[("manual", "手动添加"), ("smart", "智能发现")],
                        default="manual",
                        max_length=16,
                    ),
                ),
                ("position", models.PositiveSmallIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "使用中"), ("removed", "已移除")],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("removed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="managed_competitors",
                        to="subjects.subject",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="subject_competitors",
                        to="users.tenant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="subject_competitors",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "subject_competitors",
                "ordering": ("subject_id", "position", "created_at", "id"),
                "indexes": [
                    models.Index(
                        fields=["user", "subject", "status", "position"],
                        name="subject_comp_owner_idx",
                    ),
                    models.Index(
                        fields=["tenant", "subject", "status"],
                        name="subject_comp_tenant_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("source__in", ("manual", "smart"))),
                        name="subject_comp_source_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("status__in", ("active", "removed"))),
                        name="subject_comp_status_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("position__gte", 1), ("position__lte", 3)),
                        name="subject_comp_position_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("version__gte", 1)),
                        name="subject_comp_version_gte_1",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("removed_at__isnull", True), ("status", "active"))
                            | models.Q(("removed_at__isnull", False), ("status", "removed"))
                        ),
                        name="subject_comp_removed_at_state",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("status", "active")),
                        fields=("subject", "normalized_name"),
                        name="subject_comp_active_name_unique",
                    ),
                    models.UniqueConstraint(
                        condition=(
                            models.Q(("status", "active"))
                            & ~models.Q(("website_domain", ""))
                        ),
                        fields=("subject", "website_domain"),
                        name="subject_comp_active_domain_unique",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("status", "active")),
                        fields=("subject", "position"),
                        name="subject_comp_active_pos_unique",
                    ),
                ],
            },
        )
    ]
