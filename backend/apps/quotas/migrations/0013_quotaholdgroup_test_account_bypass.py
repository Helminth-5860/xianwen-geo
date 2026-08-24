from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("quotas", "0012_subject_cycle_postgresql_guards"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotaholdgroup",
            name="is_test_account_bypass",
            field=models.BooleanField(default=False),
        ),
    ]
