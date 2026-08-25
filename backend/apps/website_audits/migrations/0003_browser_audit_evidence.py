import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("website_audits", "0002_enrich_audit_evidence_and_findings"),
    ]

    operations = [
        migrations.AddField(
            model_name="websiteaudit",
            name="browser_status",
            field=models.CharField(
                choices=[
                    ("not_started", "未开始"),
                    ("queued", "排队中"),
                    ("running", "浏览器检测中"),
                    ("succeeded", "已完成"),
                    ("partial", "部分完成"),
                    ("failed", "失败"),
                    ("disabled", "未启用"),
                ],
                default="not_started",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="websiteaudit",
            name="browser_profiles",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="websiteaudit",
            name="browser_selected_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="websiteaudit",
            name="browser_completed_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="websiteaudit",
            name="browser_failed_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="websiteaudit",
            name="browser_error_code",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="websiteaudit",
            name="browser_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="websiteaudit",
            name="browser_finished_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="websiteaudit",
            index=models.Index(
                fields=["browser_status", "created_at"],
                name="website_browser_status_idx",
            ),
        ),
        migrations.CreateModel(
            name="WebsiteAuditBrowserSnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("profile", models.CharField(choices=[("mobile", "移动端"), ("desktop", "桌面端")], max_length=16)),
                ("status", models.CharField(choices=[("succeeded", "成功"), ("failed", "失败")], max_length=16)),
                ("final_url", models.TextField(blank=True)),
                ("navigation_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("ttfb_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("dom_content_loaded_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("load_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("fcp_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("lcp_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("cls", models.FloatField(blank=True, null=True)),
                ("tbt_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("request_count", models.PositiveIntegerField(default=0)),
                ("failed_request_count", models.PositiveIntegerField(default=0)),
                ("blocked_request_count", models.PositiveIntegerField(default=0)),
                ("transfer_bytes", models.PositiveBigIntegerField(default=0)),
                ("cross_host_request_count", models.PositiveIntegerField(default=0)),
                ("cross_host_transfer_bytes", models.PositiveBigIntegerField(default=0)),
                ("resource_summary", models.JSONField(default=dict)),
                ("console_error_count", models.PositiveIntegerField(default=0)),
                ("page_error_count", models.PositiveIntegerField(default=0)),
                ("dom_nodes", models.PositiveIntegerField(default=0)),
                ("rendered_html_characters", models.PositiveIntegerField(default=0)),
                ("rendered_text_characters", models.PositiveIntegerField(default=0)),
                ("static_text_characters", models.PositiveIntegerField(default=0)),
                ("text_delta", models.IntegerField(default=0)),
                ("text_growth_ratio", models.FloatField(blank=True, null=True)),
                ("rendered_title", models.CharField(blank=True, max_length=500)),
                ("rendered_meta_description", models.TextField(blank=True)),
                ("rendered_canonical_url", models.TextField(blank=True)),
                ("rendered_schema_types", models.JSONField(default=list)),
                ("rendered_heading_counts", models.JSONField(default=dict)),
                ("visible_image_count", models.PositiveIntegerField(default=0)),
                ("images_without_alt", models.PositiveIntegerField(default=0)),
                ("failure_code", models.CharField(blank=True, max_length=64)),
                ("evidence", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "audit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="browser_snapshots",
                        to="website_audits.websiteaudit",
                    ),
                ),
                (
                    "page",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="browser_snapshots",
                        to="website_audits.websiteauditpage",
                    ),
                ),
            ],
            options={
                "db_table": "website_audit_browser_snapshots",
                "ordering": ("page_id", "profile", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="websiteauditbrowsersnapshot",
            constraint=models.UniqueConstraint(
                fields=("audit", "page", "profile"),
                name="website_browser_snapshot_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="websiteauditbrowsersnapshot",
            index=models.Index(
                fields=["audit", "profile", "status"],
                name="website_browser_profile_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="websiteauditbrowsersnapshot",
            index=models.Index(
                fields=["audit", "page"],
                name="website_browser_page_idx",
            ),
        ),
    ]
