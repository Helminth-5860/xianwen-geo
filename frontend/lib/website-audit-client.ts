import { get, post } from "./auth-client";

export type WebsiteAuditStageStatus =
  | "not_started"
  | "disabled"
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "partial";

export type WebsiteAuditReportStatus = "pending" | "failed" | "partial" | "complete";

export type WebsiteAuditSummary = Readonly<{
  id: string;
  subject_id: string;
  root_url: string;
  root_host: string;
  status: "queued" | "running" | "succeeded" | "failed";
  max_pages: number;
  discovered_count: number;
  selected_count: number;
  fetched_count: number;
  failed_count: number;
  internal_link_count: number;
  external_link_count: number;
  robots_url: string;
  robots_status: number | null;
  sitemap_urls: string[];
  stable_error_code: string;
  started_at: string | null;
  finished_at: string | null;
  browser_status: WebsiteAuditStageStatus;
  browser_profiles: string[];
  browser_selected_count: number;
  browser_completed_count: number;
  browser_failed_count: number;
  browser_error_code: string;
  browser_started_at: string | null;
  browser_finished_at: string | null;
  semantic_status: WebsiteAuditStageStatus;
  semantic_provider_key: string;
  semantic_model_id: string;
  semantic_prompt_version: string;
  semantic_page_count: number;
  semantic_question_count: number;
  semantic_scores: Record<string, number>;
  semantic_error_code: string;
  semantic_started_at: string | null;
  semantic_finished_at: string | null;
  created_at: string;
}>;

export type WebsiteAuditIssue = Readonly<{
  check_key: string;
  category: "seo" | "geo" | "technical" | string;
  dimension: string;
  method: string;
  severity: "critical" | "high" | "medium" | "low" | "info" | string;
  result: "fail" | "warn" | string;
  title: string;
  summary: string;
  recommendation: string;
  affected_count: number;
}>;

export type WebsiteAuditReport = Readonly<{
  score_version: string;
  status: WebsiteAuditReportStatus;
  missing_layers: string[];
  overall_score: number | null;
  scores: Readonly<{
    seo: number | null;
    geo: number | null;
    technical_health: number | null;
    ai_readability: number | null;
    content_readiness: number | null;
  }>;
  semantic_dimensions: Record<string, number>;
  components: Record<string, unknown>;
  issue_counts: Record<string, Record<string, number>>;
  top_issues: WebsiteAuditIssue[];
  browser_metrics: Record<
    string,
    Readonly<{
      sample_count: number;
      ttfb_p75_ms: number | null;
      lcp_p75_ms: number | null;
      cls_p75: number | null;
      tbt_p75_ms: number | null;
      failed_requests: number;
      transfer_bytes: number;
    }>
  >;
  semantic_summary: Readonly<{
    question_coverage: Readonly<{
      total: number;
      answered: number;
      partial: number;
      missing: number;
    }>;
    content_finding_count: number;
    topic_gap_count: number;
    citeable_passage_count: number;
    summary: string;
  }>;
  evidence: Readonly<{
    fetched_pages: number;
    failed_pages: number;
    browser_completed: number;
    browser_failed: number;
    semantic_pages: number;
    semantic_questions: number;
  }>;
}>;

export type WebsiteAuditFinding = Readonly<{
  id: string;
  category: string;
  dimension: string;
  check_key: string;
  rule_version: string;
  method: string;
  severity: string;
  result: string;
  title: string;
  summary: string;
  impact: string;
  recommendation: string;
  affected_count: number;
  evidence: Record<string, unknown>;
  created_at: string;
}>;

export type WebsiteAuditPageEvidence = Readonly<{
  id: string;
  url: string;
  final_url: string;
  source: string;
  depth: number;
  http_status: number | null;
  response_ms: number | null;
  title: string;
  meta_description: string;
  canonical_url: string;
  html_lang: string;
  headings: Record<string, unknown>;
  schema_types: string[];
  image_count: number;
  image_alt_missing_count: number;
  internal_links_count: number;
  external_links_count: number;
  text_characters: number;
  fetch_error: string;
}>;

export type WebsiteAuditDetail = WebsiteAuditSummary &
  Readonly<{
    semantic_runtime_version: number | null;
    semantic_result: Readonly<{
      summary?: string;
      scores?: Record<string, number>;
      topic_gaps?: Array<{
        topic: string;
        importance: string;
        reason: string;
        suggested_content: string;
        evidence_urls?: string[];
      }>;
      question_assessments?: Array<{
        question: string;
        coverage_score: number;
        status: "answered" | "partial" | "missing";
        answer_summary: string;
        missing_points: string[];
        recommendation: string;
        evidence_urls?: string[];
      }>;
      citeable_passages?: Array<{
        page_id?: string;
        url: string;
        reason: string;
        excerpt: string;
      }>;
    }>;
    semantic_input_tokens: number;
    semantic_output_tokens: number;
    semantic_total_tokens: number;
    semantic_latency_ms: number | null;
    pages: WebsiteAuditPageEvidence[];
    browser_snapshots: unknown[];
    findings: WebsiteAuditFinding[];
    report: WebsiteAuditReport;
  }>;

export function createWebsiteAudit(subjectId: string, url: string) {
  return post<WebsiteAuditSummary>(`/subjects/${subjectId}/website-audits`, { url });
}

export function getWebsiteAuditHistory(subjectId: string) {
  return get<WebsiteAuditSummary[]>(`/subjects/${subjectId}/website-audits/history`);
}

export function getWebsiteAudit(auditId: string) {
  return get<WebsiteAuditDetail>(`/website-audits/${auditId}`);
}

export function websiteAuditStatusLabel(status: string) {
  const labels: Readonly<Record<string, string>> = {
    not_started: "等待检测",
    queued: "等待检测",
    running: "正在检测",
    succeeded: "检测完成",
    failed: "检测失败",
    disabled: "未启用",
    partial: "部分完成",
  };
  return labels[status] ?? "状态未知";
}
