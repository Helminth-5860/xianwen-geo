from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="loginevent",
            name="login_method",
            field=models.CharField(
                choices=[("password", "密码"), ("sms", "短信验证码")],
                max_length=16,
            ),
        ),
    ]