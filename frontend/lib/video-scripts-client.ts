import { get, post, write } from "./auth-client";

export type VideoPlatform =
  | "douyin"
  | "wechat_channels"
  | "xiaohongshu"
  | "bilibili"
  | "general";

export type VideoType = "talking_head" | "brand" | "product" | "knowledge" | "case";
export type VideoStyle = "professional" | "natural" | "emotional" | "conversion" | "knowledge";
export type VideoSourceMode = "subject" | "article" | "custom";

export type VideoScriptScene = Readonly<{
  scene: number;
  start: number;
  end: number;
  visual: string;
  voiceover: string;
  subtitle: string;
}>;

export type VideoScriptContent = Readonly<{
  hooks: string[];
  scenes: VideoScriptScene[];
  full_voiceover: string;
  cta: string;
  duration_seconds?: number;
}>;

export type VideoScript = Readonly<{
  id: string;
  subject_id: string;
  subject_version_id: string;
  title: string;
  status: "draft" | "generating" | "reviewing" | "ready" | "rejected";
  config: {
    platform: VideoPlatform;
    video_type: VideoType;
    duration_seconds: number;
    style: VideoStyle;
    source_mode: VideoSourceMode;
    topic: string;
    source_article_id: string | null;
  };
  source_summary: {
    mode: VideoSourceMode;
    item_count: number;
    source_types: string[];
    source_article_id: string | null;
  };
  script: VideoScriptContent | null;
  version: number;
  autosaved_at: string | null;
}>;

export type VideoScriptJob = Readonly<{
  id: string;
  article_id: string;
  operation: "video_script" | string;
  status: "queued" | "running" | "succeeded" | "failed";
  billing: { quota_type: string | null; held: boolean; consumed: boolean };
  safe_error_code: string;
}>;

export type VideoArticleOption = Readonly<{
  id: string;
  title: string;
  status: string;
  updated_at: string;
}>;

export const getVideoArticleOptions = (subjectId: string) =>
  get<{ items: VideoArticleOption[] }>(`/subjects/${subjectId}/video-script-article-options`);

export const createVideoScript = (
  subjectId: string,
  input: {
    platform: VideoPlatform;
    video_type: VideoType;
    duration_seconds: number;
    style: VideoStyle;
    source_mode: VideoSourceMode;
    topic: string;
    document_source_ids: string[];
    web_source_ids: string[];
    source_article_id?: string | null;
  },
) => post<VideoScript>(`/subjects/${subjectId}/video-scripts`, input);

export const getVideoScript = (videoScriptId: string) =>
  get<VideoScript>(`/video-scripts/${videoScriptId}`);

export const generateVideoScript = (videoScriptId: string) =>
  post<VideoScriptJob>(
    `/video-scripts/${videoScriptId}/generate`,
    {},
    { "Idempotency-Key": crypto.randomUUID() },
  );

export const getVideoScriptJob = (jobId: string) =>
  get<VideoScriptJob>(`/article-jobs/${jobId}`);

export const saveVideoScript = (
  video: VideoScript,
  input: {
    title: string;
    hooks: string[];
    scenes: VideoScriptScene[];
    full_voiceover: string;
    cta: string;
  },
) =>
  write<VideoScript>("PATCH", `/video-scripts/${video.id}`, {
    ...input,
    expected_version: video.version,
  });
