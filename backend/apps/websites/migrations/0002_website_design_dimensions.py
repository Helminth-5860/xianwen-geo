from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("websites", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="websiteproject",
            name="website_project_style_valid",
        ),
        migrations.AlterField(
            model_name="websiteproject",
            name="style_key",
            field=models.CharField(
                choices=[
                    ("professional", "专业商务"),
                    ("technology", "科技未来"),
                    ("premium", "高端品牌"),
                    ("industrial", "工业制造"),
                    ("local_service", "本地服务"),
                    ("authority", "内容权威"),
                ],
                default="professional",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="websiteproject",
            name="theme_key",
            field=models.CharField(
                choices=[
                    ("ocean", "深海蓝"),
                    ("obsidian", "曜石黑"),
                    ("cloud", "云雾灰"),
                    ("amethyst", "紫晶"),
                    ("jade", "翡翠绿"),
                    ("gold", "暖金"),
                ],
                default="ocean",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="websiteproject",
            name="density_key",
            field=models.CharField(
                choices=[
                    ("compact", "简洁"),
                    ("standard", "标准"),
                    ("rich", "丰富"),
                ],
                default="standard",
                max_length=24,
            ),
        ),
        migrations.AddConstraint(
            model_name="websiteproject",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    style_key__in=(
                        "professional",
                        "technology",
                        "premium",
                        "industrial",
                        "local_service",
                        "authority",
                    )
                ),
                name="website_project_style_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="websiteproject",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    theme_key__in=("ocean", "obsidian", "cloud", "amethyst", "jade", "gold")
                ),
                name="website_project_theme_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="websiteproject",
            constraint=models.CheckConstraint(
                condition=models.Q(density_key__in=("compact", "standard", "rich")),
                name="website_project_density_valid",
            ),
        ),
    ]
