import { get, post } from "./auth-client";

export type SourceIndexStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "partial"
  | "limit_reached"
  | "failed";

export type SourceIndexStage =
  | "preparing"
  | "searching"
  | "classifying"
  | "scoring"
  | "completed";

export type SourceType =
  | "government_association"
  | "news_media"
  | "industry_media"
  | "enterprise_site"
  | "content_platform"
  | "directory_business"
  | "forum_community"
  | "other";

export type SourceIndexProgress = Readonly<{
  queries_planned?: number;
  queries_remaining?: number;
  raw?: number;
  unique?: number;
  batch_new?: number;
  batch_yield?: number;
  public_sources?: number;
  independent_domains?: number;
  news_media?: number;
}>;

export type SourceIndexFactors = Readonly<{
  exposure?: number;
  diversity?: number;
  authority?: number;
  visibility?: number;
  freshness?: number;
}>;

export type SourceIndexScanSummary = Readonly<{
  id: string;
  subject_id: string;
  status: SourceIndexStatus;
  stage: SourceIndexStage;
  provider: string;
  query_count: number;
  provider_request_count: number;
  provider_error_count: number;
  raw_result_count: number;
  unique_result_count: number;
  public_source_count: number;
  independent_domain_count: number;
  news_media_count: number;
  high_weight_count: number;
  recent_30d_count: number;
  index_score: string | null;
  factor_scores: SourceIndexFactors;
  progress: SourceIndexProgress;
  formula_version: string;
  stable_error_code: string;
  elapsed_seconds: number | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}>;

export type SourceTypeDistribution = Readonly<{
  source_type: SourceType;
  count: number;
}>;

export type QueryCoverage = Readonly<{
  query: string;
  source_count: number;
  independent_source_count: number;
  best_rank: number | null;
}>;

export type TopSource = Readonly<{
  root_domain: string;
  source_type: SourceType;
  source_count: number;
  average_weight: number;
  highest_weight: number;
}>;

export type SourceIndexScanDetail = SourceIndexScanSummary &
  Readonly<{
    source_type_distribution: SourceTypeDistribution[];
    query_coverage: QueryCoverage[];
    top_sources: TopSource[];
  }>;

export type SourceIndexState = Readonly<{
  active_scan: SourceIndexScanSummary | null;
  latest_result: SourceIndexScanDetail | null;
}>;

export type SourceIndexItem = Readonly<{
  id: string;
  original_url: string;
  domain: string;
  root_domain: string;
  website: string;
  title: string;
  snippet: string;
  published_at: string | null;
  source_type: SourceType;
  authority_score: number;
  relevance_score: number;
  visibility_score: number;
  freshness_score: number;
  source_weight: string;
  best_rank: number;
  matched_query_count: number;
  matched_queries: string[];
  repost_cluster_id: string;
  score_version: string;
}>;

export type PaginatedSourceIndexItems = Readonly<{
  count: number;
  next: string | null;
  previous: string | null;
  results: SourceIndexItem[];
}>;

export type SourceIndexOrdering =
  | "source_weight"
  | "-source_weight"
  | "published_at"
  | "-published_at"
  | "best_rank"
  | "-best_rank"
  | "authority_score"
  | "-authority_score";

export const getSourceIndexState = (subjectId: string) =>
  get<SourceIndexState>(`/subjects/${subjectId}/source-index/`);

export const startSourceIndexScan = (subjectId: string) =>
  post<SourceIndexScanSummary>(`/subjects/${subjectId}/source-index/scans/`, {});

export const getSourceIndexScan = (scanId: string) =>
  get<SourceIndexScanDetail>(`/source-index/scans/${scanId}/`);

export const getSourceIndexItems = (
  scanId: string,
  options: Readonly<{
    page?: number;
    pageSize?: number;
    sourceType?: SourceType;
    ordering?: SourceIndexOrdering;
  }> = {},
) => {
  const params = new URLSearchParams();
  if (options.page) params.set("page", String(options.page));
  if (options.pageSize) params.set("page_size", String(options.pageSize));
  if (options.sourceType) params.set("source_type", options.sourceType);
  if (options.ordering) params.set("ordering", options.ordering);
  const suffix = params.size ? `?${params.toString()}` : "";
  return get<PaginatedSourceIndexItems>(`/source-index/scans/${scanId}/sources/${suffix}`);
};
