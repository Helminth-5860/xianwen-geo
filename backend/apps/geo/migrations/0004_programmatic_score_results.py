import uuid

import django.db.models.deletion
from django.db import migrations, models

FORWARD_SQL = r"""
DROP TRIGGER IF EXISTS geo_programmatic_scores_immutable ON programmatic_score_results;
CREATE TRIGGER geo_programmatic_scores_immutable
BEFORE UPDATE OR DELETE ON programmatic_score_results
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS geo_programmatic_scores_immutable ON programmatic_score_results;
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
    dependencies = [("geo", "0003_model_response_citations")]

    operations = [
        migrations.CreateModel(
            name="ProgrammaticScoreResult",
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
                ("scoring_rule_version", models.CharField(max_length=64)),
                ("question_type", models.CharField(max_length=24)),
                ("mention_score", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("matched_kind", models.CharField(blank=True, default="", max_length=32)),
                ("matched_value", models.CharField(blank=True, default="", max_length=500)),
                ("rank_position", models.PositiveIntegerField(blank=True, null=True)),
                ("rank_score", models.PositiveSmallIntegerField(blank=True, null=True)),
                (
                    "rank_resolution",
                    models.CharField(
                        choices=[
                            ("deterministic", "Deterministic"),
                            ("semantic_required", "Semantic required"),
                            ("not_applicable", "Not applicable"),
                        ],
                        max_length=24,
                    ),
                ),
                ("citation_base_score", models.PositiveSmallIntegerField(blank=True, null=True)),
                (
                    "citation_resolution",
                    models.CharField(
                        choices=[
                            ("deterministic", "Deterministic"),
                            ("semantic_required", "Semantic required"),
                        ],
                        max_length=24,
                    ),
                ),
                ("citation_evidence_count", models.PositiveIntegerField(default=0)),
                ("evidence", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "model_response",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programmatic_score",
                        to="geo.modelresponse",
                    ),
                ),
            ],
            options={"db_table": "programmatic_score_results"},
        ),
        migrations.AddConstraint(
            model_name="programmaticscoreresult",
            constraint=models.CheckConstraint(
                condition=~models.Q(scoring_rule_version=""),
                name="programmatic_score_rule_present",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmaticscoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(question_type__in=("natural", "brand_directed")),
                name="programmatic_score_question_type_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmaticscoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(mention_score__isnull=True)
                | models.Q(mention_score__in=(0, 100)),
                name="programmatic_score_mention_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmaticscoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(rank_position__isnull=True) | models.Q(rank_position__gte=1),
                name="programmatic_score_rank_position_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmaticscoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(rank_score__isnull=True)
                | models.Q(rank_score__in=(0, 20, 40, 60, 80, 100)),
                name="programmatic_score_rank_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmaticscoreresult",
            constraint=models.CheckConstraint(
                condition=models.Q(citation_base_score__isnull=True)
                | models.Q(citation_base_score__in=(0, 20)),
                name="programmatic_score_citation_base_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmaticscoreresult",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        question_type="brand_directed",
                        mention_score__isnull=True,
                        rank_score__isnull=True,
                        rank_position__isnull=True,
                        rank_resolution="not_applicable",
                    )
                    | models.Q(question_type="natural")
                ),
                name="programmatic_score_brand_na_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmaticscoreresult",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(rank_resolution="deterministic", rank_score__isnull=False)
                    | models.Q(
                        rank_resolution__in=("semantic_required", "not_applicable"),
                        rank_score__isnull=True,
                    )
                ),
                name="programmatic_score_rank_resolution_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="programmaticscoreresult",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        citation_resolution="deterministic",
                        citation_base_score__isnull=False,
                    )
                    | models.Q(
                        citation_resolution="semantic_required",
                        citation_base_score__isnull=True,
                    )
                ),
                name="programmatic_score_citation_resolution_valid",
            ),
        ),
        migrations.RunPython(install, reverse),
    ]
