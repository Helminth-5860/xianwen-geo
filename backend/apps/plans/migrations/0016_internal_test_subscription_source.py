from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("plans", "0015_remove_subscription_change_approval"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="subscription",
            name="subscription_source_type_valid",
        ),
        migrations.RemoveConstraint(
            model_name="subscription",
            name="subscription_source_consistent",
        ),
        migrations.AlterField(
            model_name="subscription",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("application", "套餐申请"),
                    ("trial_grant", "试用发放"),
                    ("plan_change", "套餐变更"),
                    ("internal_test", "内部测试授权"),
                ],
                default="application",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="subscription",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    source_type__in=(
                        "application",
                        "trial_grant",
                        "plan_change",
                        "internal_test",
                    )
                ),
                name="subscription_source_type_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="subscription",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        source_type="application",
                        is_trial=False,
                        source_application__isnull=False,
                        source_change__isnull=True,
                    )
                    | models.Q(
                        source_type="trial_grant",
                        is_trial=True,
                        source_application__isnull=True,
                        source_change__isnull=True,
                    )
                    | models.Q(
                        source_type="plan_change",
                        is_trial=False,
                        source_application__isnull=True,
                        source_change__isnull=False,
                    )
                    | models.Q(
                        source_type="internal_test",
                        is_trial=False,
                        source_application__isnull=True,
                        source_change__isnull=True,
                    )
                ),
                name="subscription_source_consistent",
            ),
        ),
    ]
