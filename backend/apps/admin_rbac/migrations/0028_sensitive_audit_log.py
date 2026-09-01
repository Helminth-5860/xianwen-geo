import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("admin_rbac", "0027_allow_independent_users"),
    ]

    operations = [
        migrations.CreateModel(
            name="SensitiveAuditLog",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "category",
                    models.CharField(default="sensitive_action", max_length=50),
                ),
                ("action_key", models.CharField(max_length=100)),
                (
                    "outcome",
                    models.CharField(
                        choices=[("success", "成功"), ("failure", "失败")], max_length=16
                    ),
                ),
                ("channel", models.CharField(default="admin_console", max_length=32)),
                ("actor_user_id_snapshot", models.UUIDField(blank=True, null=True)),
                ("actor_name_snapshot", models.CharField(blank=True, max_length=50)),
                ("actor_role_snapshot", models.CharField(blank=True, max_length=100)),
                ("actor_tenant_id_snapshot", models.UUIDField(blank=True, null=True)),
                ("actor_tenant_name_snapshot", models.CharField(blank=True, max_length=120)),
                ("target_user_id_snapshot", models.UUIDField(blank=True, null=True)),
                ("target_name_snapshot", models.CharField(blank=True, max_length=50)),
                ("target_owner_user_id_snapshot", models.UUIDField(blank=True, null=True)),
                ("target_owner_name_snapshot", models.CharField(blank=True, max_length=50)),
                ("target_tenant_id_snapshot", models.UUIDField(blank=True, null=True)),
                ("target_tenant_name_snapshot", models.CharField(blank=True, max_length=120)),
                ("quota_type", models.CharField(blank=True, max_length=100)),
                ("quota_before", models.BigIntegerField(blank=True, null=True)),
                ("quota_requested_delta", models.BigIntegerField(blank=True, null=True)),
                ("quota_delta", models.BigIntegerField(blank=True, null=True)),
                ("quota_after", models.BigIntegerField(blank=True, null=True)),
                ("ledger_entry_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("request_id", models.UUIDField(db_index=True)),
                ("operation_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("login_ip_snapshot", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=512)),
                ("safe_reason", models.CharField(blank=True, max_length=500)),
                ("failure_reason", models.CharField(blank=True, max_length=128)),
                ("details", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "db_table": "sensitive_audit_logs",
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="sensitiveauditlog",
            index=models.Index(
                fields=["actor_user_id_snapshot", "created_at"], name="sens_actor_created_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="sensitiveauditlog",
            index=models.Index(
                fields=["target_user_id_snapshot", "created_at"], name="sens_target_created_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="sensitiveauditlog",
            index=models.Index(
                fields=["target_owner_user_id_snapshot", "created_at"],
                name="sens_owner_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="sensitiveauditlog",
            index=models.Index(
                fields=["action_key", "created_at"], name="sens_action_created_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="sensitiveauditlog",
            index=models.Index(
                fields=["outcome", "created_at"], name="sens_outcome_created_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="sensitiveauditlog",
            index=models.Index(
                fields=["operation_ip", "created_at"], name="sens_ip_created_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="sensitiveauditlog",
            constraint=models.CheckConstraint(
                condition=models.Q(("outcome__in", ("success", "failure"))),
                name="sensitive_audit_valid_outcome",
            ),
        ),
    ]
