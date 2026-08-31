from django.db import migrations, models

ACTIVE_TYPES = (
    ("enterprise", "企业 / 公司", "依法设立的企业或公司主体", "building", 10),
    ("individual_business", "个体工商户", "依法登记的个体工商户主体", "store", 20),
    ("brand", "品牌", "独立运营或对外传播的品牌主体", "trademark", 30),
    ("product", "产品 / 服务", "独立产品或服务主体", "product", 40),
    ("person", "个人IP / 人物", "个人品牌、创作者或公众人物主体", "user", 50),
    ("organization", "机构 / 组织", "机构、协会、学校或其他组织主体", "organization", 60),
    ("project", "项目", "独立运营或建设中的项目主体", "project", 70),
    ("place", "景区 / 景点", "景区、景点或文旅目的地主体", "place", 80),
    ("other", "其他", "不属于以上类型的其他主体", "subject", 90),
)

LEGACY_TYPE_KEYS = ("store", "service", "professional_institution")

FIELD_CATALOG = {
    "name": (
        "主体名称",
        "填写营业执照、品牌或公开资料中使用的正式名称",
        True,
        10,
        True,
        "official_name",
    ),
    "summary": (
        "主体简介",
        "主体的简要介绍",
        False,
        20,
        True,
        "none",
    ),
    "core_products_services": (
        "核心产品／服务",
        "主体提供的核心产品或服务",
        False,
        30,
        True,
        "none",
    ),
    "target_audience": (
        "服务对象 / 目标客户",
        "填写主体实际服务的客户或人群",
        True,
        40,
        True,
        "none",
    ),
    "service_regions": (
        "业务覆盖区域",
        "填写产品或服务实际覆盖的全国、省或市范围",
        True,
        50,
        True,
        "none",
    ),
    "official_url": (
        "官方链接",
        "主体的官方网站或权威页面",
        False,
        60,
        True,
        "none",
    ),
}


def refresh_subject_catalog(apps, schema_editor):
    SubjectType = apps.get_model("subjects", "SubjectType")
    Definition = apps.get_model("subjects", "SubjectFieldDefinition")
    Config = apps.get_model("subjects", "SubjectTypeFieldConfig")

    definitions = {
        item.field_key: item
        for item in Definition.objects.filter(
            scope="common",
            owner_subject_type__isnull=True,
            is_builtin=True,
        )
    }

    for key, name, description, icon_key, sort_order in ACTIVE_TYPES:
        subject_type, created = SubjectType.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "description": description,
                "icon_key": icon_key,
                "status": "active",
                "sort_order": sort_order,
                "is_builtin": True,
            },
        )
        metadata_changed = False
        for field, value in (
            ("name", name),
            ("description", description),
            ("icon_key", icon_key),
            ("status", "active"),
            ("sort_order", sort_order),
            ("is_builtin", True),
        ):
            if getattr(subject_type, field) != value:
                setattr(subject_type, field, value)
                metadata_changed = True

        schema_changed = False
        for field_key, definition in definitions.items():
            if field_key not in FIELD_CATALOG:
                continue
            label, field_description, required, field_order, used_for_ai, name_role = FIELD_CATALOG[
                field_key
            ]
            config, config_created = Config.objects.get_or_create(
                subject_type=subject_type,
                field_definition=definition,
                defaults={
                    "label": label,
                    "description": field_description,
                    "required": required,
                    "default_value": None,
                    "sort_order": field_order,
                    "enabled": True,
                    "used_for_ai": used_for_ai,
                    "name_role": name_role,
                },
            )
            schema_changed = schema_changed or config_created
            changed_fields = []
            for field, value in (
                ("label", label),
                ("description", field_description),
                ("required", required),
                ("sort_order", field_order),
                ("enabled", True),
                ("used_for_ai", used_for_ai),
                ("name_role", name_role),
            ):
                if getattr(config, field) != value:
                    setattr(config, field, value)
                    changed_fields.append(field)
            if changed_fields:
                config.version += 1
                config.save(update_fields=(*changed_fields, "version", "updated_at"))
                schema_changed = True

        if schema_changed and not created:
            subject_type.schema_version += 1
            metadata_changed = True
        if metadata_changed:
            subject_type.version += 1
            subject_type.save()

    SubjectType.objects.filter(key__in=LEGACY_TYPE_KEYS, status="active").update(
        status="inactive",
        version=models.F("version") + 1,
    )


class Migration(migrations.Migration):
    dependencies = [("subjects", "0017_promote_saved_subjects")]

    operations = [
        migrations.AddField(
            model_name="subjectbusinessprofile",
            name="industry",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="subjectbusinessprofile",
            name="subject_aliases",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="subjectbusinessprofile",
            name="unified_social_credit_code",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AlterField(
            model_name="subjectbusinessprofile",
            name="contact_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="subjectbusinessprofile",
            name="contact_phone",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.RunPython(refresh_subject_catalog, migrations.RunPython.noop),
    ]
