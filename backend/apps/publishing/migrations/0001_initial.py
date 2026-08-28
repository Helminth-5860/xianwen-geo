# Generated for the Xianwen automatic publishing center.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("subjects", "0017_promote_saved_subjects"),
        ("articles", "0002_seed_catalogs_and_postgresql_guards"),
    ]

    operations = [
        migrations.CreateModel(
            name="PublishingPreference",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("is_enabled", models.BooleanField(default=False)),
                ("mode", models.CharField(choices=[("managed", "全自动托管"), ("review", "审核后发布"), ("selected", "仅发布指定内容")], default="managed", max_length=16)),
                ("distribution_strategy", models.CharField(choices=[("smart", "智能分发"), ("all", "所有已授权平台"), ("custom", "自定义平台")], default="smart", max_length=16)),
                ("custom_platform_keys", models.JSONField(default=list)),
                ("image_strategy", models.CharField(choices=[("customer_only", "仅使用企业素材"), ("customer_first", "企业素材优先，不足自动补图"), ("ai_auto", "全自动配图")], default="customer_first", max_length=24)),
                ("image_density", models.CharField(choices=[("compact", "简洁"), ("standard", "标准"), ("rich", "丰富")], default="standard", max_length=16)),
                ("frequency_mode", models.CharField(choices=[("smart", "智能安排"), ("fixed", "固定频率")], default="smart", max_length=16)),
                ("posts_per_day", models.PositiveSmallIntegerField(default=1)),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("subject", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="publishing_preference", to="subjects.subject")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publishing_preferences", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "publishing_preferences"},
        ),
        migrations.CreateModel(
            name="PlatformAccount",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("platform_key", models.CharField(max_length=32)),
                ("auth_method", models.CharField(choices=[("official_api", "官方授权"), ("browser_session", "网页登录授权")], max_length=24)),
                ("status", models.CharField(choices=[("unlinked", "未授权"), ("authorizing", "授权中"), ("connected", "已授权"), ("expired", "授权已失效"), ("action_required", "需要重新授权"), ("suspended", "已暂停")], default="unlinked", max_length=24)),
                ("display_name", models.CharField(blank=True, max_length=255)),
                ("external_account_id", models.CharField(blank=True, max_length=255)),
                ("secret_ciphertext", models.TextField(blank=True)),
                ("credential_version", models.PositiveIntegerField(default=1)),
                ("enabled_for_auto", models.BooleanField(default=True)),
                ("session_expires_at", models.DateTimeField(blank=True, null=True)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publishing_platform_accounts", to="subjects.subject")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publishing_platform_accounts", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "publishing_platform_accounts", "ordering": ("platform_key", "created_at")},
        ),
        migrations.CreateModel(
            name="PlatformAuthorizationSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("platform_key", models.CharField(max_length=32)),
                ("auth_method", models.CharField(choices=[("official_api", "官方授权"), ("browser_session", "网页登录授权")], max_length=24)),
                ("status", models.CharField(choices=[("created", "等待授权"), ("starting", "正在打开授权页面"), ("waiting_user", "等待完成登录"), ("succeeded", "授权成功"), ("failed", "授权未完成"), ("expired", "授权已过期")], default="created", max_length=24)),
                ("one_time_token_digest", models.CharField(max_length=64, unique=True)),
                ("remote_session_ref", models.CharField(blank=True, max_length=255)),
                ("action_url", models.TextField(blank=True)),
                ("safe_error_code", models.CharField(blank=True, max_length=100)),
                ("expires_at", models.DateTimeField()),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="authorization_sessions", to="publishing.platformaccount")),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publishing_authorization_sessions", to="subjects.subject")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publishing_authorization_sessions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "publishing_authorization_sessions", "ordering": ("-created_at", "-id")},
        ),
        migrations.CreateModel(
            name="Publication",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("preparing", "准备中"), ("queued", "等待发布"), ("running", "正在发布"), ("partial", "部分完成"), ("succeeded", "发布完成"), ("failed", "发布未完成"), ("cancelled", "已取消")], default="preparing", max_length=16)),
                ("source_title", models.CharField(max_length=500)),
                ("source_content_digest", models.CharField(max_length=64)),
                ("distribution_strategy", models.CharField(choices=[("smart", "智能分发"), ("all", "所有已授权平台"), ("custom", "自定义平台")], max_length=16)),
                ("image_strategy", models.CharField(choices=[("customer_only", "仅使用企业素材"), ("customer_first", "企业素材优先，不足自动补图"), ("ai_auto", "全自动配图")], max_length=24)),
                ("image_plan", models.JSONField(default=dict)),
                ("platform_plan", models.JSONField(default=list)),
                ("scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("article", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publications", to="articles.article")),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publications", to="subjects.subject")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "publications", "ordering": ("-created_at", "-id")},
        ),
        migrations.CreateModel(
            name="PublicationTarget",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("platform_key", models.CharField(max_length=32)),
                ("status", models.CharField(choices=[("waiting", "等待发布"), ("ready", "已准备"), ("running", "正在发布"), ("succeeded", "已发布"), ("failed", "发布失败"), ("auth_required", "需要重新授权"), ("paused", "已暂停")], default="waiting", max_length=24)),
                ("adapted_title", models.CharField(blank=True, max_length=500)),
                ("adapted_content", models.TextField(blank=True)),
                ("media_payload", models.JSONField(default=dict)),
                ("scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("external_post_id", models.CharField(blank=True, max_length=255)),
                ("public_url", models.TextField(blank=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("safe_error_code", models.CharField(blank=True, max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="publication_targets", to="publishing.platformaccount")),
                ("publication", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="targets", to="publishing.publication")),
            ],
            options={"db_table": "publication_targets", "ordering": ("scheduled_at", "platform_key")},
        ),
        migrations.AddIndex(model_name="publishingpreference", index=models.Index(fields=["user", "is_enabled"], name="publishing_pref_user_idx")),
        migrations.AddConstraint(model_name="publishingpreference", constraint=models.CheckConstraint(condition=models.Q(("posts_per_day__gte", 1), ("posts_per_day__lte", 10)), name="publishing_posts_day_range")),
        migrations.AddConstraint(model_name="publishingpreference", constraint=models.CheckConstraint(condition=models.Q(("version__gte", 1)), name="publishing_pref_version_gte_1")),
        migrations.AddConstraint(model_name="platformaccount", constraint=models.UniqueConstraint(fields=("user", "subject", "platform_key"), name="publishing_account_user_subject_platform_unique")),
        migrations.AddIndex(model_name="platformaccount", index=models.Index(fields=["user", "subject", "status"], name="publishing_account_state_idx")),
        migrations.AddIndex(model_name="platformauthorizationsession", index=models.Index(fields=["user", "status", "created_at"], name="publishing_auth_user_idx")),
        migrations.AddIndex(model_name="platformauthorizationsession", index=models.Index(fields=["platform_key", "status", "created_at"], name="publishing_auth_platform_idx")),
        migrations.AddIndex(model_name="publication", index=models.Index(fields=["user", "subject", "status"], name="publication_user_state_idx")),
        migrations.AddConstraint(model_name="publicationtarget", constraint=models.UniqueConstraint(fields=("publication", "platform_key"), name="publication_target_platform_unique")),
        migrations.AddIndex(model_name="publicationtarget", index=models.Index(fields=["status", "scheduled_at"], name="publication_target_queue_idx")),
    ]
