import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("documents", "0005_parse_state_pointer_consistency"),
        ("images", "0002_seed_presets_and_postgresql_guards"),
        ("plans", "0017_add_video_credit_definition"),
        ("quotas", "0014_backfill_video_credit_accounts"),
        ("subjects", "0017_promote_saved_subjects"),
        ("users", "0013_user_is_test_account"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VideoGenerationJob",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "generation_mode",
                    models.CharField(
                        choices=[("text", "文字生成"), ("image", "图片生成")], max_length=16
                    ),
                ),
                ("prompt", models.TextField()),
                ("prompt_digest", models.CharField(max_length=64)),
                (
                    "aspect_ratio",
                    models.CharField(
                        choices=[("9:16", "竖屏 9:16"), ("16:9", "横屏 16:9")],
                        max_length=8,
                    ),
                ),
                ("duration_seconds", models.PositiveSmallIntegerField()),
                ("resolution", models.CharField(default="720P", max_length=16)),
                ("provider_key", models.CharField(default="aliyun", max_length=64)),
                (
                    "provider_model_id",
                    models.CharField(default="wan2.6-i2v-flash", max_length=255),
                ),
                ("provider_job_id", models.CharField(blank=True, max_length=128)),
                ("provider_request_id", models.CharField(blank=True, max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "排队中"),
                            ("processing", "生成中"),
                            ("succeeded", "已完成"),
                            ("failed", "生成失败"),
                        ],
                        default="queued",
                        max_length=16,
                    ),
                ),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("first_frame", "准备首帧"),
                            ("submit", "准备提交"),
                            ("submitting", "正在提交"),
                            ("poll", "等待生成"),
                            ("transfer", "保存视频"),
                            ("complete", "已完成"),
                        ],
                        default="first_frame",
                        max_length=24,
                    ),
                ),
                ("safe_error_code", models.CharField(blank=True, max_length=100)),
                ("safe_error_message", models.CharField(blank=True, max_length=200)),
                ("poll_count", models.PositiveIntegerField(default=0)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("lease_generation", models.UUIDField(blank=True, null=True)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("idempotency_key_version", models.PositiveSmallIntegerField(default=1)),
                ("idempotency_key_digest", models.CharField(max_length=64, unique=True)),
                ("request_digest", models.CharField(max_length=64)),
                ("request_id", models.UUIDField(db_index=True)),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "first_frame",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="video_generation_jobs",
                        to="images.imageasset",
                    ),
                ),
                (
                    "quota_hold",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="video_generation_job",
                        to="quotas.quotaholdgroup",
                    ),
                ),
                (
                    "source_document_version",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="video_generation_jobs",
                        to="documents.documentversion",
                    ),
                ),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="video_generation_jobs",
                        to="subjects.subject",
                    ),
                ),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="video_generation_jobs",
                        to="plans.subscription",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="video_generation_jobs",
                        to="users.tenant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="video_generation_jobs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "video_generation_jobs",
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.CreateModel(
            name="VideoAsset",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("object_key", models.CharField(max_length=500, unique=True)),
                ("duration_seconds", models.PositiveSmallIntegerField()),
                (
                    "aspect_ratio",
                    models.CharField(
                        choices=[("9:16", "竖屏 9:16"), ("16:9", "横屏 16:9")],
                        max_length=8,
                    ),
                ),
                ("resolution", models.CharField(default="720P", max_length=16)),
                ("mime_type", models.CharField(default="video/mp4", max_length=64)),
                ("size_bytes", models.PositiveBigIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("is_subject_library", models.BooleanField(default=False)),
                ("available_at", models.DateTimeField()),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "generation_job",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="result_asset",
                        to="videos.videogenerationjob",
                    ),
                ),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="video_assets",
                        to="subjects.subject",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="video_assets",
                        to="users.tenant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="video_assets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "videos", "ordering": ("-created_at", "-id")},
        ),
        migrations.AddIndex(
            model_name="videogenerationjob",
            index=models.Index(
                fields=["user", "subject", "created_at"], name="video_job_owner_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="videogenerationjob",
            index=models.Index(
                fields=["status", "next_attempt_at", "lease_expires_at"],
                name="video_job_due_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="videogenerationjob",
            constraint=models.UniqueConstraint(
                condition=~models.Q(provider_job_id=""),
                fields=("provider_key", "provider_job_id"),
                name="video_provider_job_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="videogenerationjob",
            constraint=models.CheckConstraint(
                condition=models.Q(generation_mode="text", source_document_version__isnull=True)
                | models.Q(generation_mode="image", source_document_version__isnull=False),
                name="video_job_source_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="videogenerationjob",
            constraint=models.CheckConstraint(
                condition=models.Q(aspect_ratio__in=("9:16", "16:9")),
                name="video_job_aspect_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="videogenerationjob",
            constraint=models.CheckConstraint(
                condition=models.Q(duration_seconds__in=(5, 10)),
                name="video_job_duration_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="videogenerationjob",
            constraint=models.CheckConstraint(
                condition=models.Q(resolution="720P"), name="video_job_resolution_720p"
            ),
        ),
        migrations.AddConstraint(
            model_name="videogenerationjob",
            constraint=models.CheckConstraint(
                condition=models.Q(version__gte=1), name="video_job_version_gte_1"
            ),
        ),
        migrations.AddIndex(
            model_name="videoasset",
            index=models.Index(
                fields=["user", "subject", "is_subject_library", "created_at"],
                name="video_asset_owner_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="videoasset",
            constraint=models.CheckConstraint(
                condition=models.Q(size_bytes__gte=1), name="video_asset_size_gte_1"
            ),
        ),
        migrations.AddConstraint(
            model_name="videoasset",
            constraint=models.CheckConstraint(
                condition=models.Q(duration_seconds__in=(5, 10)),
                name="video_asset_duration_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="videoasset",
            constraint=models.CheckConstraint(
                condition=models.Q(aspect_ratio__in=("9:16", "16:9")),
                name="video_asset_aspect_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="videoasset",
            constraint=models.CheckConstraint(
                condition=models.Q(resolution="720P"), name="video_asset_resolution_720p"
            ),
        ),
        migrations.AddConstraint(
            model_name="videoasset",
            constraint=models.CheckConstraint(
                condition=models.Q(version__gte=1), name="video_asset_version_gte_1"
            ),
        ),
    ]
