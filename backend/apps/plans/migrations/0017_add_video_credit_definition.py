from django.db import migrations

VIDEO_CREDIT_DEFINITION = {
    "name": "视频额度",
    "category": "quota",
    "value_type": "integer",
    "storage_kind": "plan_limit",
    "scope": "subscription",
    "quota_type": "video_credits",
    "minimum": 0,
    "maximum": 2**63 - 1,
    "unit": "second",
    "required": True,
    "default_value": 0,
    "enum_values": [],
    "json_schema": {},
    "description": "AI 视频生成额度；按生成视频秒数扣除",
    "status": "active",
    "catalog_version": 1,
    "sort_order": 225,
    "semantic_digest": "fb40452477faa7815304e97928ebe6cfe33dd5f534c75b34111cfe579c4bb930",
}


def add_video_credit_definition(apps, schema_editor):
    Definition = apps.get_model("plans", "PlanLimitDefinition")
    PlanLimit = apps.get_model("plans", "PlanLimit")
    row, _ = Definition.objects.update_or_create(
        key="video_credits",
        defaults=VIDEO_CREDIT_DEFINITION,
    )
    for version in apps.get_model("plans", "PlanVersion").objects.filter(status="draft"):
        PlanLimit.objects.get_or_create(
            plan_version_id=version.pk,
            limit_key="video_credits",
            defaults={
                "limit_definition_id": row.pk,
                "value_type": "integer",
                "integer_value": 0,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("plans", "0016_internal_test_subscription_source")]
    operations = [
        migrations.RunPython(add_video_credit_definition, migrations.RunPython.noop),
    ]
