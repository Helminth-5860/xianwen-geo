import { get, post } from "./auth-client";

export type NegativeIndexStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "partial"
  | "limit_reached"
  | "failed";

export type NegativeIndexStage =
  | "preparing"
  | "searching"
  | "classifying"
  | "verifying"
  | "clustering"
  | "scoring"
  | "completed";

export type NegativeCategory =
  | "regulatory"
  | "judicial"
  | "consumer_complaint"
  | "product_service_incident"
  | "business_operation"
  | "media_negative"
  | "online_opinion"
  | "other";

export type NegativeEventStatus =
  | "suspected"
  | "reported"
  | "confirmed"
  | "disputed"
  | "resolved"
  | "retracted"
  | "false_positive";

export type NegativeClaimType =
  | "official_finding"
  | "reported_fact"
  | "reported_claim"
  | "user_allegation"
  | "opinion"
  | "rumor"
  | "rebuttal";

export type NegativeIndexScanSummary = Readonly<{
  id: string;
  subject_id: string;
  status: NegativeIndexStatus;
  stage: NegativeIndexStage;
  provider: string;
  ai_provider: string;
  ai_model_key: string;
  query_count: number;
  provider_request_count: number;
  provider_error_count: number;
  raw_result_count: number;
  unique_result_count: number;
  candidate_count: number;
  negative_item_count: number;
  event_count: number;
  high_risk_event_count: number;
  recent_30d_event_count: number;
  verified_item_count: number;
  index_score: string | null;
  risk_level: "low" | "watch" | "elevated" | "high";
  factor_scores: Readonly<Record<string, number>>;
  progress: Readonly<Record<string, number>>;
  formula_version: string;
  classifier_version: string;
  stable_error_code: string;
  elapsed_seconds: number | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}>;

export type DistributionRow = Readonly<{
  category?: NegativeCategory;
  status?: NegativeEventStatus;
  count: number;
}>;

export type NegativeIndexScanDetail = NegativeIndexScanSummary &
  Readonly<{
    category_distribution: DistributionRow[];
    status_distribution: DistributionRow[];
  }>;

export type NegativeIndexState = Readonly<{
  active_scan: NegativeIndexScanSummary | null;
  latest_result: NegativeIndexScanDetail | null;
  history: NegativeIndexScanSummary[];
}>;

export type NegativeEvent = Readonly<{
  id: string;
  category: NegativeCategory;
  claim_type: NegativeClaimType;
  status: NegativeEventStatus;
  title: string;
  summary: string;
  severity_score: number;
  evidence_score: number;
  visibility_score: number;
  freshness_score: number;
  current_risk: string;
  source_count: number;
  independent_domain_count: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
}>;

export type NegativeSource = Readonly<{
  id: string;
  original_url: string;
  domain: string;
  root_domain: string;
  website: string;
  title: string;
  snippet: string;
  published_at: string | null;
  source_type: string;
  authority_score: number;
  relevance_score: number;
  visibility_score: number;
  freshness_score: number;
  best_rank: number;
  matched_query_count: number;
  matched_queries: string[];
  rule_signal_score: number;
  negative_confidence: number;
  severity_score: number;
  evidence_confidence: number;
  category: NegativeCategory;
  claim_type: NegativeClaimType;
  event_status: NegativeEventStatus;
  event_title: string;
  ai_summary: string;
  classification_source: "ai" | "rule" | "verified_ai";
  verification_status: "not_requested" | "succeeded" | "failed";
  verification_excerpt: string;
  verification_error_code: string;
}>;

export type NegativeEventDetail = NegativeEvent & Readonly<{ sources: NegativeSource[] }>;

export type PaginatedNegativeEvents = Readonly<{
  count: number;
  next: string | null;
  previous: string | null;
  results: NegativeEvent[];
}>;

export const getNegativeIndexState = (subjectId: string) =>
  get<NegativeIndexState>(`/subjects/${subjectId}/negative-index/`);

export const startNegativeIndexScan = (subjectId: string) =>
  post<NegativeIndexScanSummary>(`/subjects/${subjectId}/negative-index/scans/`, {});

export const getNegativeIndexScan = (scanId: string) =>
  get<NegativeIndexScanDetail>(`/negative-index/scans/${scanId}/`);

export const getNegativeIndexEvents = (
  scanId: string,
  options: Readonly<{
    page?: number;
    pageSize?: number;
    category?: NegativeCategory;
    status?: NegativeEventStatus;
    ordering?: "current_risk" | "-current_risk" | "last_seen_at" | "-last_seen_at";
  }> = {},
) => {
  const params = new URLSearchParams();
  if (options.page) params.set("page", String(options.page));
  if (options.pageSize) params.set("page_size", String(options.pageSize));
  if (options.category) params.set("category", options.category);
  if (options.status) params.set("status", options.status);
  if (options.ordering) params.set("ordering", options.ordering);
  const suffix = params.size ? `?${params.toString()}` : "";
  return get<PaginatedNegativeEvents>(`/negative-index/scans/${scanId}/events/${suffix}`);
};

export const getNegativeEvent = (eventId: string) =>
  get<NegativeEventDetail>(`/negative-index/events/${eventId}/`);
