import { get, post } from "./auth-client";

export type ReportTrack = Readonly<{
  score: string | null;
  grade?: string | null;
  status: "formal" | "reference" | "failed" | "not_generated";
  formal_model_count?: number;
  planned_count?: number;
  successful_count?: number;
  success_rate?: string | null;
}>;

export type ReportModel = Readonly<{
  model_id: string;
  model_key: string;
  status: string;
  planned_calls: number;
  completed_calls: number;
  successful_calls: number;
  failed_calls: number;
  cancelled_calls: number;
  geo: ReportTrack | null;
  brand_reputation: ReportTrack | null;
}>;

export type GeoReportComparison = Readonly<{
  baseline_report_id: string;
  status: "comparable" | "not_comparable";
  same_subject: boolean;
  same_questions: boolean;
  same_models: boolean;
  same_scoring_rule: boolean;
  subject_version_changed: boolean;
  scoring_version_changed: boolean;
  geo_score_delta: string | null;
  brand_reputation_score_delta: string | null;
  exposure_index_delta: string | null;
  dimension_deltas: Record<string, string | null>;
  model_deltas: ReadonlyArray<{
    model_id: string;
    model_key: string;
    geo_score_delta: string | null;
    brand_reputation_score_delta: string | null;
  }>;
}>;

export type GeoReport = Readonly<{
  id: string;
  detection_id: string;
  subject_id: string;
  subject_version_id: string;
  retest_mode: "" | "quick" | "adjusted";
  summary: {
    geo: ReportTrack;
    brand_reputation: ReportTrack;
    exposure: {
      exposure_index: string;
      grade: string;
      status: "formal" | "reference";
      disclaimer: string;
      mention_rate_score: string;
      recommendation_rate_score: string;
      ranking_performance_score: string;
      model_coverage_score: string;
    };
    models: ReportModel[];
    dimensions: Record<string, string | null>;
    competitors: Array<{
      id: string;
      canonical_name: string;
      aliases: string[];
      entity_type: string;
      mention_count: number;
    }>;
  };
  provenance: {
    scoring_rule_version: string;
    questions: Array<{ source_question_id: string; text: string }>;
    models: Array<{ model_id: string; model_key: string }>;
  };
  comparison: GeoReportComparison | null;
  generated_at: string;
}>;

export type GeoReportPairComparison = Readonly<{
  current: GeoReport;
  baseline: GeoReport;
  comparison: GeoReportComparison;
}>;

export type ReportQuestionPage = Readonly<{
  results: Array<{
    question_id: string;
    source_question_id: string;
    question_type: "natural" | "brand_directed";
    text: string;
    results: Array<{
      call_id: string;
      model_id: string;
      model_key: string;
      status: string;
      safe_error_summary: Record<string, unknown>;
      answer_available: boolean;
      snippet: string;
      score: Record<string, string | null> | null;
      citations: Array<{
        title: string;
        url: string;
        source_name: string;
        quoted_text: string;
      }>;
    }>;
  }>;
  pagination: {
    page: number;
    page_size: number;
    count: number;
    total_pages: number;
  };
}>;

export type ReportAnswer = Readonly<{
  call_id: string;
  model_key: string;
  answer: string;
  citations: Array<{ title: string; url: string; source_name: string; quoted_text: string }>;
}>;

export type ReportTrend = Readonly<{
  report_id: string;
  generated_at: string;
  subject_version_id: string;
  geo_score: string | null;
  comparison: GeoReportComparison | null;
}>;

export type ReportExport = Readonly<{
  id: string;
  report_id: string;
  format: "pdf" | "word" | "excel";
  status: "queued" | "running" | "succeeded" | "failed";
  safe_error_code: string;
  download_url: string | null;
  expires_at: string | null;
  expired: boolean;
}>;

export type RetestCreated = Readonly<{
  detection_id: string;
  status: string;
  replayed: boolean;
}>;

export type GeoModelOption = Readonly<{
  id: string;
  model_key: string;
  display_name: string;
  selected_by_default: boolean;
  enabled: boolean;
  paused: boolean;
  configured: boolean;
}>;

export type DetectionOptions = Readonly<{
  models: GeoModelOption[];
  max_questions_per_detection: number;
  max_models_per_detection: number;
  available_detection_runs: number;
  can_start_job: boolean;
}>;

export const getReportForDetection = (detectionId: string) =>
  get<GeoReport>(`/geo/detections/${detectionId}/report`);

export const getReport = (reportId: string) => get<GeoReport>(`/geo/reports/${reportId}`);

export const getReportComparison = (reportId: string, otherId: string) =>
  get<GeoReportPairComparison>(`/geo/reports/${reportId}/comparison/${otherId}`);

export const getReportQuestions = (reportId: string, page: number) =>
  get<ReportQuestionPage>(`/geo/reports/${reportId}/questions?page=${page}`);

export const getReportAnswer = (callId: string) =>
  get<ReportAnswer>(`/geo/model-calls/${callId}/response`);

export const getReportHistory = (subjectId: string) =>
  get<{ items: GeoReport[] }>(`/subjects/${subjectId}/geo/reports`);

export const getReportTrends = (subjectId: string) =>
  get<{ items: ReportTrend[] }>(`/subjects/${subjectId}/geo/trends`);

export const createReportExport = (reportId: string, format: ReportExport["format"]) =>
  post<Pick<ReportExport, "id" | "status">>(`/geo/reports/${reportId}/exports`, { format });

export const getReportExport = (exportId: string) =>
  get<ReportExport>(`/report-exports/${exportId}`);

export const quickRetest = (reportId: string, idempotencyKey: string) =>
  post<RetestCreated>(
    `/geo/reports/${reportId}/retest`,
    { mode: "quick" },
    { "Idempotency-Key": idempotencyKey },
  );

export const adjustedRetest = (
  reportId: string,
  questionIds: string[],
  modelIds: string[],
  idempotencyKey: string,
) =>
  post<RetestCreated>(
    `/geo/reports/${reportId}/retest`,
    { mode: "adjusted", question_ids: questionIds, model_ids: modelIds },
    { "Idempotency-Key": idempotencyKey },
  );

export const getDetectionOptions = (subjectId: string) =>
  get<DetectionOptions>(`/subjects/${subjectId}/geo/detection-options`);
