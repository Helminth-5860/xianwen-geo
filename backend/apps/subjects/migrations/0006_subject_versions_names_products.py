import django.db.models.deletion
import uuid
from django.db import migrations, models


def reject_existing_subject_versions(apps, schema_editor):
    SubjectVersion = apps.get_model("subjects", "SubjectVersion")
    if SubjectVersion.objects.exists():
        raise RuntimeError(
            "Existing SubjectVersion rows require manual XW-0203 integrity review; "
            "the migration will not fabricate current-version or semantic evidence."
        )


def block_reverse_with_formal_versions(apps, schema_editor):
    SubjectVersion = apps.get_model("subjects", "SubjectVersion")
    if SubjectVersion.objects.exists():
        raise RuntimeError(
            "XW-0203 formal subject evidence exists; destructive reverse requires manual review."
        )


class Migration(migrations.Migration):
    dependencies = [("subjects", "0005_subject_data_postgresql_guards")]

    operations = [
        migrations.RunPython(reject_existing_subject_versions, migrations.RunPython.noop),
        migrations.AddField(
            model_name="subjectversion",
            name="field_values_digest",
            field=models.CharField(max_length=64),
        ),
        migrations.AddField(
            model_name="subjectversion",
            name="official_name",
            field=models.CharField(max_length=500),
        ),
        migrations.AddField(
            model_name="subjectversion",
            name="semantic_digest",
            field=models.CharField(max_length=64),
        ),
        migrations.AddField(
            model_name="subject",
            name="current_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="current_for_subjects",
                to="subjects.subjectversion",
            ),
        ),
        migrations.AddField(
            model_name="subject",
            name="retest_required",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="SubjectName",
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
                    "role",
                    models.CharField(
                        choices=[
                            ("official_name", "\u6b63\u5f0f\u540d\u79f0"),
                            ("alias", "\u522b\u540d"),
                            ("english_name", "\u82f1\u6587\u540d"),
                        ],
                        max_length=32,
                    ),
                ),
                ("display_value", models.CharField(max_length=500)),
                ("matching_value", models.CharField(max_length=500)),
                ("source_field_key", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subject_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="names",
                        to="subjects.subjectversion",
                    ),
                ),
            ],
            options={
                "db_table": "subject_names",
                "ordering": ("subject_version_id", "role", "display_value", "id"),
            },
        ),
        migrations.CreateModel(
            name="SubjectProduct",
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
                ("candidate_key", models.CharField(max_length=64)),
                ("display_value", models.CharField(max_length=500)),
                ("matching_value", models.CharField(max_length=500)),
                ("source_field_key", models.CharField(max_length=64)),
                ("uniqueness_confirmed", models.BooleanField(default=False)),
                ("include_in_mention", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subject_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="products",
                        to="subjects.subjectversion",
                    ),
                ),
            ],
            options={
                "db_table": "subject_products",
                "ordering": ("subject_version_id", "display_value", "id"),
            },
        ),
        migrations.AddField(
            model_name="subjectevent",
            name="subject_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="events",
                to="subjects.subjectversion",
            ),
        ),
        migrations.AlterField(
            model_name="subjectevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("created", "\u5df2\u521b\u5efa"),
                    ("activated", "\u5df2\u542f\u7528"),
                    ("archived", "\u5df2\u5f52\u6863"),
                    ("current_selected", "\u5df2\u8bbe\u4e3a\u5f53\u524d\u4e3b\u4f53"),
                    ("current_cleared", "\u5df2\u6e05\u9664\u5f53\u524d\u4e3b\u4f53"),
                    ("version_committed", "\u5df2\u63d0\u4ea4\u6b63\u5f0f\u7248\u672c"),
                ],
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="subjectname",
            constraint=models.UniqueConstraint(
                fields=("subject_version", "role", "matching_value"),
                name="subject_name_version_role_value_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="subjectname",
            constraint=models.CheckConstraint(
                condition=models.Q(role__in=("official_name", "alias", "english_name")),
                name="subject_name_valid_role",
            ),
        ),
        migrations.AddConstraint(
            model_name="subjectproduct",
            constraint=models.UniqueConstraint(
                fields=("subject_version", "candidate_key"),
                name="subject_product_candidate_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="subjectproduct",
            constraint=models.UniqueConstraint(
                fields=("subject_version", "matching_value"),
                name="subject_product_value_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="subjectproduct",
            constraint=models.CheckConstraint(
                condition=models.Q(include_in_mention=False)
                | models.Q(uniqueness_confirmed=True),
                name="subject_product_mention_requires_unique",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            block_reverse_with_formal_versions,
        ),
    ]
