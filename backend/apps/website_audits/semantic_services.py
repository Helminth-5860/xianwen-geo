from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai.errors import AIAdapterError

from .models import WebsiteAudit, WebsiteAuditFinding
from .semantic_context import build_semantic_audit_context
from .semantic_provider import SEMANTIC_PROMPT_VERSION, execute_semantic_provider
from .semantic_validation import SemanticAuditSchemaError


class WebsiteSemanticAuditBusy(Exception):
    pass


class WebsiteSemanticAuditNotReady(Exception):
    pass


def queue_semantic_audit(audit_id) -> bool:
    with transaction.atomic():
        audit = WebsiteAudit.objects.select_for_update().get(pk=audit_id)
        if audit.status != WebsiteAudit.Status.SUCCEEDED:
            return False
        if not settings.WEBSITE_AUDIT_SEMANTIC_ENABLED:
            audit.semantic_status = WebsiteAudit.SemanticStatus.DISABLED
            audit.semantic_finished_at = timezone.now()
            audit.save(
                update_fields=("semantic_status", "semantic_finished_at", "updated_at")
            )
            return False
        if audit.semantic_status in {
            WebsiteAudit.SemanticStatus.QUEUED,
            WebsiteAudit.SemanticStatus.RUNNING,
            WebsiteAudit.SemanticStatus.SUCCEEDED,
        }:
            return audit.semantic_status == WebsiteAudit.SemanticStatus.QUEUED
        audit.semantic_status = WebsiteAudit.SemanticStatus.QUEUED
        audit.semantic_provider_key = ""
        audit.semantic_model_id = ""
        audit.semantic_runtime_version = None
        audit.semantic_prompt_version = SEMANTIC_PROMPT_VERSION
        audit.semantic_page_count = 0
        audit.semantic_question_count = 0
        audit.semantic_scores = {}
        audit.semantic_result = {}
        audit.semantic_input_tokens = 0
        audit.semantic_output_tokens = 0
        audit.semantic_total_tokens = 0
        audit.semantic_latency_ms = None
        audit.semantic_error_code = ""
        audit.semantic_started_at = None
        audit.semantic_finished_at = None
        audit.save(
            update_fields=(
                "semantic_status",
                "semantic_provider_key",
                "semantic_model_id",
                "semantic_runtime_version",
                "semantic_prompt_version",
                "semantic_page_count",
                "semantic_question_count",
                "semantic_scores",
                "semantic_result",
                "semantic_input_tokens",
                "semantic_output_tokens",
                "semantic_total_tokens",
                "semantic_latency_ms",
                "semantic_error_code",
                "semantic_started_at",
                "semantic_finished_at",
                "updated_at",
            )
        )
        return True


def _start_semantic_audit(audit_id) -> WebsiteAudit:
    with transaction.atomic():
        # Lock only the audit row. Subject.current_version is nullable, so joining it
        # here would create a LEFT OUTER JOIN that PostgreSQL cannot lock with
        # SELECT ... FOR UPDATE. Related subject data is loaded after this state
        # transition by the non-locking query in execute_semantic_audit().
        audit = WebsiteAudit.objects.select_for_update().get(pk=audit_id)
        if audit.status != WebsiteAudit.Status.SUCCEEDED:
            raise WebsiteSemanticAuditNotReady
        if audit.semantic_status == WebsiteAudit.SemanticStatus.SUCCEEDED:
            return audit
        if audit.semantic_status not in {
            WebsiteAudit.SemanticStatus.QUEUED,
            WebsiteAudit.SemanticStatus.FAILED,
        }:
            raise WebsiteSemanticAuditBusy
        audit.semantic_status = WebsiteAudit.SemanticStatus.RUNNING
        audit.semantic_started_at = timezone.now()
        audit.semantic_finished_at = None
        audit.semantic_error_code = ""
        audit.save(
            update_fields=(
                "semantic_status",
                "semantic_started_at",
                "semantic_finished_at",
                "semantic_error_code",
                "updated_at",
            )
        )
        return audit


def fail_semantic_audit(audit_id, code: str = "SEMANTIC_AUDIT_FAILED") -> None:
    WebsiteAudit.objects.filter(pk=audit_id).update(
        semantic_status=WebsiteAudit.SemanticStatus.FAILED,
        semantic_error_code=code[:64],
        semantic_finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


def _semantic_schema_error_code(exc: SemanticAuditSchemaError) -> str:
    reason = "".join(
        character if character.isalnum() else "_"
        for character in str(exc).strip().upper()
    ).strip("_")
    return (f"SEMANTIC_SCHEMA_{reason}" if reason else "SEMANTIC_AUDIT_SCHEMA_INVALID")[:64]


def _semantic_findings(result: dict) -> list[WebsiteAuditFinding]:
    rows: list[WebsiteAuditFinding] = []
    # The audit FK is attached by the caller before bulk_create.
    for index, item in enumerate(result.get("content_findings", []), start=1):
        severity = item["severity"]
        rows.append(
            WebsiteAuditFinding(
                category=WebsiteAuditFinding.Category.GEO,
                dimension="GEO语义内容分析",
                check_key=f"geo.semantic.content.{item['key'][:70]}.{index}",
                rule_version=SEMANTIC_PROMPT_VERSION,
                method=WebsiteAuditFinding.Method.SEMANTIC,
                severity=severity,
                result=(
                    WebsiteAuditFinding.Result.FAIL
                    if severity == "high"
                    else WebsiteAuditFinding.Result.WARN
                ),
                title=item["title"],
                summary=item["reason"],
                impact="该问题由官网公开内容的语义证据分析得出，会影响机器理解、回答完整度或引用准备度。",
                recommendation=item["recommendation"],
                affected_count=len(item.get("evidence_urls", [])),
                evidence={"urls": item.get("evidence_urls", []), "semantic": True},
            )
        )
    for index, item in enumerate(result.get("topic_gaps", []), start=1):
        importance = item["importance"]
        rows.append(
            WebsiteAuditFinding(
                category=WebsiteAuditFinding.Category.GEO,
                dimension="主题覆盖完整度",
                check_key=f"geo.semantic.topic_gap.{index}",
                rule_version=SEMANTIC_PROMPT_VERSION,
                method=WebsiteAuditFinding.Method.SEMANTIC,
                severity={"high": "high", "medium": "medium", "low": "low"}[importance],
                result=WebsiteAuditFinding.Result.WARN,
                title=f"主题缺口：{item['topic']}"[:300],
                summary=item["reason"],
                impact="关键主题缺口会降低官网对用户问题与生成式搜索答案场景的覆盖能力。",
                recommendation=item["suggested_content"],
                affected_count=len(item.get("evidence_urls", [])),
                evidence={"urls": item.get("evidence_urls", []), "semantic": True},
            )
        )
    questions = result.get("question_assessments", [])
    weak = [row for row in questions if row.get("status") != "answered"]
    if questions:
        rows.append(
            WebsiteAuditFinding(
                category=WebsiteAuditFinding.Category.GEO,
                dimension="AI回答准备度",
                check_key="geo.semantic.question_coverage",
                rule_version=SEMANTIC_PROMPT_VERSION,
                method=WebsiteAuditFinding.Method.SEMANTIC,
                severity="high" if len(weak) * 2 >= len(questions) else ("medium" if weak else "info"),
                result=WebsiteAuditFinding.Result.WARN if weak else WebsiteAuditFinding.Result.PASS,
                title="官网问题回答覆盖存在缺口" if weak else "官网问题回答覆盖基础良好",
                summary=(
                    f"本次评估 {len(questions)} 个核心问题，其中 {len(weak)} 个仅部分覆盖或缺失。"
                    if weak
                    else f"本次评估的 {len(questions)} 个核心问题均有较明确的官网证据。"
                ),
                impact="用户真实问题无法由官网明确回答时，生成式搜索系统更难从官网抽取完整答案。",
                recommendation="优先补足高优先级缺失问题，并在对应页面提供清晰、直接、可核验的回答。",
                affected_count=len(weak),
                evidence={
                    "weak_questions": [
                        {
                            "question": row.get("question", ""),
                            "coverage_score": row.get("coverage_score"),
                            "status": row.get("status"),
                        }
                        for row in weak[:30]
                    ],
                    "semantic": True,
                },
            )
        )
    return rows


def execute_semantic_audit(audit_id) -> dict[str, object]:
    audit = _start_semantic_audit(audit_id)
    if audit.semantic_status == WebsiteAudit.SemanticStatus.SUCCEEDED:
        return {"audit_id": str(audit.id), "semantic_status": audit.semantic_status}

    audit = (
        WebsiteAudit.objects.select_related("subject__current_version")
        .prefetch_related(
            "pages",
            "subject__current_version__names",
            "subject__current_version__products",
        )
        .get(pk=audit_id)
    )
    context = build_semantic_audit_context(
        audit,
        maximum_pages=settings.WEBSITE_AUDIT_SEMANTIC_MAX_PAGES,
        max_chars_per_page=settings.WEBSITE_AUDIT_SEMANTIC_MAX_CHARS_PER_PAGE,
        max_total_chars=settings.WEBSITE_AUDIT_SEMANTIC_MAX_TOTAL_CHARS,
        maximum_keywords=settings.WEBSITE_AUDIT_SEMANTIC_MAX_KEYWORDS,
        maximum_questions=settings.WEBSITE_AUDIT_SEMANTIC_MAX_QUESTIONS,
    )
    if not context.pages:
        fail_semantic_audit(audit_id, "SEMANTIC_AUDIT_NO_PAGE_EVIDENCE")
        raise WebsiteSemanticAuditNotReady

    try:
        provider = execute_semantic_provider(audit_id=str(audit.id), context=context)
    except AIAdapterError as exc:
        fail_semantic_audit(audit_id, exc.stable_code or "SEMANTIC_PROVIDER_FAILED")
        raise
    except SemanticAuditSchemaError as exc:
        fail_semantic_audit(audit_id, _semantic_schema_error_code(exc))
        raise

    result = provider.validated.result
    finding_rows = _semantic_findings(result)
    with transaction.atomic():
        locked = WebsiteAudit.objects.select_for_update().get(pk=audit_id)
        locked.findings.filter(method=WebsiteAuditFinding.Method.SEMANTIC).delete()
        for row in finding_rows:
            row.audit = locked
        if finding_rows:
            WebsiteAuditFinding.objects.bulk_create(finding_rows, batch_size=100)
        locked.semantic_status = WebsiteAudit.SemanticStatus.SUCCEEDED
        locked.semantic_provider_key = provider.provider_key
        locked.semantic_model_id = provider.provider_model_id
        locked.semantic_runtime_version = provider.runtime_version
        locked.semantic_prompt_version = SEMANTIC_PROMPT_VERSION
        locked.semantic_page_count = len(context.pages)
        locked.semantic_question_count = len(result.get("question_assessments", []))
        locked.semantic_scores = provider.validated.scores
        locked.semantic_result = result
        locked.semantic_input_tokens = provider.input_tokens
        locked.semantic_output_tokens = provider.output_tokens
        locked.semantic_total_tokens = provider.total_tokens
        locked.semantic_latency_ms = provider.latency_ms
        locked.semantic_error_code = ""
        locked.semantic_finished_at = timezone.now()
        locked.save(
            update_fields=(
                "semantic_status",
                "semantic_provider_key",
                "semantic_model_id",
                "semantic_runtime_version",
                "semantic_prompt_version",
                "semantic_page_count",
                "semantic_question_count",
                "semantic_scores",
                "semantic_result",
                "semantic_input_tokens",
                "semantic_output_tokens",
                "semantic_total_tokens",
                "semantic_latency_ms",
                "semantic_error_code",
                "semantic_finished_at",
                "updated_at",
            )
        )
    return {
        "audit_id": str(audit.id),
        "semantic_status": WebsiteAudit.SemanticStatus.SUCCEEDED,
        "pages": len(context.pages),
        "questions": len(result.get("question_assessments", [])),
        "findings": len(finding_rows),
        "scores": provider.validated.scores,
    }
