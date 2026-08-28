from __future__ import annotations

from apps.source_index.scanner import SubjectSearchContext
from apps.source_index.provider import truncate_baidu_query


NEGATIVE_QUERY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("general", ("负面", "争议 曝光")),
    ("consumer", ("投诉 退款", "维权 差评")),
    ("regulatory", ("处罚 违法", "行政处罚 监管")),
    ("judicial", ("诉讼 判决", "执行 失信")),
    ("marketing", ("虚假宣传 欺诈", "骗局 诈骗")),
    ("operations", ("欠薪 欠款", "裁员 经营异常")),
    ("security", ("数据泄露 安全事故",)),
)


def build_negative_queries(context: SubjectSearchContext, *, max_queries: int = 12) -> list[dict[str, str]]:
    if not context.anchors:
        return []
    primary = context.official_name or context.anchors[0]
    aliases = [value for value in context.anchors if value and value != primary]
    queries: list[dict[str, str]] = []
    seen: set[str] = set()

    def append(group: str, query: str) -> None:
        query = truncate_baidu_query(query)
        key = query.casefold().strip()
        if not query or key in seen or len(queries) >= max_queries:
            return
        seen.add(key)
        queries.append({"group": group, "query": query})

    # Full legal name gets the highest-evidence searches first.
    for group, suffixes in NEGATIVE_QUERY_GROUPS:
        for suffix in suffixes:
            append(group, f"{primary} {suffix}")
            if len(queries) >= max_queries:
                return queries

    # If the official name is long, preserve at least one compact brand/alias query.
    for alias in aliases[:2]:
        append("brand", f"{alias} 投诉 负面")
        append("brand", f"{alias} 处罚 诉讼")
    return queries[:max_queries]
