from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0012_remove_account_review"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_test_account",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
