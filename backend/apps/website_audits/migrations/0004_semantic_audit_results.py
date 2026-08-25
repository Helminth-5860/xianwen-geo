from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("website_audits", "0003_browser_audit_evidence"),
    ]

    operations = [
        migrations.AddField(
            model_name="websiteaudit",
            name="semantic_status",
            field=models.CharField(
                choices=[
                    ("not_started", "未开始"),
                    ("queued", "排队中"),
                    ("running", "语义检测中"),
                    ("succeeded", "已完成"),
                    ("failed", "失败"),
                    ("disabled", "未启用"),
                ],
                default="not_started",
                max_length=16,
            ),
        ),
        migrations.AddField(model_name="websiteaudit", name="semantic_provider_key", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="websiteaudit", name="semantic_model_id", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="websiteaudit", name="semantic_runtime_version", field=models.PositiveBigIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="websiteaudit", name="semantic_prompt_version", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="websiteaudit", name="semantic_page_count", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="websiteaudit", name="semantic_question_count", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="websiteaudit", name="semantic_scores", field=models.JSONField(default=dict)),
        migrations.AddField(model_name="websiteaudit", name="semantic_result", field=models.JSONField(default=dict)),
        migrations.AddField(model_name="websiteaudit", name="semantic_input_tokens", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="websiteaudit", name="semantic_output_tokens", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="websiteaudit", name="semantic_total_tokens", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="websiteaudit", name="semantic_latency_ms", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="websiteaudit", name="semantic_error_code", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="websiteaudit", name="semantic_started_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="websiteaudit", name="semantic_finished_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddIndex(
            model_name="websiteaudit",
            index=models.Index(fields=["semantic_status", "created_at"], name="website_semantic_status_idx"),
        ),
    ]
