from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("website_audits", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="websiteauditpage",
            name="jsonld_block_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="websiteauditpage",
            name="jsonld_invalid_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="websiteauditpage",
            name="list_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="websiteauditpage",
            name="paragraph_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="websiteauditpage",
            name="schema_entities",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="websiteauditpage",
            name="table_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="websiteauditfinding",
            name="affected_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="websiteauditfinding",
            name="dimension",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="websiteauditfinding",
            name="impact",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="websiteauditfinding",
            name="method",
            field=models.CharField(
                choices=[
                    ("deterministic", "程序检测"),
                    ("browser", "浏览器检测"),
                    ("semantic", "语义分析"),
                ],
                default="deterministic",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="websiteauditfinding",
            name="recommendation",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="websiteauditfinding",
            name="rule_version",
            field=models.CharField(default="deterministic-v1", max_length=32),
        ),
    ]
