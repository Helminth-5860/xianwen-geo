from dataclasses import dataclass

CATALOG_VERSION = 2


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
    BuiltinSubjectType("enterprise", "企业 / 公司", "依法设立的企业或公司主体", "building", 10),
    BuiltinSubjectType(
        "individual_business", "个体工商户", "依法登记的个体工商户主体", "store", 20
    ),
    BuiltinSubjectType("brand", "品牌", "独立运营或对外传播的品牌主体", "trademark", 30),
    BuiltinSubjectType("product", "产品 / 服务", "独立产品或服务主体", "product", 40),
    BuiltinSubjectType("person", "个人IP / 人物", "个人品牌、创作者或公众人物主体", "user", 50),
    BuiltinSubjectType(
        "organization",
        "机构 / 组织",
        "机构、协会、学校或其他组织主体",
        "organization",
        60,
    ),
    BuiltinSubjectType("project", "项目", "独立运营或建设中的项目主体", "project", 70),
    BuiltinSubjectType("place", "景区 / 景点", "景区、景点或文旅目的地主体", "place", 80),
    BuiltinSubjectType("other", "其他", "不属于以上类型的其他主体", "subject", 90),
)

COMMON_FIELD_CATALOG = (
    CommonField(
        "name",
        "主体名称",
        "填写营业执照、品牌或公开资料中使用的正式名称",
        "text",
        True,
        10,
        True,
        "official_name",
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
        "target_audience",
        "服务对象 / 目标客户",
        "填写主体实际服务的客户或人群",
        "textarea",
        True,
        40,
        True,
        "none",
    ),
    CommonField(
        "service_regions",
        "业务覆盖区域",
        "填写产品或服务实际覆盖的全国、省或市范围",
        "textarea",
        True,
        50,
        True,
        "none",
    ),
    CommonField(
        "official_url", "官方链接", "主体的官方网站或权威页面", "url", False, 60, True, "none"
    ),
)

TYPE_BY_KEY = {item.key: item for item in SUBJECT_TYPE_CATALOG}
COMMON_FIELD_BY_KEY = {item.key: item for item in COMMON_FIELD_CATALOG}
