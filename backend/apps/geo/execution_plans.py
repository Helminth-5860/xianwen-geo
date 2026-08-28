from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal
from urllib.parse import quote

from django.db import IntegrityError, transaction
from django.http import Http404

from apps.media_inquiries.catalog import paid_media_catalog
from apps.media_inquiries.exceptions import PaidMediaBusinessError
from apps.media_inquiries.models import PaidMediaInquiry
from apps.media_inquiries.services import cancel_inquiry, create_inquiry
from apps.subjects.subject_services import subject_for_user_or_404

from .models import StrategyExecutionPlan, StrategyReport

PAID_MEDIA_ITEM_KEY = "paid-media"
ITEM_PENDING = "pending"
ITEM_IN_PROGRESS = "in_progress"
ITEM_COMPLETED = "completed"
ITEM_CANCELLED = "cancelled"
ITEM_STATUSES = {ITEM_PENDING, ITEM_IN_PROGRESS, ITEM_COMPLETED, ITEM_CANCELLED}

CATEGORY_KEYWORDS = {
    "IT科技": (
        "软件开发",
        "信息技术",
        "人工智能产品",
        "科技公司",
        "网络科技",
        "云计算",
        "大数据",
        "saas",
        "芯片",
        "电子科技",
    ),
    "财经金融": ("财经", "金融", "银行", "证券", "基金", "保险", "投资", "资本"),
    "健康医疗": ("健康", "医疗", "医院", "医药", "药品", "生物"),
    "食品餐饮": ("食品", "餐饮", "饮品", "茶饮", "酒", "零食"),
    "留学教育": ("留学", "教育", "培训", "学校", "课程", "学习"),
    "家装家居": ("家装", "家居", "装修", "建材", "家具"),
    "汽车行业": ("汽车", "新能源车", "车企", "车辆", "汽配"),
    "酒店旅游": ("旅游", "文旅", "酒店", "民宿", "景区"),
    "体育运动": ("体育", "运动", "健身", "赛事"),
    "女性时尚": ("美容", "美妆", "护肤", "时尚", "女装", "珠宝"),
    "娱乐行业": ("娱乐", "影视", "音乐", "艺人", "综艺"),
    "生活消费": ("生活服务", "消费品", "家政", "零售", "日用品"),
    "文化艺术": ("文化", "艺术", "出版", "书画", "博物馆"),
    "游戏行业": ("游戏", "电竞", "手游", "网游"),
    "亲子母婴": ("亲子", "母婴", "育儿", "婴童", "孕产"),
    "房产行业": ("房产", "房地产", "楼盘", "物业", "置业"),
    "贸易能源": ("贸易", "能源", "电力", "石油", "光伏", "储能"),
    "公益": ("公益", "慈善", "社会组织", "志愿服务"),
    "区块链": ("区块链", "数字资产", "链上"),
    "新闻资讯": ("新闻媒体", "新闻资讯", "融媒体", "传媒机构"),
}

REGION_ALIASES = {
    "北京": ("北京",),
    "上海": ("上海",),
    "天津": ("天津",),
    "重庆": ("重庆",),
    "广东": ("广东", "广州", "深圳", "佛山", "东莞", "珠海", "中山", "惠州"),
    "江苏": ("江苏", "南京", "苏州", "无锡", "常州", "南通"),
    "浙江": ("浙江", "杭州", "宁波", "温州", "嘉兴", "绍兴"),
    "山东": ("山东", "济南", "青岛", "烟台", "潍坊", "临沂", "淄博"),
    "河南": ("河南", "郑州", "洛阳", "开封", "南阳"),
    "河北": ("河北", "石家庄", "唐山", "保定", "廊坊", "邯郸"),
    "湖北": ("湖北", "武汉", "宜昌", "襄阳", "咸宁"),
    "湖南": ("湖南", "长沙", "株洲", "湘潭"),
    "福建": ("福建", "福州", "厦门", "泉州"),
    "四川": ("四川", "成都", "绵阳"),
    "陕西": ("陕西", "西安"),
    "安徽": ("安徽", "合肥", "芜湖"),
    "江西": ("江西", "南昌", "赣州"),
    "辽宁": ("辽宁", "沈阳", "大连"),
    "吉林": ("吉林", "长春"),
    "黑龙江": ("黑龙江", "哈尔滨"),
    "山西": ("山西", "太原"),
    "广西": ("广西", "南宁", "桂林"),
    "海南": ("海南", "海口", "三亚"),
    "贵州": ("贵州", "贵阳"),
    "云南": ("云南", "昆明"),
    "甘肃": ("甘肃", "兰州"),
    "青海": ("青海", "西宁"),
    "宁夏": ("宁夏", "银川"),
    "新疆": ("新疆", "乌鲁木齐"),
    "内蒙古": ("内蒙古", "呼和浩特"),
    "西藏": ("西藏", "拉萨"),
    "香港": ("香港",),
    "澳门": ("澳门",),
    "台湾": ("台湾",),
}


class ExecutionPlanError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


class ExecutionPlanInputInvalid(ExecutionPlanError):
    def __init__(self, message: str = "执行方案选择不正确，请检查后重新提交。") -> None:
        super().__init__("EXECUTION_PLAN_INPUT_INVALID", message, status=422)


class ExecutionPlanStateConflict(ExecutionPlanError):
    def __init__(self, message: str = "当前执行方案状态不允许此操作。") -> None:
        super().__init__("EXECUTION_PLAN_STATE_CONFLICT", message, status=409)


class ExecutionPlanVersionConflict(ExecutionPlanError):
    def __init__(self) -> None:
        super().__init__(
            "EXECUTION_PLAN_VERSION_CONFLICT",
            "执行方案已发生变化，请刷新后重试。",
            status=409,
        )


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        if not value or value in seen:
            raise ExecutionPlanInputInvalid("执行方案中存在空白或重复选择，请重新选择。")
        result.append(value)
        seen.add(value)
    return result


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _validated_idempotency_key(raw_key: str | None) -> str:
    key = (raw_key or "").strip()
    if not key or len(key) > 200 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise ExecutionPlanInputInvalid("页面状态已失效，请刷新后重新提交。")
    return key


def _strategy_for_user(user, strategy_id, *, lock: bool = False) -> StrategyReport:
    query = StrategyReport.objects.select_related("report", "subject").filter(
        pk=strategy_id,
        user=user,
        subject__user=user,
        subject__user__tenant_id=user.tenant_id,
    )
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get()
    except StrategyReport.DoesNotExist as exc:
        raise Http404 from exc


def _phase_label(strategy: StrategyReport, index: int) -> str:
    schedule = strategy.ai_body.get("schedule", [])
    if isinstance(schedule, list) and schedule:
        phase = schedule[min(index, len(schedule) - 1)]
        if isinstance(phase, dict) and isinstance(phase.get("phase"), str):
            value = phase["phase"].strip()
            if value:
                return value
    return f"建议在 {strategy.period_days} 天内完成"


def _estimated_days(strategy: StrategyReport, index: int) -> int:
    return max(1, min(strategy.period_days, 3 + index * 2))


def _priority(index: int) -> str:
    return ("urgent", "high", "medium")[min(index, 2)] if index < 3 else "low"


def _preview_items(strategy: StrategyReport) -> list[dict[str, object]]:
    body = strategy.ai_body
    priorities = body.get("priorities", [])
    topics = body.get("article_topics", [])
    items: list[dict[str, object]] = []
    if isinstance(priorities, list):
        for index, priority in enumerate(priorities):
            if not isinstance(priority, dict):
                continue
            actions = priority.get("actions")
            if not isinstance(actions, list):
                actions = []
            deliverables = [
                value.strip() for value in actions if isinstance(value, str) and value.strip()
            ]
            if not deliverables:
                continue
            title = priority.get("title")
            rationale = priority.get("rationale")
            success_metric = priority.get("success_metric")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (title, rationale, success_metric)
            ):
                continue
            items.append(
                {
                    "key": f"priority-{index + 1:02d}",
                    "kind": "platform_assisted",
                    "title": title.strip(),
                    "problem": rationale.strip(),
                    "reason": rationale.strip(),
                    "recommendation": "；".join(deliverables),
                    "deliverables": deliverables,
                    "success_metric": success_metric.strip(),
                    "expected_improvement": success_metric.strip(),
                    "priority": _priority(index),
                    "estimated_days": _estimated_days(strategy, index),
                    "estimated_price_cents": 0,
                    "cost_note": "按实际使用功能与套餐规则为准。",
                    "selected_by_default": index < 3,
                    "period": _phase_label(strategy, index),
                    "route": f"/geo/strategy/{strategy.report_id}",
                }
            )
    if isinstance(topics, list):
        for index, topic in enumerate(topics):
            if not isinstance(topic, dict):
                continue
            title = topic.get("title")
            reason = topic.get("reason")
            if not all(isinstance(value, str) and value.strip() for value in (title, reason)):
                continue
            normalized_title = title.strip()
            items.append(
                {
                    "key": f"article-{index + 1:02d}",
                    "kind": "platform_assisted",
                    "title": f"生成文章：{normalized_title}",
                    "problem": "当前主体仍需补充可公开核验的内容信号。",
                    "reason": reason.strip(),
                    "recommendation": f"围绕“{normalized_title}”生成并审核文章。",
                    "deliverables": ["完成文章大纲、正文和发布前校对"],
                    "success_metric": "文章保存到内容库并可用于后续发布",
                    "expected_improvement": (
                        "增加与当前主体相关的可用内容，不承诺固定排名或曝光结果。"
                    ),
                    "priority": "medium",
                    "estimated_days": _estimated_days(strategy, len(items)),
                    "estimated_price_cents": 0,
                    "cost_note": "生成文章时按套餐额度规则结算。",
                    "selected_by_default": index == 0,
                    "article_topic": normalized_title,
                    "period": _phase_label(strategy, len(items)),
                    "route": (
                        f"/subjects/{strategy.subject_id}/articles/new"
                        f"?topic={quote(normalized_title)}"
                    ),
                }
            )
    items.append(
        {
            "key": "retest",
            "kind": "platform_assisted",
            "title": "完成后重新检测",
            "problem": "优化完成后需要通过可比检测确认实际变化。",
            "reason": "用相同主体重新检测，查看优化前后的实际变化。",
            "recommendation": "在本轮执行项目完成后发起一次可比复测。",
            "deliverables": ["形成一份可与本次结果对比的新检测报告"],
            "success_metric": "获得可核验的优化前后对比结果",
            "expected_improvement": "确认本轮执行后的实际变化，不预设检测结果。",
            "priority": "high",
            "estimated_days": strategy.period_days,
            "estimated_price_cents": 0,
            "cost_note": "复测时按套餐额度规则结算。",
            "selected_by_default": True,
            "period": f"{strategy.period_days} 天计划完成后",
            "route": f"/geo/retest?report_id={strategy.report_id}",
        }
    )
    return items


def _package_item_keys(items: list[dict[str, object]]) -> dict[str, list[str]]:
    improvements = [str(item["key"]) for item in items if str(item["key"]).startswith("priority-")]
    articles = [str(item["key"]) for item in items if str(item["key"]).startswith("article-")]
    retest = [str(item["key"]) for item in items if item["key"] == "retest"]

    def combined(*groups: list[str]) -> list[str]:
        return list(dict.fromkeys(key for group in groups for key in group))

    return {
        "basic": combined(improvements[:2], articles[:1], retest),
        "focused": combined(improvements[:4], articles[:2], retest),
        "comprehensive": combined(improvements, articles, retest),
        "custom": [],
    }


def _package_payload(
    items: list[dict[str, object]],
    recommended_media: list[dict[str, object]],
) -> list[dict[str, object]]:
    keys = _package_item_keys(items)
    by_key = {str(item["key"]): item for item in items}
    media_by_id = {str(item["id"]): item for item in recommended_media}
    matched_media = [item for item in recommended_media if item["selected_by_default"]]
    focused_media = [str(item["id"]) for item in matched_media[:2]]
    comprehensive_media = [str(item["id"]) for item in matched_media]

    def package(
        *,
        code: str,
        name: str,
        description: str,
        item_keys: list[str],
        media_ids: list[str],
        recommended: bool,
    ) -> dict[str, object]:
        estimated_days = max(
            (int(by_key[key]["estimated_days"]) for key in item_keys),
            default=0,
        )
        estimated_price_cents = sum(
            int(by_key[key]["estimated_price_cents"]) for key in item_keys
        ) + sum(int(media_by_id[media_id]["price_cents"]) for media_id in media_ids)
        return {
            "code": code,
            "name": name,
            "description": description,
            "item_keys": item_keys,
            "media_ids": media_ids,
            "estimated_days": estimated_days,
            "estimated_price_cents": estimated_price_cents,
            "recommended": recommended,
        }

    return [
        package(
            code="basic",
            name="基础改善",
            description="先处理最明显的短板，并准备一项核心内容。",
            item_keys=keys["basic"],
            media_ids=[],
            recommended=False,
        ),
        package(
            code="focused",
            name="重点提升",
            description="集中处理主要短板，并补充重点内容与复测。媒体仅为备选，提交前仍需确认。",
            item_keys=keys["focused"],
            media_ids=focused_media,
            recommended=True,
        ),
        package(
            code="comprehensive",
            name="全面建设",
            description="执行当前方案中的全部建议，并在完成后重新检测。媒体仅为备选，提交前仍需确认。",
            item_keys=keys["comprehensive"],
            media_ids=comprehensive_media,
            recommended=False,
        ),
        package(
            code="custom",
            name="自定义方案",
            description="按照实际需求自由选择要执行的项目。",
            item_keys=[],
            media_ids=[],
            recommended=False,
        ),
    ]


def _strategy_matching_facts(strategy: StrategyReport) -> tuple[set[str], set[str]]:
    frozen_facts = {"subject": strategy.report_facts.get("subject", {})}
    text = json.dumps(frozen_facts, ensure_ascii=False, sort_keys=True).casefold()
    categories = {
        category
        for category, keywords in CATEGORY_KEYWORDS.items()
        if any(keyword.casefold() in text for keyword in keywords)
    }
    regions = {
        region
        for region, aliases in REGION_ALIASES.items()
        if any(alias.casefold() in text for alias in aliases)
    }
    return categories, regions


def _paid_media_recommendations(strategy: StrategyReport) -> list[dict[str, object]]:
    try:
        candidates = [
            item
            for item in paid_media_catalog().items
            if item.url is not None and item.price_cents > 0
        ]
    except PaidMediaBusinessError:
        return []
    if not candidates:
        return []
    categories, regions = _strategy_matching_facts(strategy)
    prices = sorted(item.price_cents for item in candidates)
    median = prices[len(prices) // 2]

    def match(item) -> tuple[bool, bool]:
        return item.category in categories, item.region in regions

    regional_candidates = [
        item
        for item in candidates
        if not regions or item.region in regions or item.region in {None, "全国"}
    ]
    matched = [item for item in regional_candidates if any(match(item))]
    pool = matched or [item for item in candidates if item.region in {None, "全国"}]
    if not pool:
        pool = candidates

    def rank(item) -> tuple[int, int, int, str]:
        category_match, region_match = match(item)
        nationwide = item.region == "全国"
        relevance = (40 if category_match else 0) + (30 if region_match else 0)
        relevance += 10 if nationwide else 0
        return (-relevance, abs(item.price_cents - median), item.price_cents, item.id)

    selected = []
    seen_domains: set[str] = set()
    for item in sorted(pool, key=rank):
        domain_key = item.domain or item.id
        if domain_key in seen_domains:
            continue
        selected.append(item)
        seen_domains.add(domain_key)
        if len(selected) == 6:
            break

    shortfall_text = json.dumps(
        strategy.ai_body.get("priorities", []),
        ensure_ascii=False,
        sort_keys=True,
    )
    if "引用" in shortfall_text or "信源" in shortfall_text:
        shortfall_reason = "本次报告显示可信引用或公开信源仍需补充"
    elif "曝光" in shortfall_text or "可见" in shortfall_text or "提及" in shortfall_text:
        shortfall_reason = "本次报告显示品牌可见度仍有提升空间"
    elif "推荐" in shortfall_text:
        shortfall_reason = "本次报告显示推荐表现仍有提升空间"
    else:
        shortfall_reason = "本次优化方案建议补充可公开核验的外部信号"

    payload = []
    for item in selected:
        category_match, region_match = match(item)
        reasons = []
        if category_match and item.category:
            reasons.append(f"与主体的“{item.category}”方向相关")
        if region_match and item.region:
            reasons.append(f"覆盖主体服务区域“{item.region}”")
        if not reasons:
            reasons.append("未找到精确分类匹配，作为全国通用备选")
        payload.append(
            {
                **item.public_payload(),
                "reason": (
                    shortfall_reason
                    + "；"
                    + "，".join(reasons)
                    + "，且价格处于目录适中区间；发布内容、效果和最终安排需由用户确认。"
                ),
                "selected_by_default": category_match or region_match,
            }
        )
    return payload


def _plan_item_payload(item: dict[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {
        "key": item["key"],
        "title": item["title"],
        "kind": item["kind"],
        "status": item["status"],
        "recommendation": item["recommendation"],
        "deliverables": copy.deepcopy(item["deliverables"]),
        "success_metric": item["success_metric"],
        "estimated_days": item["estimated_days"],
        "estimated_price_cents": item["estimated_price_cents"],
        "cost_note": item["cost_note"],
    }
    if item.get("article_topic"):
        payload["article_topic"] = item["article_topic"]
    if item.get("route"):
        payload["route"] = item["route"]
    if item.get("period"):
        payload["period"] = item["period"]
    return payload


def _selected_media_payload(inquiry: PaidMediaInquiry | None) -> list[dict[str, object]]:
    if inquiry is None:
        return []
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "url": item.get("url"),
            "domain": item.get("domain"),
            "logo_path": item.get("logo_path"),
            "price_cents": item["price_cents"],
            "inquiry_status": inquiry.status,
        }
        for item in inquiry.selected_media
    ]


def execution_plan_payload(plan: StrategyExecutionPlan) -> dict[str, object]:
    inquiry = getattr(plan, "paid_media_inquiry", None)
    items = [_plan_item_payload(item) for item in copy.deepcopy(plan.items)]
    estimated_days = max((int(item["estimated_days"]) for item in items), default=0)
    estimated_price_cents = int(plan.media_total * 100) + sum(
        int(item["estimated_price_cents"]) for item in items
    )
    return {
        "id": str(plan.pk),
        "strategy_id": str(plan.strategy_id),
        "report_id": str(plan.report_id),
        "subject_id": str(plan.subject_id),
        "package_code": plan.package_code,
        "package_name": plan.get_package_code_display(),
        "status": plan.status,
        "version": plan.version,
        "estimated_days": estimated_days,
        "estimated_price_cents": estimated_price_cents,
        "items": items,
        "selected_media": _selected_media_payload(inquiry),
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
    }


def execution_preview(*, user, strategy_id) -> dict[str, object]:
    strategy = _strategy_for_user(user, strategy_id)
    if strategy.status != StrategyReport.Status.SUCCEEDED or not strategy.ai_body:
        raise ExecutionPlanStateConflict("优化方案尚未生成完成，暂时不能建立执行方案。")
    items = _preview_items(strategy)
    recommended_media = _paid_media_recommendations(strategy)
    plan = (
        StrategyExecutionPlan.objects.select_related("paid_media_inquiry")
        .filter(strategy=strategy, user=user)
        .first()
    )
    return {
        "preview": {
            "items": items,
            "packages": _package_payload(items, recommended_media),
            "recommended_media": recommended_media,
            "overview": strategy.ai_body.get("overview", ""),
            "report_summary": copy.deepcopy(strategy.report_facts.get("scores", {})),
            "period_days": strategy.period_days,
        },
        "plan": execution_plan_payload(plan) if plan is not None else None,
    }


def _selected_items(
    *,
    strategy: StrategyReport,
    item_keys: list[str],
) -> list[dict[str, object]]:
    preview_items = _preview_items(strategy)
    by_key = {str(item["key"]): item for item in preview_items}
    selected_keys = _unique(item_keys)
    unknown = [key for key in selected_keys if key not in by_key]
    if unknown:
        raise ExecutionPlanInputInvalid("所选执行项目已发生变化，请刷新后重新选择。")
    return [{**copy.deepcopy(by_key[key]), "status": ITEM_PENDING} for key in selected_keys]


def _normalized_package_code(
    *,
    strategy: StrategyReport,
    requested_code: str,
    item_keys: list[str],
    media_ids: list[str],
) -> str:
    if requested_code == StrategyExecutionPlan.PackageCode.CUSTOM:
        return requested_code
    package = next(
        row
        for row in _package_payload(
            _preview_items(strategy),
            _paid_media_recommendations(strategy),
        )
        if row["code"] == requested_code
    )
    if set(item_keys) == set(package["item_keys"]) and set(media_ids) == set(package["media_ids"]):
        return requested_code
    return StrategyExecutionPlan.PackageCode.CUSTOM


@transaction.atomic
def create_execution_plan(
    *,
    user,
    strategy_id,
    package_code: str,
    item_keys: list[str],
    media_ids: list[str],
    idempotency_key: str | None,
    request_id,
) -> tuple[StrategyExecutionPlan, bool]:
    key = _validated_idempotency_key(idempotency_key)
    strategy = _strategy_for_user(user, strategy_id, lock=True)
    if strategy.status != StrategyReport.Status.SUCCEEDED or not strategy.ai_body:
        raise ExecutionPlanStateConflict("优化方案尚未生成完成，暂时不能建立执行方案。")
    if package_code not in StrategyExecutionPlan.PackageCode.values:
        raise ExecutionPlanInputInvalid("请选择可用的执行方案。")
    normalized_media_ids = _unique(media_ids) if media_ids else []
    selected_items = _selected_items(
        strategy=strategy,
        item_keys=item_keys,
    )
    if not selected_items and not normalized_media_ids:
        raise ExecutionPlanInputInvalid("请至少选择一个要执行的项目。")
    normalized_package_code = _normalized_package_code(
        strategy=strategy,
        requested_code=package_code,
        item_keys=[str(item["key"]) for item in selected_items],
        media_ids=normalized_media_ids,
    )
    request_digest = _digest(
        {
            "strategy_id": str(strategy.pk),
            "package_code": normalized_package_code,
            "item_keys": [str(item["key"]) for item in selected_items],
            "media_ids": sorted(normalized_media_ids),
        }
    )
    existing = (
        StrategyExecutionPlan.objects.select_related("paid_media_inquiry")
        .filter(strategy=strategy)
        .first()
    )
    if existing is not None:
        if existing.user_id != user.pk or existing.request_digest != request_digest:
            raise ExecutionPlanStateConflict("该优化方案已经建立执行方案，请刷新后查看。")
        return existing, False

    inquiry = None
    if normalized_media_ids:
        media_key = f"execution-plan-{strategy.pk}-{hashlib.sha256(key.encode()).hexdigest()}"
        inquiry = create_inquiry(
            user=user,
            subject_id=strategy.subject_id,
            media_ids=normalized_media_ids,
            idempotency_key=media_key,
            request_id=request_id,
        ).inquiry
        selected_items.append(
            {
                "key": PAID_MEDIA_ITEM_KEY,
                "kind": "paid_media",
                "title": "确认付费媒体发布安排",
                "problem": "当前方案需要补充外部媒体信号，具体媒体仍需人工确认匹配度。",
                "reason": "根据已确认的媒体选择提交给管理员，由管理员联系确认具体发布安排。",
                "recommendation": "由管理员联系确认媒体、内容、价格和发布时间后再安排发布。",
                "deliverables": [f"确认并安排 {inquiry.item_count} 家媒体的发布需求"],
                "success_metric": "管理员确认发布安排并反馈处理结果",
                "expected_improvement": "补充可核验的外部公开信号，不承诺固定曝光或排名结果。",
                "priority": "high",
                "estimated_days": min(strategy.period_days, 15),
                "estimated_price_cents": 0,
                "cost_note": "以管理员确认的最终报价为准。",
                "selected_by_default": True,
                "period": "以管理员确认的安排为准",
                "route": f"/subjects/{strategy.subject_id}/paid-media",
                "status": ITEM_PENDING,
                "inquiry_id": str(inquiry.pk),
            }
        )
    try:
        with transaction.atomic():
            plan = StrategyExecutionPlan.objects.create(
                strategy=strategy,
                user=user,
                subject=strategy.subject,
                report=strategy.report,
                package_code=normalized_package_code,
                items=selected_items,
                paid_media_inquiry=inquiry,
                media_total=inquiry.total_price if inquiry is not None else Decimal("0.00"),
                request_digest=request_digest,
            )
    except IntegrityError as exc:
        replay = (
            StrategyExecutionPlan.objects.select_related("paid_media_inquiry")
            .filter(strategy=strategy)
            .first()
        )
        if replay is not None and replay.request_digest == request_digest:
            return replay, False
        raise ExecutionPlanStateConflict("该优化方案已经建立执行方案，请刷新后查看。") from exc
    return plan, True


def execution_plan_for_user(*, user, plan_id, lock: bool = False) -> StrategyExecutionPlan:
    query = StrategyExecutionPlan.objects.select_related(
        "strategy", "report", "subject", "paid_media_inquiry"
    ).filter(
        pk=plan_id,
        user=user,
        subject__user=user,
        subject__user__tenant_id=user.tenant_id,
    )
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get()
    except StrategyExecutionPlan.DoesNotExist as exc:
        raise Http404 from exc


def execution_plans_for_subject(*, user, subject_id):
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    return StrategyExecutionPlan.objects.select_related(
        "strategy", "report", "subject", "paid_media_inquiry"
    ).filter(user=user, subject=subject, subject__user=user)


def _calculated_status(items: list[dict[str, object]]) -> str:
    states = [str(item.get("status", "")) for item in items]
    if not states or any(state not in ITEM_STATUSES for state in states):
        raise ExecutionPlanStateConflict("执行方案内容已发生变化，请刷新后重试。")
    if any(state in {ITEM_PENDING, ITEM_IN_PROGRESS} for state in states):
        return StrategyExecutionPlan.Status.ACTIVE
    if all(state == ITEM_COMPLETED for state in states):
        return StrategyExecutionPlan.Status.COMPLETED
    return StrategyExecutionPlan.Status.CANCELLED


def _find_item(items: list[dict[str, object]], item_key: str | None) -> dict[str, object]:
    normalized = (item_key or "").strip()
    for item in items:
        if item.get("key") == normalized:
            return item
    raise ExecutionPlanInputInvalid("没有找到所选执行项目，请刷新后重试。")


def _cancel_media(*, user, plan: StrategyExecutionPlan) -> None:
    inquiry = plan.paid_media_inquiry
    if inquiry is None:
        return
    if inquiry.status == PaidMediaInquiry.Status.CANCELLED:
        return
    if inquiry.status != PaidMediaInquiry.Status.PENDING:
        raise ExecutionPlanStateConflict("媒体申请已进入处理阶段，请先联系管理员确认是否可以取消。")
    cancel_inquiry(user=user, inquiry_id=inquiry.pk, subject_id=plan.subject_id)
    inquiry.refresh_from_db()


@transaction.atomic
def update_execution_plan(
    *,
    user,
    plan_id,
    action: str,
    item_key: str | None = None,
    expected_version: int,
) -> StrategyExecutionPlan:
    plan = execution_plan_for_user(user=user, plan_id=plan_id, lock=True)
    if plan.version != expected_version:
        raise ExecutionPlanVersionConflict
    items = copy.deepcopy(plan.items)
    if not isinstance(items, list):
        raise ExecutionPlanStateConflict("执行方案内容已发生变化，请刷新后重试。")

    if action == "cancel_plan":
        if plan.status == StrategyExecutionPlan.Status.COMPLETED:
            raise ExecutionPlanStateConflict("已完成的执行方案不能取消。")
        media_item = next(
            (item for item in items if item.get("key") == PAID_MEDIA_ITEM_KEY),
            None,
        )
        if (
            plan.paid_media_inquiry_id is not None
            and media_item is not None
            and media_item.get("status") in {ITEM_PENDING, ITEM_IN_PROGRESS}
        ):
            if plan.paid_media_inquiry.status == PaidMediaInquiry.Status.PENDING:
                _cancel_media(user=user, plan=plan)
            elif plan.paid_media_inquiry.status != PaidMediaInquiry.Status.CANCELLED:
                raise ExecutionPlanStateConflict(
                    "媒体申请已进入处理阶段，请先联系管理员确认是否可以取消。"
                )
        for item in items:
            if item.get("status") in {ITEM_PENDING, ITEM_IN_PROGRESS}:
                item["status"] = ITEM_CANCELLED
    else:
        item = _find_item(items, item_key)
        current = item.get("status")
        is_media = item.get("key") == PAID_MEDIA_ITEM_KEY
        if action == "start_item":
            if current != ITEM_PENDING:
                raise ExecutionPlanStateConflict("只有待执行的项目可以开始。")
            item["status"] = ITEM_IN_PROGRESS
        elif action == "complete_item":
            if current not in {ITEM_PENDING, ITEM_IN_PROGRESS}:
                raise ExecutionPlanStateConflict("当前项目不能标记为完成。")
            if (
                is_media
                and plan.paid_media_inquiry is not None
                and plan.paid_media_inquiry.status != PaidMediaInquiry.Status.COMPLETED
            ):
                raise ExecutionPlanStateConflict("管理员尚未确认媒体发布完成，请稍后查看。")
            item["status"] = ITEM_COMPLETED
        elif action == "cancel_item":
            if current not in {ITEM_PENDING, ITEM_IN_PROGRESS}:
                raise ExecutionPlanStateConflict("当前项目不能取消。")
            if is_media:
                _cancel_media(user=user, plan=plan)
            item["status"] = ITEM_CANCELLED
        elif action == "restore_item":
            if current != ITEM_CANCELLED:
                raise ExecutionPlanStateConflict("只有已取消的项目可以恢复。")
            if is_media and plan.paid_media_inquiry_id is not None:
                raise ExecutionPlanStateConflict("已取消的媒体申请不能直接恢复，请重新选择媒体。")
            item["status"] = ITEM_PENDING
        else:
            raise ExecutionPlanInputInvalid("请选择可用的执行操作。")

    plan.items = items
    plan.status = _calculated_status(items)
    plan.version += 1
    plan.save(update_fields=("items", "status", "version", "updated_at"))
    return plan
