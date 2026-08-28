import { AuthApiError, get, post, userMessage } from "./auth-client";

export type VideoGenerationMode = "text" | "image";
export type VideoAspectRatio = "9:16" | "16:9";
export type VideoDurationSeconds = 5 | 10;
export type VideoJobStatus =
  "queued" | "processing" | "running" | "retry_wait" | "succeeded" | "failed";

export type VideoQuota = Readonly<{
  available: number;
  frozen: number;
  consumed: number;
  unlimited: boolean;
}>;

export type VideoAsset = Readonly<{
  id: string;
  subject_id: string;
  job_id: string;
  duration_seconds: VideoDurationSeconds;
  aspect_ratio: VideoAspectRatio;
  resolution: "720p";
  mime_type: string;
  size_bytes: number;
  is_subject_library: boolean;
  url: string | null;
  url_expires_in: number | null;
  version: number;
  created_at: string;
}>;

export type VideoJob = Readonly<{
  id: string;
  subject_id: string;
  generation_mode: VideoGenerationMode;
  prompt: string;
  source_document_version_id: string | null;
  aspect_ratio: VideoAspectRatio;
  duration_seconds: VideoDurationSeconds;
  resolution: "720p";
  status: VideoJobStatus;
  safe_error_code: string;
  quota_status: string;
  video: VideoAsset | null;
  version: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}>;

export type VideoPagination = Readonly<{
  page: number;
  page_size: number;
  count: number;
  total_pages: number;
}>;

export type VideoJobList = Readonly<{
  items: VideoJob[];
  pagination: VideoPagination;
  quota: VideoQuota;
}>;

export type VideoLibraryList = Readonly<{
  items: VideoAsset[];
  pagination: VideoPagination;
}>;

export type CreateVideoInput = Readonly<{
  generation_mode: VideoGenerationMode;
  prompt: string;
  source_document_version_id: string | null;
  aspect_ratio: VideoAspectRatio;
  duration_seconds: VideoDurationSeconds;
}>;

const VIDEO_ERROR_MESSAGES: Readonly<Record<string, string>> = Object.freeze({
  VIDEO_PROMPT_REQUIRED: "请填写内容描述。",
  VIDEO_PROMPT_TOO_LONG: "内容描述最多可填写 1500 个字。",
  VIDEO_SOURCE_IMAGE_REQUIRED: "图片生成视频需要先上传一张参考图片。",
  VIDEO_SOURCE_IMAGE_INVALID: "参考图片不可用，请重新上传 PNG、JPEG 或 WEBP 图片。",
  VIDEO_SOURCE_IMAGE_TOO_LARGE: "参考图片不能超过 20 MB。",
  VIDEO_DURATION_INVALID: "视频时长仅支持 5 秒或 10 秒。",
  VIDEO_ASPECT_RATIO_INVALID: "视频比例仅支持 9:16 或 16:9。",
  VIDEO_QUOTA_INSUFFICIENT: "当前视频额度不足，请查看套餐与额度。",
  VIDEO_PLAN_REQUIRED: "当前套餐暂不包含视频生成，请先查看可用套餐。",
  VIDEO_CONTENT_REJECTED: "本次内容未通过安全检查，请调整描述或参考图片后重试。",
  VIDEO_FIRST_FRAME_FAILED: "首帧图片未能生成，本次额度未扣除，请调整内容后重试。",
  VIDEO_PROVIDER_RATE_LIMIT: "当前使用人数较多，请稍后再生成。",
  VIDEO_PROVIDER_TIMEOUT: "视频生成时间较长，本次额度已释放，请重新生成。",
  VIDEO_PROVIDER_AUTHENTICATION_FAILED: "视频生成服务暂不可用，请联系管理员。",
  VIDEO_PROVIDER_TEMPORARY_FAILURE: "视频生成服务暂时不稳定，请稍后重新生成。",
  VIDEO_SUBMISSION_UNCERTAIN: "本次任务提交状态无法确认，额度已释放，请重新生成。",
  VIDEO_DOWNLOAD_FAILED: "视频暂时无法保存，本次额度已释放，请重新生成。",
  VIDEO_STORAGE_FAILED: "视频未能安全保存，本次额度已释放，请重新生成。",
  VIDEO_QUEUE_UNAVAILABLE: "当前生成服务较忙，请稍后重新生成。",
  VIDEO_INTERNAL_FAILURE: "本次视频未能生成，额度已释放，请重新尝试。",
});

export function videoUserMessage(reason: unknown): string {
  if (reason instanceof AuthApiError) {
    const detailCode = reason.details.video_code;
    const code = typeof detailCode === "string" ? detailCode : reason.code || reason.message;
    const exact = VIDEO_ERROR_MESSAGES[code.trim().toUpperCase()];
    if (exact) return exact;
  }
  return userMessage(reason);
}

export function videoFailureMessage(code: string): string {
  if (!code) return "本次视频未能生成，额度已释放，请重新尝试。";
  return (
    VIDEO_ERROR_MESSAGES[code.trim().toUpperCase()] ?? "本次视频未能生成，额度已释放，请重新尝试。"
  );
}

export const listSubjectVideoJobs = (
  subjectId: string,
  page = 1,
  pageSize = 20,
  signal?: AbortSignal,
) =>
  get<VideoJobList>(`/subjects/${subjectId}/video-jobs?page=${page}&page_size=${pageSize}`, {
    signal,
    cache: "no-store",
  });

export const createVideoJob = (
  subjectId: string,
  input: CreateVideoInput,
  idempotencyKey: string,
) =>
  post<{ job: VideoJob; quota: VideoQuota }>(`/subjects/${subjectId}/video-jobs`, input, {
    "Idempotency-Key": idempotencyKey,
  });

export const getVideoJob = (jobId: string, signal?: AbortSignal) =>
  get<VideoJob>(`/video-jobs/${jobId}`, { signal, cache: "no-store" });

export const regenerateVideoJob = (jobId: string, idempotencyKey: string) =>
  post<{ job: VideoJob; quota: VideoQuota }>(
    `/video-jobs/${jobId}/regenerate`,
    {},
    { "Idempotency-Key": idempotencyKey },
  );

export const saveVideoToLibrary = (jobId: string, expectedVersion: number) =>
  post<VideoAsset>(`/video-jobs/${jobId}/save-to-library`, {
    expected_version: expectedVersion,
  });

export const createVideoDownloadIntent = (jobId: string) =>
  post<{ url: string; expires_in: number }>(`/video-jobs/${jobId}/download-intents`, {});

export const listSubjectVideos = (
  subjectId: string,
  page = 1,
  pageSize = 20,
  signal?: AbortSignal,
) =>
  get<VideoLibraryList>(
    `/subjects/${subjectId}/videos?library=true&page=${page}&page_size=${pageSize}`,
    { signal, cache: "no-store" },
  );
