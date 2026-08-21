import { get, post } from "./auth-client";

export type ImageSizePreset = Readonly<{
  id: string;
  key: string;
  name: string;
  aspect_ratio: string;
  width: number;
  height: number;
  applicable_channels: string[];
  applicable_roles: string[];
  version: number;
}>;

export type ImageStylePreset = Readonly<{
  id: string;
  key: string;
  name: string;
  description: string;
  applicable_roles: string[];
  version: number;
}>;

export type ImageQuota = Readonly<{ available: number; frozen: number; consumed: number }>;

export type ImageAsset = Readonly<{
  id: string;
  subject_id: string;
  article_id: string | null;
  job_id: string | null;
  role: "cover" | "illustration" | "channel";
  source_type: "generated" | "uploaded" | "derivative";
  width: number;
  height: number;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  provider: string;
  provider_model: string;
  generation_capability: string;
  adapter_version: string;
  moderation_status: "approved" | "suspected" | "rejected" | "service_error";
  is_subject_library: boolean;
  lifecycle_status: "active" | "trashed";
  url: string | null;
  url_expires_in: number | null;
  generated_at: string | null;
  available_at: string;
  created_at: string;
  version?: number;
}>;

export type ImageJob = Readonly<{
  id: string;
  subject_id: string;
  article_id: string | null;
  generation_type: "generate" | "edit";
  role: ImageAsset["role"];
  status: "queued" | "running" | "retry_wait" | "succeeded" | "failed";
  attempt_count: number;
  max_retries: number;
  safe_error_code: string;
  provider: string;
  provider_model: string;
  runtime_version: number;
  adapter_version: string;
  prompt_version: string;
  quota_status: string;
  image: ImageAsset | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}>;

export type ImageRecommendation = Readonly<{
  position: string;
  role: ImageAsset["role"];
  purpose: string;
  prompt: string;
  size_preset_id: string;
  style_preset_id: string;
  requires_confirmation: true;
}>;

export const getImageSizes = () => get<ImageSizePreset[]>("/image-sizes");
export const getImageStyles = () => get<ImageStylePreset[]>("/image-styles");
export const getImageRecommendations = (articleId: string) =>
  post<{ article_id: string; recommendations: ImageRecommendation[] }>(
    `/articles/${articleId}/image-recommendations`,
    {},
  );
export const getSubjectImages = (subjectId: string, library = false) =>
  get<{ results: ImageAsset[]; quota: ImageQuota }>(
    `/subjects/${subjectId}/images${library ? "?library=true" : ""}`,
  );
export const getImageJob = (jobId: string) => get<ImageJob>(`/image-jobs/${jobId}`);

export function generateImage(
  subjectId: string,
  input: {
    article_id: string | null;
    role: ImageAsset["role"];
    prompt: string;
    size_preset_id: string;
    style_preset_id: string;
    reference_asset_id?: string | null;
    reference_document_version_id?: string | null;
    reference_url?: string;
  },
) {
  return post<{ job: ImageJob; jobs: ImageJob[]; quota: ImageQuota }>(
    `/subjects/${subjectId}/images/generate`,
    input,
    { "Idempotency-Key": crypto.randomUUID() },
  );
}

export const saveImageToLibrary = (imageId: string, expectedVersion: number) =>
  post<ImageAsset>(`/images/${imageId}/save-to-library`, {
    expected_version: expectedVersion,
  });
export const attachImage = (imageId: string, articleId: string, expectedVersion: number) =>
  post<ImageAsset>(`/images/${imageId}/attach`, {
    article_id: articleId,
    expected_version: expectedVersion,
  });
export const deriveImage = (
  imageId: string,
  input: {
    kind: "compressed" | "crop" | "channel" | "format";
    width: number;
    height: number;
    output_format: "png" | "jpeg" | "webp";
  },
) => post<{ id: string; url: string | null }>(`/images/${imageId}/derive`, input);
export const deriveImageAI = (
  imageId: string,
  input: { prompt: string; size_preset_id: string; style_preset_id: string },
) =>
  post<{ job: ImageJob; quota: ImageQuota }>(
    `/images/${imageId}/derive`,
    { ai: true, ...input },
    { "Idempotency-Key": crypto.randomUUID() },
  );
export const createImageBatchDownload = (subjectId: string, imageIds: string[]) =>
  post<{ id: string; image_count: number; url: string; expires_at: string }>(
    "/images/batch-download",
    { subject_id: subjectId, image_ids: imageIds },
  );
export const appealImageModeration = (imageId: string, note: string) =>
  post<{ status: string; appeal_no: number }>(`/images/${imageId}/moderation/appeal`, { note });
