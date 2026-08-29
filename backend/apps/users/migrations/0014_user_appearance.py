from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0013_user_is_test_account"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="appearance_mode",
            field=models.CharField(
                choices=[("light", "浅色"), ("dark", "深色"), ("system", "跟随系统")],
                default="system",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="appearance_accent",
            field=models.CharField(
                choices=[
                    ("blue", "显问蓝"),
                    ("green", "青绿色"),
                    ("purple", "紫罗兰"),
                    ("orange", "暖橙色"),
                ],
                default="blue",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(("appearance_mode__in", ("light", "dark", "system"))),
                name="user_appearance_mode_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("appearance_accent__in", ("blue", "green", "purple", "orange"))
                ),
                name="user_appearance_accent_valid",
            ),
        ),
    ]
