import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("subjects", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PublicationVerificationCheck",
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
                ("requested_url", models.TextField()),
                ("final_url", models.TextField()),
                ("hostname", models.CharField(blank=True, max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("published", "Published"),
                            ("failed", "Failed"),
                            ("unknown", "Unknown"),
                        ],
                        max_length=16,
                    ),
                ),
                ("page_title", models.CharField(blank=True, max_length=500)),
                ("http_status", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("response_time_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("result_message", models.CharField(blank=True, max_length=500)),
                ("safe_failure_code", models.CharField(blank=True, max_length=100)),
                ("checked_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="publication_verification_checks",
                        to="subjects.subject",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "publication_verification_checks",
                "ordering": ("-checked_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="publicationverificationcheck",
            index=models.Index(
                fields=["user", "subject", "-checked_at"],
                name="pubverify_user_subj_idx",
            ),
        ),
    ]
