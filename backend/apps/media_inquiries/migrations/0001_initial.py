import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("subjects", "0017_promote_saved_subjects"),
        ("users", "0013_user_is_test_account"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PaidMediaInquiry",
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
                ("selected_media", models.JSONField()),
                ("item_count", models.PositiveIntegerField()),
                ("total_price", models.DecimalField(decimal_places=2, max_digits=16)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "待处理"),
                            ("contacted", "已联系"),
                            ("cancelled", "已取消"),
                            ("completed", "已完成"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("idempotency_key_digest", models.CharField(max_length=64, unique=True)),
                ("request_digest", models.CharField(max_length=64)),
                ("request_id", models.UUIDField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="paid_media_inquiries",
                        to="subjects.subject",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="paid_media_inquiries",
                        to="users.tenant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="paid_media_inquiries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "paid_media_inquiries",
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["user", "subject", "created_at"],
                        name="media_inquiry_owner_idx",
                    ),
                    models.Index(
                        fields=["status", "created_at"],
                        name="media_inquiry_status_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("status__in", ("pending", "contacted", "cancelled", "completed"))
                        ),
                        name="media_inquiry_status_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("item_count__gte", 1)),
                        name="media_inquiry_items_gte_1",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("total_price__gte", 0)),
                        name="media_inquiry_total_nonnegative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("version__gte", 1)),
                        name="media_inquiry_version_gte_1",
                    ),
                ],
            },
        )
    ]
