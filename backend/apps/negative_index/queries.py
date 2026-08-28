from __future__ import annotations

from apps.search_discovery.subject_context import (
    SubjectSearchContext,
    append_query,
    primary_anchor,
)

NEGATIVE_QUERY_THEMES = (
    "负面 争议",
    "投诉 退款 维权",
    "处罚 违法 监管",
    "诉讼 判决 执行",
    "失信 被执行人",
    "虚假宣传 欺诈 诈骗",
    "欠薪 欠款 裁员",
    "数据泄露 安全事故",
    "差评 曝光 质疑",
)


def build_negative_queries(
    context: SubjectSearchContext,
    max_queries: int = 12,
) -> list[str]:
    if not context.anchors:
        return []
    official = context.official_name or context.anchors[0]
    primary = primary_anchor(context.anchors, official)
    queries: list[str] = []
    for theme in NEGATIVE_QUERY_THEMES:
        append_query(queries, f"{official} {theme}")
        if len(queries) >= max_queries:
            return queries[:max_queries]
    if primary != official:
        for theme in ("投诉 退款", "处罚 诉讼", "诈骗 虚假宣传"):
            append_query(queries, f"{primary} {theme}")
            if len(queries) >= max_queries:
                break
    return queries[:max_queries]
