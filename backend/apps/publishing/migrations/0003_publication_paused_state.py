from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("publishing", "0002_publication_target_review_state")]

    operations = [
        migrations.AlterField(
            model_name="publication",
            name="status",
            field=models.CharField(
                choices=[
                    ("preparing", "准备中"),
                    ("queued", "等待发布"),
                    ("running", "正在发布"),
                    ("paused", "已暂停"),
                    ("partial", "部分完成"),
                    ("succeeded", "发布完成"),
                    ("failed", "发布未完成"),
                    ("cancelled", "已取消"),
                ],
                default="preparing",
                max_length=16,
            ),
        )
    ]
