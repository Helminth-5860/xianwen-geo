import { get, post, remove } from "./auth-client";

export type DetectionStatus =
  "queued" | "running" | "partial" | "succeeded" | "failed" | "cancelled";

export type GeoDetectionJob = Readonly<{
  id: string;
  subject_id: string;
  status: DetectionStatus;
  version: number;
  planned_question_count: number;
  planned_model_count: number;
  planned_detection_points: number;
  completed_calls: number;
  successful_calls: number;
  failed_calls: number;
  cancelled_calls: number;
  progress_percent: number;
  queue_priority: number;
  queue_position: number | null;
  cancel_requested: boolean;
  quota: {
    quota_type: "geo_detection_runs" | "detection_points";
    status: "open" | "partially_settled" | "settled";
    held: number;
    consumed: number;
    released: number;
  };
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
}>;

export type GeoModelProgress = Readonly<{
  model_id: string;
  model_key: string;
  provider_key: string;
  provider_model_id: string;
  status: DetectionStatus;
  planned_calls: number;
  completed_calls: number;
  successful_calls: number;
  failed_calls: number;
  cancelled_calls: number;
  web_search_used_count: number;
  degraded_count: number;
}>;

export type GeoDetectionEstimate = Readonly<{
  question_count: number;
  model_count: number;
  required_detection_runs: number;
  available_detection_runs: number;
  active_detection_jobs: number;
  concurrent_detection_jobs: number;
  can_submit: boolean;
}>;

export type GeoDetectionCreated = Readonly<{
  detection_id: string;
  status: DetectionStatus;
  planned_detection_points: number;
  quota_hold: number;
  status_url: string;
  replayed: boolean;
}>;

export type GeoDetectionHistoryPage = Readonly<{
  items: GeoDetectionJob[];
  pagination?: Readonly<{
    page: number;
    page_size: number;
    count: number;
    total_pages: number;
  }>;
}>;

export const terminalDetectionStatuses = new Set<DetectionStatus>([
  "partial",
  "succeeded",
  "failed",
  "cancelled",
]);

export const getDetectionJob = (detectionId: string, signal?: AbortSignal) =>
  get<GeoDetectionJob>(`/geo/detections/${detectionId}`, { signal, cache: "no-store" });

export const getDetectionModelProgress = (detectionId: string, signal?: AbortSignal) =>
  get<{ items: GeoModelProgress[] }>(`/geo/detections/${detectionId}/model-progress`, {
    signal,
    cache: "no-store",
  });

export async function getDetectionProgress(detectionId: string, signal?: AbortSignal) {
  const [job, models] = await Promise.all([
    getDetectionJob(detectionId, signal),
    getDetectionModelProgress(detectionId, signal),
  ]);
  return { job, models: models.items } as const;
}

export const getDetectionHistory = (subjectId: string, page = 1) =>
  get<GeoDetectionHistoryPage>(`/subjects/${subjectId}/geo/detections?page=${page}&page_size=20`);

export const removeDetectionResult = (subjectId: string, detectionId: string) =>
  remove<{ removed: true }>(`/subjects/${subjectId}/geo/detections/${detectionId}`);

export const estimateDetection = (subjectId: string, questionIds: string[], modelIds: string[]) =>
  post<GeoDetectionEstimate>(`/subjects/${subjectId}/geo/estimate`, {
    question_ids: questionIds,
    model_ids: modelIds,
    mode: "new",
  });

export const createDetection = (
  subjectId: string,
  questionIds: string[],
  modelIds: string[],
  idempotencyKey: string,
) =>
  post<GeoDetectionCreated>(
    `/subjects/${subjectId}/geo/detections`,
    { question_ids: questionIds, model_ids: modelIds, mode: "new" },
    { "Idempotency-Key": idempotencyKey },
  );
