import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("subjects", "0015_remove_catalog_revision_approval")]

    operations = [
        migrations.CreateModel(
            name="SubjectBusinessProfile",
            fields=[
                (
                    "subject",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="business_profile",
                        serialize=False,
                        to="subjects.subject",
                    ),
                ),
                (
                    "legal_entity_type",
                    models.CharField(
                        choices=[("company", "公司"), ("individual_business", "个体工商户")],
                        max_length=32,
                    ),
                ),
                ("contact_name", models.CharField(max_length=100)),
                ("contact_phone", models.CharField(max_length=32)),
                ("business_address", models.CharField(max_length=500)),
                ("primary_business", models.TextField()),
                ("brand_name", models.CharField(blank=True, max_length=200)),
                ("social_channels", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "subject_business_profiles"},
        ),
        migrations.AddConstraint(
            model_name="subjectbusinessprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(legal_entity_type__in=("company", "individual_business")),
                name="subject_profile_valid_entity_type",
            ),
        ),
    ]
