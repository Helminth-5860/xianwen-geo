# Generated manually for source-index v1.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("subjects", "0017_promote_saved_subjects"),
    ]

    operations = [
        migrations.CreateModel(
            name="SourceIndexScan",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("partial", "Partial"),
                            ("limit_reached", "Limit reached"),
                            ("failed", "Failed"),
                        ],
                        default="queued",
                        max_length=20,
                    ),
                ),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("preparing", "Preparing"),
                            ("searching", "Searching"),
                            ("classifying", "Classifying"),
                            ("scoring", "Scoring"),
                            ("completed", "Completed"),
                        ],
                        default="preparing",
                        max_length=20,
                    ),
                ),
                ("provider", models.CharField(default="baidu", max_length=32)),
                ("query_count", models.PositiveIntegerField(default=0)),
                ("provider_request_count", models.PositiveIntegerField(default=0)),
                ("provider_error_count", models.PositiveIntegerField(default=0)),
                ("raw_result_count", models.PositiveIntegerField(default=0)),
                ("unique_result_count", models.PositiveIntegerField(default=0)),
                ("public_source_count", models.PositiveIntegerField(default=0)),
                ("independent_domain_count", models.PositiveIntegerField(default=0)),
                ("news_media_count", models.PositiveIntegerField(default=0)),
                ("high_weight_count", models.PositiveIntegerField(default=0)),
                ("recent_30d_count", models.PositiveIntegerField(default=0)),
                (
                    "index_score",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=5,
                        null=True,
                    ),
                ),
                ("factor_scores", models.JSONField(default=dict)),
                ("progress", models.JSONField(default=dict)),
                (
                    "formula_version",
                    models.CharField(default="source-index-v1", max_length=64),
                ),
                ("stable_error_code", models.CharField(blank=True, max_length=100)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("elapsed_ms", models.PositiveBigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="source_index_scans",
                        to="subjects.subject",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="source_index_scans",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "source_index_scans",
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["user", "subject", "created_at"],
                        name="src_scan_user_subj_idx",
                    ),
                    models.Index(
                        fields=["status", "created_at"],
                        name="src_scan_status_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            status__in=(
                                "queued",
                                "running",
                                "succeeded",
                                "partial",
                                "limit_reached",
                                "failed",
                            )
                        ),
                        name="src_scan_status_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            stage__in=(
                                "preparing",
                                "searching",
                                "classifying",
                                "scoring",
                                "completed",
                            )
                        ),
                        name="src_scan_stage_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(index_score__isnull=True)
                        | models.Q(index_score__gte=0, index_score__lte=100),
                        name="src_scan_index_range",
                    ),
                    models.UniqueConstraint(
                        fields=("user", "subject"),
                        condition=models.Q(status__in=("queued", "running")),
                        name="src_scan_one_active_per_subject",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SourceIndexItem",
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
                ("original_url", models.URLField(max_length=4096)),
                ("normalized_url", models.CharField(max_length=4096)),
                ("domain", models.CharField(max_length=255)),
                ("root_domain", models.CharField(max_length=255)),
                ("website", models.CharField(blank=True, max_length=500)),
                ("title", models.CharField(max_length=1000)),
                ("snippet", models.TextField(blank=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                (
                    "source_type",
                    models.CharField(
                        choices=[
                            ("government_association", "政府/协会"),
                            ("news_media", "新闻媒体"),
                            ("industry_media", "行业媒体"),
                            ("enterprise_site", "企业网站"),
                            ("content_platform", "内容平台/自媒体"),
                            ("directory_business", "黄页/工商"),
                            ("forum_community", "论坛社区"),
                            ("other", "其他"),
                        ],
                        max_length=32,
                    ),
                ),
                ("authority_score", models.PositiveSmallIntegerField()),
                ("relevance_score", models.PositiveSmallIntegerField()),
                ("visibility_score", models.PositiveSmallIntegerField()),
                ("freshness_score", models.PositiveSmallIntegerField()),
                (
                    "source_weight",
                    models.DecimalField(decimal_places=2, max_digits=5),
                ),
                ("best_rank", models.PositiveIntegerField()),
                ("matched_query_count", models.PositiveIntegerField(default=1)),
                ("repost_cluster_id", models.CharField(blank=True, max_length=64)),
                (
                    "score_version",
                    models.CharField(default="source-weight-v1", max_length=64),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "scan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="source_index.sourceindexscan",
                    ),
                ),
            ],
            options={
                "db_table": "source_index_items",
                "ordering": ("-source_weight", "best_rank", "id"),
                "indexes": [
                    models.Index(
                        fields=["scan", "source_type", "source_weight"],
                        name="src_item_type_score_idx",
                    ),
                    models.Index(
                        fields=["scan", "root_domain"],
                        name="src_item_domain_idx",
                    ),
                    models.Index(
                        fields=["scan", "published_at"],
                        name="src_item_date_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("scan", "normalized_url"),
                        name="src_item_scan_url_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(authority_score__lte=100),
                        name="src_item_authority_lte100",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(relevance_score__lte=100),
                        name="src_item_relevance_lte100",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(visibility_score__lte=100),
                        name="src_item_visibility_lte100",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(freshness_score__lte=100),
                        name="src_item_freshness_lte100",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(source_weight__gte=0, source_weight__lte=100),
                        name="src_item_weight_range",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SourceIndexHit",
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
                ("query", models.CharField(max_length=200)),
                ("rank", models.PositiveIntegerField()),
                ("range_start", models.DateField(blank=True, null=True)),
                ("range_end", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hits",
                        to="source_index.sourceindexitem",
                    ),
                ),
                (
                    "scan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hits",
                        to="source_index.sourceindexscan",
                    ),
                ),
            ],
            options={
                "db_table": "source_index_hits",
                "ordering": ("scan_id", "query", "rank", "id"),
                "indexes": [
                    models.Index(
                        fields=["scan", "query", "rank"],
                        name="src_hit_query_rank_idx",
                    ),
                    models.Index(
                        fields=["item", "rank"],
                        name="src_hit_item_rank_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "scan",
                            "item",
                            "query",
                            "range_start",
                            "range_end",
                        ),
                        name="src_hit_scan_item_query_range_unique",
                        nulls_distinct=False,
                    ),
                ],
            },
        ),
    ]
