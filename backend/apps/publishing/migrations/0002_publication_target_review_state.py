from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("publishing", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="publicationtarget",
            name="status",
            field=models.CharField(
                choices=[
                    ("waiting", "等待发布"),
                    ("ready", "已准备"),
                    ("running", "正在发布"),
                    ("submitted", "平台审核中"),
                    ("succeeded", "已发布"),
                    ("failed", "发布失败"),
                    ("auth_required", "需要重新授权"),
                    ("paused", "已暂停"),
                ],
                default="waiting",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="publicationtarget",
            name="submitted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="publicationtarget",
            name="management_url",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="publicationtarget",
            name="next_status_check_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
