import uuid

import django.db.models.deletion
from django.db import migrations, models

FORWARD_SQL = r"""
DROP TRIGGER IF EXISTS geo_model_response_citations_immutable ON model_response_citations;
CREATE TRIGGER geo_model_response_citations_immutable
BEFORE UPDATE OR DELETE ON model_response_citations
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS geo_model_response_citations_immutable ON model_response_citations;
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
    dependencies = [("geo", "0002_postgresql_guards")]

    operations = [
        migrations.CreateModel(
            name="ModelResponseCitation",
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
                ("sort_order", models.PositiveIntegerField()),
                ("title", models.CharField(blank=True, default="", max_length=500)),
                ("canonical_url", models.TextField(blank=True, default="")),
                ("source_name", models.CharField(blank=True, default="", max_length=500)),
                ("source_host", models.CharField(blank=True, default="", max_length=253)),
                ("quoted_text", models.TextField(blank=True, default="")),
                ("provider_rank", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "url_status",
                    models.CharField(
                        choices=[
                            ("safe", "Safe"),
                            ("missing", "Missing"),
                            ("invalid", "Invalid"),
                            ("blocked", "Blocked"),
                            ("unresolved", "Unresolved"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "source_category",
                    models.CharField(
                        choices=[("unknown", "Unknown"), ("web", "Web")],
                        default="unknown",
                        max_length=24,
                    ),
                ),
                (
                    "extraction_method",
                    models.CharField(
                        choices=[("provider", "Provider"), ("raw_text", "Raw text")],
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "model_response",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="citations",
                        to="geo.modelresponse",
                    ),
                ),
            ],
            options={
                "db_table": "model_response_citations",
                "ordering": ("model_response_id", "sort_order", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="modelresponsecitation",
            constraint=models.UniqueConstraint(
                fields=("model_response", "sort_order"),
                name="model_response_citation_sort_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelresponsecitation",
            constraint=models.CheckConstraint(
                condition=models.Q(provider_rank__isnull=True) | models.Q(provider_rank__gte=1),
                name="model_response_citation_rank_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelresponsecitation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    url_status__in=("safe", "missing", "invalid", "blocked", "unresolved")
                ),
                name="model_response_citation_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelresponsecitation",
            constraint=models.CheckConstraint(
                condition=~models.Q(url_status="safe")
                | (~models.Q(canonical_url="") & ~models.Q(source_host="")),
                name="model_response_citation_safe_url_present",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelresponsecitation",
            constraint=models.CheckConstraint(
                condition=models.Q(url_status="safe") | models.Q(canonical_url=""),
                name="model_response_citation_unsafe_url_hidden",
            ),
        ),
        migrations.RunPython(install, reverse),
    ]
