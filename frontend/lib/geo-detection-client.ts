import { get, post } from "./auth-client";

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
  required_detection_points: number;
  available_detection_points: number;
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

export const terminalDetectionStatuses = new Set<DetectionStatus>([
  "partial",
  "succeeded",
  "failed",
  "cancelled",
]);

export async function getDetectionProgress(detectionId: string) {
  const [job, models] = await Promise.all([
    get<GeoDetectionJob>(`/geo/detections/${detectionId}`),
    get<{ items: GeoModelProgress[] }>(`/geo/detections/${detectionId}/model-progress`),
  ]);
  return { job, models: models.items } as const;
}

export const getDetectionHistory = (subjectId: string) =>
  get<{ items: GeoDetectionJob[] }>(`/subjects/${subjectId}/geo/detections`);

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
