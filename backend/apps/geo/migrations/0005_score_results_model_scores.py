import uuid

import django.db.models.deletion
from django.db import migrations, models

FORWARD_SQL = r"""
DROP TRIGGER IF EXISTS geo_score_results_immutable ON score_results;
CREATE TRIGGER geo_score_results_immutable
BEFORE UPDATE OR DELETE ON score_results
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

DROP TRIGGER IF EXISTS geo_model_scores_immutable ON model_scores;
CREATE TRIGGER geo_model_scores_immutable
BEFORE UPDATE OR DELETE ON model_scores
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS geo_score_results_immutable ON score_results;
DROP TRIGGER IF EXISTS geo_model_scores_immutable ON model_scores;
"""


def install(apps, schema_editor):
    del apps
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def reverse(apps, schema_editor):
    del apps
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("geo", "0004_programmatic_score_results")]

    operations = [
        migrations.CreateModel(
            name="ScoreResult",
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
                ("question_type", models.CharField(max_length=24)),
                (
                    "track",
                    models.CharField(
                        choices=[("geo", "GEO"), ("brand_reputation", "Brand reputation")],
                        max_length=24,
                    ),
                ),
                (
                    "mention_score",
                    models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        max_digits=7,
                        null=True,
                    ),
                ),
                (
                    "recommendation_score",
                    models.DecimalField(decimal_places=4, max_digits=7),
                ),
                (
                    "rank_score",
                    models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        max_digits=7,
                        null=True,
                    ),
                ),
                ("accuracy_score", models.DecimalField(decimal_places=4, max_digits=7)),
                ("sentiment_score", models.DecimalField(decimal_places=4, max_digits=7)),
                ("citation_score", models.DecimalField(decimal_places=4, max_digits=7)),
                ("total_score", models.DecimalField(decimal_places=4, max_digits=7)),
                ("scoring_rule_version", models.CharField(max_length=64)),
                ("semantic_schema_version", models.CharField(max_length=64)),
                ("semantic_provider_key", models.CharField(max_length=100)),
                ("semantic_model_key", models.CharField(max_length=100)),
                ("semantic_adapter_version", models.CharField(max_length=100)),
                ("semantic_prompt_version", models.CharField(max_length=100)),
                ("semantic_provider_model_id", models.CharField(max_length=255)),
                ("semantic_output_digest", models.CharField(max_length=64)),
                ("evidence", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "model_response",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="score_result",
                        to="geo.modelresponse",
                    ),
                ),
            ],
            options={"db_table": "score_results"},
        ),
        migrations.CreateModel(
            name="ModelScoreResult",
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
                    "track",
                    models.CharField(
                        choices=[("geo", "GEO"), ("brand_reputation", "Brand reputation")],
                        max_length=24,
                    ),
                ),
                ("planned_count", models.PositiveIntegerField()),
                ("successful_count", models.PositiveIntegerField()),
                (
                    "success_rate",
                    models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        max_digits=7,
                        null=True,
                    ),
                ),
                (
                    "score",
                    models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        max_digits=7,
                        null=True,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("formal", "Formal"),
                            ("reference", "Reference"),
                            ("not_generated", "Not generated"),
                        ],
                        max_length=16,
                    ),
                ),
                ("scoring_rule_version", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "model_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="score_results",
                        to="geo.geodetectionmodelrun",
                    ),
                ),
            ],
            options={"db_table": "model_scores"},
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(question_type__in=("natural", "brand_directed")),
                name="score_result_qtype_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(track__in=("geo", "brand_reputation")),
                name="score_result_track_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        question_type="natural",
                        track="geo",
                        mention_score__isnull=False,
                        rank_score__isnull=False,
                    )
                    | models.Q(
                        question_type="brand_directed",
                        track="brand_reputation",
                        mention_score__isnull=True,
                        rank_score__isnull=True,
                    )
                ),
                name="score_result_track_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(recommendation_score__gte=0, recommendation_score__lte=100),
                name="score_result_recommend_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(accuracy_score__gte=0, accuracy_score__lte=100),
                name="score_result_accuracy_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(sentiment_score__gte=0, sentiment_score__lte=100),
                name="score_result_sentiment_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(citation_score__gte=0, citation_score__lte=100),
                name="score_result_citation_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(total_score__gte=0, total_score__lte=100),
                name="score_result_total_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(mention_score__isnull=True)
                | models.Q(mention_score__gte=0, mention_score__lte=100),
                name="score_result_mention_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(rank_score__isnull=True)
                | models.Q(rank_score__gte=0, rank_score__lte=100),
                name="score_result_rank_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=~models.Q(scoring_rule_version=""),
                name="score_result_rule_present",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=~models.Q(semantic_schema_version=""),
                name="score_result_schema_present",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreresult",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(semantic_provider_key="")
                    & ~models.Q(semantic_model_key="")
                    & ~models.Q(semantic_adapter_version="")
                    & ~models.Q(semantic_prompt_version="")
                    & ~models.Q(semantic_provider_model_id="")
                    & ~models.Q(semantic_output_digest="")
                ),
                name="score_result_provenance_present",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelscoreresult",
            constraint=models.UniqueConstraint(
                fields=("model_run", "track"),
                name="model_score_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelscoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(track__in=("geo", "brand_reputation")),
                name="model_score_track_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelscoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=("formal", "reference", "not_generated")),
                name="model_score_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelscoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(successful_count__lte=models.F("planned_count")),
                name="model_score_counts_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelscoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(success_rate__isnull=True)
                | models.Q(success_rate__gte=0, success_rate__lte=100),
                name="model_score_rate_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelscoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(score__isnull=True) | models.Q(score__gte=0, score__lte=100),
                name="model_score_value_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelscoreresult",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        status="not_generated",
                        planned_count=0,
                        successful_count=0,
                        success_rate__isnull=True,
                        score__isnull=True,
                    )
                    | models.Q(
                        status__in=("formal", "reference"),
                        planned_count__gte=1,
                        success_rate__isnull=False,
                    )
                ),
                name="model_score_state_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelscoreresult",
            constraint=models.CheckConstraint(
                condition=~models.Q(scoring_rule_version=""),
                name="model_score_rule_present",
            ),
        ),
        migrations.RunPython(install, reverse),
    ]
