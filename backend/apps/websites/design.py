from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction

from apps.subjects.models import Subject, SubjectBusinessProfile, SubjectProduct
from apps.subjects.subject_services import subject_for_user_or_404

from .models import WebsiteProject

STYLE_OPTIONS = (
    {
        "key": "professional",
        "name": "专业商务",
        "description": "稳重清晰，适合企业服务、咨询、贸易与企业间业务。",
    },
    {
        "key": "technology",
        "name": "科技未来",
        "description": "现代轻盈，适合软件、人工智能、数字化与科技业务。",
    },
    {
        "key": "premium",
        "name": "高端品牌",
        "description": "强调品牌质感与留白，适合重视形象表达的企业。",
    },
    {
        "key": "industrial",
        "name": "工业制造",
        "description": "突出产品、能力与应用场景，适合制造、设备与工程企业。",
    },
    {
        "key": "local_service",
        "name": "本地服务",
        "description": "突出服务项目、服务区域与联系入口，适合门店和本地服务。",
    },
    {
        "key": "authority",
        "name": "内容权威",
        "description": "强调专业知识、常见问题与内容可信度，适合专业服务与研究型企业。",
    },
)

THEME_OPTIONS = (
    {"key": "ocean", "name": "深海蓝", "description": "专业、可信、适用范围广。"},
    {"key": "obsidian", "name": "曜石黑", "description": "稳重、硬朗、强调高级感。"},
    {"key": "cloud", "name": "云雾灰", "description": "克制、清爽、突出内容本身。"},
    {"key": "amethyst", "name": "紫晶", "description": "现代、智能、具有科技感。"},
    {"key": "jade", "name": "翡翠绿", "description": "自然、可靠、亲和而清晰。"},
    {"key": "gold", "name": "暖金", "description": "温暖、品质感强、适合品牌表达。"},
)

DENSITY_OPTIONS = (
    {
        "key": "compact",
        "name": "简洁",
        "description": "保留最核心信息，页面更短、更直接。",
    },
    {
        "key": "standard",
        "name": "标准",
        "description": "信息完整与浏览效率之间保持平衡。",
    },
    {
        "key": "rich",
        "name": "丰富",
        "description": "展示更多业务、解决方案与常见问题内容。",
    },
)

RECOMMENDED_THEMES = {
    "professional": ("ocean", "obsidian", "gold"),
    "technology": ("ocean", "amethyst", "obsidian"),
    "premium": ("obsidian", "gold", "cloud"),
    "industrial": ("obsidian", "ocean", "cloud"),
    "local_service": ("ocean", "jade", "gold"),
    "authority": ("ocean", "cloud", "obsidian"),
}

CONTENT_STYLE_KEY = {
    "professional": "professional",
    "technology": "technology",
    "premium": "premium",
    "industrial": "professional",
    "local_service": "professional",
    "authority": "professional",
}

STYLE_NAMES = {item["key"]: item["name"] for item in STYLE_OPTIONS}
THEME_NAMES = {item["key"]: item["name"] for item in THEME_OPTIONS}
DENSITY_NAMES = {item["key"]: item["name"] for item in DENSITY_OPTIONS}


class WebsiteDesignConflict(Exception):
    pass


def design_options_payload() -> dict[str, object]:
    return {
        "styles": list(STYLE_OPTIONS),
        "themes": list(THEME_OPTIONS),
        "densities": list(DENSITY_OPTIONS),
        "recommended_themes": {
            key: list(values) for key, values in RECOMMENDED_THEMES.items()
        },
    }


def content_style_key(style_key: str) -> str:
    return CONTENT_STYLE_KEY.get(style_key, "professional")


def _flatten_text(value: object) -> Iterable[str]:
    if isinstance(value, str):
        normalized = " ".join(value.split())
        if normalized:
            yield normalized
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten_text(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten_text(item)


def _subject_design_text(subject: Subject) -> str:
    values: list[str] = []
    version = subject.current_version
    if version is not None:
        values.append(version.official_name)
        values.extend(_flatten_text(version.field_values))
        values.extend(
            SubjectProduct.objects.filter(subject_version=version)
            .order_by("display_value")
            .values_list("display_value", flat=True)[:30]
        )
    try:
        profile = subject.business_profile
    except SubjectBusinessProfile.DoesNotExist:
        profile = None
    if profile is not None:
        values.extend(
            value
            for value in (profile.brand_name, profile.primary_business)
            if isinstance(value, str) and value.strip()
        )
    return " ".join(values).casefold()


def recommend_design(*, user, subject_id) -> dict[str, str]:
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    text = _subject_design_text(subject)

    rules = (
        (
            "industrial",
            (
                "制造",
                "机械",
                "设备",
                "工厂",
                "工业",
                "自动化",
                "机器人",
                "工程",
                "五金",
                "材料",
            ),
            "obsidian",
            "rich",
        ),
        (
            "local_service",
            (
                "家政",
                "装修",
                "门店",
                "维修",
                "培训",
                "教育",
                "医疗",
                "诊所",
                "餐饮",
                "美容",
                "摄影",
                "健身",
                "物业",
                "搬家",
                "婚庆",
            ),
            "jade",
            "standard",
        ),
        (
            "authority",
            (
                "咨询",
                "研究",
                "律师",
                "法律",
                "会计",
                "审计",
                "专利",
                "知识产权",
                "认证",
                "研究院",
            ),
            "cloud",
            "rich",
        ),
        (
            "premium",
            ("品牌", "设计", "珠宝", "美学", "高端", "奢华", "精品"),
            "gold",
            "standard",
        ),
        (
            "technology",
            (
                "人工智能",
                "ai",
                "软件",
                "数字化",
                "数据",
                "云计算",
                "saas",
                "信息技术",
                "智能系统",
            ),
            "ocean",
            "standard",
        ),
    )

    style_key = "professional"
    theme_key = "ocean"
    density_key = "standard"
    for candidate_style, terms, candidate_theme, candidate_density in rules:
        if any(term in text for term in terms):
            style_key = candidate_style
            theme_key = candidate_theme
            density_key = candidate_density
            break

    return {
        "style_key": style_key,
        "style_name": STYLE_NAMES[style_key],
        "theme_key": theme_key,
        "theme_name": THEME_NAMES[theme_key],
        "density_key": density_key,
        "density_name": DENSITY_NAMES[density_key],
        "reason": "根据当前主体的业务资料推荐，可随时更换。",
    }


def project_design_payload(project: WebsiteProject) -> dict[str, str]:
    return {
        "style_key": project.style_key,
        "style_name": STYLE_NAMES.get(project.style_key, "专业商务"),
        "theme_key": project.theme_key,
        "theme_name": THEME_NAMES.get(project.theme_key, "深海蓝"),
        "density_key": project.density_key,
        "density_name": DENSITY_NAMES.get(project.density_key, "标准"),
    }


def apply_project_design(
    *,
    project: WebsiteProject,
    style_key: str,
    theme_key: str,
    density_key: str,
    expected_version: int | None = None,
) -> WebsiteProject:
    if (
        style_key not in STYLE_NAMES
        or theme_key not in THEME_NAMES
        or density_key not in DENSITY_NAMES
    ):
        raise WebsiteDesignConflict("请选择有效的网站设计")

    with transaction.atomic():
        locked = WebsiteProject.objects.select_for_update().get(pk=project.pk)
        if expected_version is not None and locked.version != expected_version:
            raise WebsiteDesignConflict("官网已发生变化，请刷新后重新选择")
        if (
            locked.style_key == style_key
            and locked.theme_key == theme_key
            and locked.density_key == density_key
        ):
            return locked
        locked.style_key = style_key
        locked.theme_key = theme_key
        locked.density_key = density_key
        locked.version += 1
        locked.save(
            update_fields=("style_key", "theme_key", "density_key", "version", "updated_at")
        )
        return locked


def project_for_subject(*, user, subject_id) -> WebsiteProject:
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    try:
        return WebsiteProject.objects.select_related("subject", "subject_version").get(
            user=user,
            subject=subject,
        )
    except WebsiteProject.DoesNotExist as exc:
        raise WebsiteDesignConflict("请先生成官网草稿") from exc
