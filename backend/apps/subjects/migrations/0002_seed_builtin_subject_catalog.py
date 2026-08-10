from django.db import migrations


TYPES = (
    ("enterprise", "企业", "企业主体", "building", 10),
    ("brand", "品牌", "品牌主体", "trademark", 20),
    ("product", "产品", "产品主体", "product", 30),
    ("person", "人物", "人物主体", "user", 40),
    ("organization", "机构", "机构主体", "organization", 50),
    ("store", "门店", "门店主体", "store", 60),
    ("service", "服务", "服务主体", "service", 70),
    ("project", "项目", "项目主体", "project", 80),
    ("place", "景区／地点", "景区或地点主体", "place", 90),
    (
        "professional_institution",
        "学校／医院等专业机构",
        "学校、医院等专业机构主体",
        "institution",
        100,
    ),
)

FIELDS = (
    ("name", "主体名称", "主体最常用的正式名称", "text", True, 10, True, "official_name"),
    ("summary", "主体简介", "主体的简要介绍", "textarea", False, 20, True, "none"),
    (
        "core_products_services",
        "核心产品／服务",
        "主体提供的核心产品或服务",
        "textarea",
        False,
        30,
        True,
        "none",
    ),
    ("target_audience", "目标用户", "主体主要服务的目标用户", "textarea", False, 40, True, "none"),
    ("service_regions", "服务地区", "主体提供服务的地区", "textarea", False, 50, True, "none"),
    ("official_url", "官方链接", "主体的官方网站或权威页面", "url", False, 60, True, "none"),
)


def seed_catalog(apps, schema_editor):
    SubjectType = apps.get_model("subjects", "SubjectType")
    Definition = apps.get_model("subjects", "SubjectFieldDefinition")
    Config = apps.get_model("subjects", "SubjectTypeFieldConfig")
    definitions = {}
    for key, _label, _description, field_type, *_rest in FIELDS:
        definition, _ = Definition.objects.get_or_create(
            scope="common",
            owner_subject_type=None,
            field_key=key,
            defaults={"field_type": field_type, "is_builtin": True},
        )
        if definition.field_type != field_type or not definition.is_builtin:
            raise RuntimeError(f"公共字段 {key} 的机器语义不一致。")
        definitions[key] = definition
    for key, name, description, icon_key, sort_order in TYPES:
        subject_type, _ = SubjectType.objects.get_or_create(
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
        if not subject_type.is_builtin:
            raise RuntimeError(f"内置主体类型 {key} 的机器语义不一致。")
        for (
            field_key,
            label,
            field_description,
            _field_type,
            required,
            field_sort_order,
            used_for_ai,
            name_role,
        ) in FIELDS:
            Config.objects.get_or_create(
                subject_type=subject_type,
                field_definition=definitions[field_key],
                defaults={
                    "label": label,
                    "description": field_description,
                    "required": required,
                    "default_value": None,
                    "sort_order": field_sort_order,
                    "enabled": True,
                    "used_for_ai": used_for_ai,
                    "name_role": name_role,
                },
            )


class Migration(migrations.Migration):
    dependencies = [("subjects", "0001_initial")]

    operations = [migrations.RunPython(seed_catalog, migrations.RunPython.noop)]
