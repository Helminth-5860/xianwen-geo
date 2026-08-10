from dataclasses import dataclass

CATALOG_VERSION = 1


@dataclass(frozen=True)
class BuiltinSubjectType:
    key: str
    name: str
    description: str
    icon_key: str
    sort_order: int


@dataclass(frozen=True)
class CommonField:
    key: str
    label: str
    description: str
    field_type: str
    required: bool
    sort_order: int
    used_for_ai: bool
    name_role: str


SUBJECT_TYPE_CATALOG = (
    BuiltinSubjectType("enterprise", "企业", "企业主体", "building", 10),
    BuiltinSubjectType("brand", "品牌", "品牌主体", "trademark", 20),
    BuiltinSubjectType("product", "产品", "产品主体", "product", 30),
    BuiltinSubjectType("person", "人物", "人物主体", "user", 40),
    BuiltinSubjectType("organization", "机构", "机构主体", "organization", 50),
    BuiltinSubjectType("store", "门店", "门店主体", "store", 60),
    BuiltinSubjectType("service", "服务", "服务主体", "service", 70),
    BuiltinSubjectType("project", "项目", "项目主体", "project", 80),
    BuiltinSubjectType("place", "景区／地点", "景区或地点主体", "place", 90),
    BuiltinSubjectType(
        "professional_institution",
        "学校／医院等专业机构",
        "学校、医院等专业机构主体",
        "institution",
        100,
    ),
)

COMMON_FIELD_CATALOG = (
    CommonField(
        "name", "主体名称", "主体最常用的正式名称", "text", True, 10, True, "official_name"
    ),
    CommonField("summary", "主体简介", "主体的简要介绍", "textarea", False, 20, True, "none"),
    CommonField(
        "core_products_services",
        "核心产品／服务",
        "主体提供的核心产品或服务",
        "textarea",
        False,
        30,
        True,
        "none",
    ),
    CommonField(
        "target_audience", "目标用户", "主体主要服务的目标用户", "textarea", False, 40, True, "none"
    ),
    CommonField(
        "service_regions", "服务地区", "主体提供服务的地区", "textarea", False, 50, True, "none"
    ),
    CommonField(
        "official_url", "官方链接", "主体的官方网站或权威页面", "url", False, 60, True, "none"
    ),
)

TYPE_BY_KEY = {item.key: item for item in SUBJECT_TYPE_CATALOG}
COMMON_FIELD_BY_KEY = {item.key: item for item in COMMON_FIELD_CATALOG}
