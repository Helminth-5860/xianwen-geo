import json
from dataclasses import dataclass
from typing import Any

from .models import Subject, SubjectBusinessProfile

DIRECT_MUNICIPALITY_CODES = {"110000", "120000", "310000", "500000"}
CREDIT_CODE_SUBJECT_TYPES = {"enterprise", "individual_business"}


def _text_present(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def business_address_is_complete(value: Any) -> bool:
    if not _text_present(value):
        return False
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return False
    path = payload.get("path")
    if not isinstance(path, list) or not path or not _text_present(payload.get("detail")):
        return False
    if any(
        not isinstance(node, dict)
        or not _text_present(node.get("code"))
        or not _text_present(node.get("name"))
        for node in path
    ):
        return False
    first_code = str(path[0]["code"])
    minimum_depth = 1 if first_code in DIRECT_MUNICIPALITY_CODES else 2
    return minimum_depth <= len(path) <= 3


def service_regions_are_complete(value: Any) -> bool:
    if not _text_present(value):
        return False
    if value.strip() in {"全国", "全国范围", "全国服务"}:
        return True
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return False
    nationwide = payload.get("nationwide")
    areas = payload.get("areas")
    if nationwide is True:
        return areas == []
    if nationwide is not False or not isinstance(areas, list) or not areas:
        return False
    for area in areas:
        if not isinstance(area, dict) or area.get("level") not in {"province", "city"}:
            return False
        path = area.get("path")
        if not isinstance(path, list) or not path:
            return False
        if any(
            not isinstance(node, dict)
            or not _text_present(node.get("code"))
            or not _text_present(node.get("name"))
            for node in path
        ):
            return False
        first_code = str(path[0]["code"])
        expected_level = "city" if first_code in DIRECT_MUNICIPALITY_CODES else None
        if len(path) == 1:
            if area.get("level") != (expected_level or "province"):
                return False
        elif len(path) == 2:
            if first_code in DIRECT_MUNICIPALITY_CODES or area.get("level") != "city":
                return False
        else:
            return False
    return True


@dataclass(frozen=True)
class SubjectProfileCompleteness:
    percentage: int
    core_completed: int
    core_total: int
    missing_core_keys: tuple[str, ...]
    missing_core_labels: tuple[str, ...]
    suggestion: str


def calculate_subject_profile_completeness(subject: Subject) -> SubjectProfileCompleteness:
    values = subject.draft_values if isinstance(subject.draft_values, dict) else {}
    try:
        profile = subject.business_profile
    except SubjectBusinessProfile.DoesNotExist:
        profile = None

    core_checks = (
        ("name", "主体名称", _text_present(values.get("name"))),
        ("subject_type", "主体类型", bool(subject.subject_type_id)),
        ("industry", "所属行业", profile is not None and _text_present(profile.industry)),
        (
            "primary_business",
            "主营业务",
            profile is not None and _text_present(profile.primary_business),
        ),
        ("target_audience", "服务对象 / 目标客户", _text_present(values.get("target_audience"))),
        (
            "business_address",
            "主体地址",
            profile is not None and business_address_is_complete(profile.business_address),
        ),
        (
            "service_regions",
            "业务覆盖区域",
            service_regions_are_complete(values.get("service_regions")),
        ),
    )
    missing_core = tuple((key, label) for key, label, complete in core_checks if not complete)
    core_completed = len(core_checks) - len(missing_core)

    optional_checks = [
        ("official_url", "官方网站", _text_present(values.get("official_url"))),
        (
            "subject_aliases",
            "主体别名",
            profile is not None and _text_present(profile.subject_aliases),
        ),
        (
            "core_products_services",
            "核心产品 / 服务",
            _text_present(values.get("core_products_services")),
        ),
        ("summary", "主体简介", _text_present(values.get("summary"))),
    ]
    if subject.subject_type.key in CREDIT_CODE_SUBJECT_TYPES:
        optional_checks.append(
            (
                "unified_social_credit_code",
                "统一社会信用代码",
                profile is not None and _text_present(profile.unified_social_credit_code),
            )
        )

    optional_completed = sum(1 for _key, _label, complete in optional_checks if complete)
    optional_score = round(30 * optional_completed / len(optional_checks))
    percentage = min(100, core_completed * 10 + optional_score)

    if missing_core:
        suggestion = f"请先补充{missing_core[0][1]}，完成核心资料后主体即可正常使用。"
    else:
        missing_optional = next(
            ((key, label) for key, label, complete in optional_checks if not complete), None
        )
        if missing_optional is None:
            suggestion = "主体资料已完善，可用于后续 GEO 分析。"
        elif missing_optional[0] == "official_url":
            suggestion = "建议补充官方网站，有助于提升主体识别与 GEO 分析质量。"
        else:
            suggestion = f"建议补充{missing_optional[1]}，让主体信息更完整。"

    return SubjectProfileCompleteness(
        percentage=percentage,
        core_completed=core_completed,
        core_total=len(core_checks),
        missing_core_keys=tuple(key for key, _label in missing_core),
        missing_core_labels=tuple(label for _key, label in missing_core),
        suggestion=suggestion,
    )
