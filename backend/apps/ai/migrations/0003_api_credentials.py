import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0002_seed_and_postgresql_guards"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="APICredential",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "environment",
                    models.CharField(
                        choices=[("staging", "Staging"), ("production", "Production")],
                        max_length=32,
                    ),
                ),
                ("secret_reference", models.TextField(blank=True)),
                ("secret_mask", models.CharField(max_length=100)),
                ("version_no", models.PositiveIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "启用"), ("replaced", "已替换")],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("replaced_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_ai_api_credentials",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "provider",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="api_credentials",
                        to="ai.aiprovider",
                    ),
                ),
                (
                    "replaced_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="replaced_ai_api_credentials",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "api_credentials",
                "ordering": ("provider_id", "environment", "-version_no"),
            },
        ),
        migrations.CreateModel(
            name="APICredentialAudit",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[("created", "新增"), ("rotated", "轮换"), ("tested", "测试")],
                        max_length=16,
                    ),
                ),
                (
                    "outcome",
                    models.CharField(
                        choices=[("success", "成功"), ("failure", "失败")], max_length=16
                    ),
                ),
                ("safe_summary", models.JSONField(default=dict)),
                ("stable_error_code", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_api_credential_audits",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "credential",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="credential_audits",
                        to="ai.apicredential",
                    ),
                ),
            ],
            options={
                "db_table": "api_credential_audit",
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["credential", "created_at"],
                        name="ai_cred_audit_credential_idx",
                    )
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="apicredential",
            constraint=models.UniqueConstraint(
                fields=("provider", "environment", "version_no"),
                name="ai_credential_provider_env_version_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="apicredential",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "active")),
                fields=("provider", "environment"),
                name="ai_credential_one_active_per_env",
            ),
        ),
        migrations.AddConstraint(
            model_name="apicredential",
            constraint=models.CheckConstraint(
                condition=models.Q(("environment__in", ("staging", "production"))),
                name="ai_credential_environment_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="apicredential",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ("active", "replaced"))),
                name="ai_credential_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="apicredential",
            constraint=models.CheckConstraint(
                condition=models.Q(("version_no__gte", 1)),
                name="ai_credential_version_gte_1",
            ),
        ),
        migrations.AddConstraint(
            model_name="apicredential",
            constraint=models.CheckConstraint(
                condition=~models.Q(("secret_mask", "")),
                name="ai_credential_mask_not_empty",
            ),
        ),
        migrations.AddConstraint(
            model_name="apicredential",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("replaced_at__isnull", True), ("status", "active"))
                    & ~models.Q(("secret_reference", ""))
                    | models.Q(("secret_reference", ""), ("status", "replaced"))
                    & models.Q(("replaced_at__isnull", False))
                ),
                name="ai_credential_secret_state_shape",
            ),
        ),
    ]
