# Generated manually for XW-0301.
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("subjects", "0013_subject_enrichment_postgresql_guards"),
    ]

    operations = [
        migrations.CreateModel(
            name="KeywordSet",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("draft_subject_version", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="keyword_drafts", to="subjects.subjectversion")),
                ("subject", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="keyword_set", to="subjects.subject")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="keyword_sets", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "keyword_sets",
                "ordering": ("subject_id", "id"),
                "constraints": [models.CheckConstraint(condition=models.Q(("version__gte", 1)), name="keyword_set_version_gte_1")],
            },
        ),
        migrations.CreateModel(
            name="KeywordSetVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("version_no", models.PositiveBigIntegerField()),
                ("content_digest", models.CharField(max_length=64)),
                ("item_count", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_keyword_versions", to=settings.AUTH_USER_MODEL)),
                ("keyword_set", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="versions", to="keywords.keywordset")),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="keyword_versions", to="subjects.subject")),
                ("subject_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="keyword_versions", to="subjects.subjectversion")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="keyword_versions", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "keyword_set_versions",
                "ordering": ("keyword_set_id", "version_no", "id"),
                "constraints": [
                    models.UniqueConstraint(fields=("keyword_set", "version_no"), name="keyword_version_number_unique"),
                    models.CheckConstraint(condition=models.Q(("version_no__gte", 1)), name="keyword_version_number_gte_1"),
                    models.CheckConstraint(condition=models.Q(("item_count__gte", 1)), name="keyword_version_item_count_gte_1"),
                    models.CheckConstraint(condition=~models.Q(("content_digest", "")), name="keyword_version_digest_present"),
                ],
            },
        ),
        migrations.AddField(
            model_name="keywordset",
            name="current_version",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="current_for_keyword_sets", to="keywords.keywordsetversion"),
        ),
        migrations.CreateModel(
            name="KeywordDraftItem",
            fields=[
                ("text", models.CharField(max_length=500)),
                ("matching_text", models.CharField(max_length=500)),
                ("structure_type", models.CharField(choices=[("short", "短关键词"), ("long_tail", "长尾关键词"), ("general", "通用关键词")], max_length=16)),
                ("is_regional", models.BooleanField(default=False)),
                ("region_level", models.CharField(blank=True, choices=[("country", "国家/地区"), ("province", "省/州"), ("city", "城市"), ("district", "区县"), ("custom", "自定义")], max_length=16)),
                ("region_text", models.CharField(blank=True, max_length=200)),
                ("region_matching_key", models.CharField(blank=True, max_length=240)),
                ("sort_order", models.PositiveIntegerField()),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("keyword_set", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="draft_items", to="keywords.keywordset")),
            ],
            options={
                "db_table": "keyword_draft_items",
                "ordering": ("keyword_set_id", "sort_order", "id"),
                "constraints": [
                    models.UniqueConstraint(fields=("keyword_set", "sort_order"), name="keyword_draft_sort_unique"),
                    models.UniqueConstraint(fields=("keyword_set", "matching_text", "region_matching_key"), name="keyword_draft_semantic_unique"),
                    models.CheckConstraint(condition=~models.Q(("text", "")) & ~models.Q(("matching_text", "")), name="keyword_draft_text_present"),
                    models.CheckConstraint(condition=models.Q(("structure_type__in", ("short", "long_tail", "general"))), name="keyword_draft_structure_valid"),
                    models.CheckConstraint(condition=models.Q(("region_level", "")) | models.Q(("region_level__in", ("country", "province", "city", "district", "custom"))), name="keyword_draft_region_level_valid"),
                    models.CheckConstraint(condition=models.Q(("is_regional", False), ("region_level", ""), ("region_matching_key", ""), ("region_text", "")) | (models.Q(("is_regional", True)) & ~models.Q(("region_text", "")) & ~models.Q(("region_matching_key", ""))), name="keyword_draft_region_shape"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Keyword",
            fields=[
                ("text", models.CharField(max_length=500)),
                ("matching_text", models.CharField(max_length=500)),
                ("structure_type", models.CharField(choices=[("short", "短关键词"), ("long_tail", "长尾关键词"), ("general", "通用关键词")], max_length=16)),
                ("is_regional", models.BooleanField(default=False)),
                ("region_level", models.CharField(blank=True, choices=[("country", "国家/地区"), ("province", "省/州"), ("city", "城市"), ("district", "区县"), ("custom", "自定义")], max_length=16)),
                ("region_text", models.CharField(blank=True, max_length=200)),
                ("region_matching_key", models.CharField(blank=True, max_length=240)),
                ("sort_order", models.PositiveIntegerField()),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("keyword_set_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="keywords", to="keywords.keywordsetversion")),
            ],
            options={
                "db_table": "keywords",
                "ordering": ("keyword_set_version_id", "sort_order", "id"),
                "constraints": [
                    models.UniqueConstraint(fields=("keyword_set_version", "sort_order"), name="keyword_formal_sort_unique"),
                    models.UniqueConstraint(fields=("keyword_set_version", "matching_text", "region_matching_key"), name="keyword_formal_semantic_unique"),
                    models.CheckConstraint(condition=~models.Q(("text", "")) & ~models.Q(("matching_text", "")), name="keyword_formal_text_present"),
                    models.CheckConstraint(condition=models.Q(("structure_type__in", ("short", "long_tail", "general"))), name="keyword_formal_structure_valid"),
                    models.CheckConstraint(condition=models.Q(("region_level", "")) | models.Q(("region_level__in", ("country", "province", "city", "district", "custom"))), name="keyword_formal_region_level_valid"),
                    models.CheckConstraint(condition=models.Q(("is_regional", False), ("region_level", ""), ("region_matching_key", ""), ("region_text", "")) | (models.Q(("is_regional", True)) & ~models.Q(("region_text", "")) & ~models.Q(("region_matching_key", ""))), name="keyword_formal_region_shape"),
                ],
            },
        ),
    ]
