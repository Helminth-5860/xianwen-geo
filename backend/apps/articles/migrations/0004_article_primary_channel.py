import uuid

import django.db.models.deletion
from django.db import migrations, models


GENERAL_CHANNEL_ID = uuid.UUID("22222222-0701-4000-8000-000000000099")


def seed_general_channel(apps, schema_editor):
    PublishingChannel = apps.get_model("articles", "PublishingChannel")
    ChannelTemplateVersion = apps.get_model("articles", "ChannelTemplateVersion")
    Article = apps.get_model("articles", "Article")

    channel, _ = PublishingChannel.objects.get_or_create(
        key="general",
        defaults={
            "id": GENERAL_CHANNEL_ID,
            "name": "通用型",
            "official_url": "",
            "channel_type": "general",
            "description": "适合官网、内容库和后续改编的通用文章。",
            "applicable_article_types": [],
            "image_ratios": ["16:9", "1:1"],
            "enabled": True,
            "sort_order": 0,
        },
    )
    if not ChannelTemplateVersion.objects.filter(channel=channel, is_current=True).exists():
        ChannelTemplateVersion.objects.create(
            channel=channel,
            version_no=1,
            rules={
                "title_max": 80,
                "structure": "清晰导语、正文分节、总结",
                "tone": "专业、自然、信息完整",
                "tags": False,
                "external_links": "仅保留可核验来源",
                "content_form": "通用长文",
            },
            prompt_version="channel-general-v1",
            is_current=True,
        )
    Article.objects.filter(primary_channel__isnull=True).update(primary_channel=channel)


class Migration(migrations.Migration):
    dependencies = [("articles", "0003_seed_domestic_publishing_channels")]

    operations = [
        migrations.AddField(
            model_name="article",
            name="primary_channel",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="primary_articles",
                to="articles.publishingchannel",
            ),
        ),
        migrations.RunPython(seed_general_channel, migrations.RunPython.noop),
    ]
