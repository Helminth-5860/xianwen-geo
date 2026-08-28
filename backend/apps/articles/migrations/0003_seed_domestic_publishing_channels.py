from __future__ import annotations

import uuid

from django.db import migrations


CHANNELS = (
    ("wechat", "微信公众号", "https://mp.weixin.qq.com/", "social_content", ["2.35:1", "16:9"], {"title_max": 64, "structure": "导语、分节、总结", "tone": "专业易读", "tags": False, "external_links": "按平台规则", "content_form": "完整长图文"}),
    ("toutiao", "今日头条", "https://mp.toutiao.com/", "social_content", ["16:9", "3:2"], {"title_max": 30, "structure": "结论先行、信息分节、总结", "tone": "资讯化、清晰直接", "tags": True, "external_links": "克制使用", "content_form": "资讯阅读型长文"}),
    ("baijiahao", "百家号", "https://baijiahao.baidu.com/", "social_content", ["16:9", "3:2"], {"title_max": 64, "structure": "问题背景、核心信息、方法或观点、总结", "tone": "搜索友好、事实清晰", "tags": True, "external_links": "按平台规则", "content_form": "知识资讯长文"}),
    ("zhihu", "知乎", "https://www.zhihu.com/", "knowledge_community", ["16:9", "1:1"], {"title_max": 80, "structure": "问题导向、结论先行、论据、总结", "tone": "理性解释、专业可信", "tags": True, "external_links": "克制使用", "content_form": "问答或专栏长文"}),
    ("xiaohongshu", "小红书", "https://creator.xiaohongshu.com/", "social_content", ["3:4", "1:1"], {"title_max": 20, "structure": "短开场、要点列表、结论", "tone": "自然、具体、不夸张", "tags": True, "external_links": "不主动添加", "content_form": "图文短内容", "text_max": 1000}),
    ("weibo", "微博", "https://weibo.com/", "social_content", ["1:1", "16:9"], {"title_max": 40, "structure": "核心摘要、要点、话题", "tone": "简洁直接", "tags": True, "external_links": "可保留一个核心链接", "content_form": "摘要或头条文章"}),
    ("bilibili", "B站专栏", "https://member.bilibili.com/", "social_content", ["16:9", "4:3"], {"title_max": 64, "structure": "导语、分节、总结", "tone": "清晰易读、知识型", "tags": True, "external_links": "按平台规则", "content_form": "专栏文章"}),
    ("douyin", "抖音图文", "https://creator.douyin.com/", "social_content", ["3:4", "9:16"], {"title_max": 30, "structure": "短标题、核心观点、图文卡片要点", "tone": "短、具体、可扫读", "tags": True, "external_links": "不主动添加", "content_form": "图文卡片", "text_max": 800}),
    ("qq", "企鹅号", "https://om.qq.com/", "social_content", ["16:9", "3:2"], {"title_max": 64, "structure": "导语、正文分节、总结", "tone": "资讯化、专业", "tags": True, "external_links": "按平台规则", "content_form": "资讯长文"}),
    ("sohu", "搜狐号", "https://mp.sohu.com/", "social_content", ["16:9", "3:2"], {"title_max": 64, "structure": "导语、正文分节、总结", "tone": "资讯化、简洁", "tags": True, "external_links": "按平台规则", "content_form": "资讯长文"}),
    ("csdn", "CSDN", "https://mp.csdn.net/", "technical_community", ["16:9", "1:1"], {"title_max": 100, "structure": "背景、原理或步骤、实践建议、总结", "tone": "技术专业、可复用", "tags": True, "external_links": "允许可核验来源", "content_form": "技术文章"}),
    ("juejin", "掘金", "https://juejin.cn/creator/content/article/new", "technical_community", ["16:9", "1:1"], {"title_max": 80, "structure": "问题、方案、实践、总结", "tone": "技术专业、开发者友好", "tags": True, "external_links": "允许可核验来源", "content_form": "技术文章"}),
    ("cnblogs", "博客园", "https://i.cnblogs.com/posts/edit", "technical_community", ["16:9", "1:1"], {"title_max": 120, "structure": "背景、正文分节、实践、总结", "tone": "技术记录型", "tags": True, "external_links": "允许可核验来源", "content_form": "技术博客"}),
    ("oschina", "开源中国", "https://my.oschina.net/", "technical_community", ["16:9", "1:1"], {"title_max": 100, "structure": "背景、观点或实践、总结", "tone": "技术社区、专业", "tags": True, "external_links": "允许可核验来源", "content_form": "技术文章"}),
    ("segmentfault", "思否", "https://segmentfault.com/write", "technical_community", ["16:9", "1:1"], {"title_max": 100, "structure": "问题、分析、解决方案、总结", "tone": "技术问答与实践", "tags": True, "external_links": "允许可核验来源", "content_form": "技术文章"}),
    ("jianshu", "简书", "https://www.jianshu.com/writer", "content_community", ["16:9", "1:1"], {"title_max": 100, "structure": "导语、正文分节、总结", "tone": "自然、完整", "tags": False, "external_links": "克制使用", "content_form": "长文"}),
    ("douban", "豆瓣", "https://www.douban.com/", "content_community", ["16:9", "1:1"], {"title_max": 100, "structure": "背景、正文、总结", "tone": "自然、克制、信息型", "tags": False, "external_links": "克制使用", "content_form": "长文"}),
)


BASE_NAMESPACE = uuid.UUID("8d23976f-e244-43b3-a4b0-2c08f092b542")


def seed_domestic_channels(apps, schema_editor):
    PublishingChannel = apps.get_model("articles", "PublishingChannel")
    ChannelTemplateVersion = apps.get_model("articles", "ChannelTemplateVersion")

    for order, (key, name, url, channel_type, image_ratios, rules) in enumerate(CHANNELS, start=10):
        channel_id = uuid.uuid5(BASE_NAMESPACE, f"channel:{key}")
        channel, _ = PublishingChannel.objects.update_or_create(
            key=key,
            defaults={
                "id": channel_id,
                "name": name,
                "official_url": url,
                "channel_type": channel_type,
                "description": "显问自动发文渠道；内容适配与真实发布能力需按平台逐项验收后开放。",
                "applicable_article_types": [],
                "image_ratios": image_ratios,
                "enabled": True,
                "sort_order": order,
            },
        )
        current = ChannelTemplateVersion.objects.filter(channel=channel, is_current=True).first()
        if current is not None and current.rules == rules:
            continue
        if current is not None:
            current.is_current = False
            current.save(update_fields=("is_current",))
        latest = ChannelTemplateVersion.objects.filter(channel=channel).order_by("-version_no").first()
        version_no = 1 if latest is None else latest.version_no + 1
        ChannelTemplateVersion.objects.create(
            channel=channel,
            version_no=version_no,
            rules=rules,
            prompt_version=f"channel-{key}-publishing-v1",
            is_current=True,
        )


class Migration(migrations.Migration):
    dependencies = [("articles", "0002_seed_catalogs_and_postgresql_guards")]
    operations = [migrations.RunPython(seed_domestic_channels, migrations.RunPython.noop)]
