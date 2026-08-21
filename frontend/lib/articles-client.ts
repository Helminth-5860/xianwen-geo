import { get, post, write } from "./auth-client";

export type ArticleType = Readonly<{
  id: string;
  key: string;
  name: string;
  description: string;
  template_version: {
    id: string;
    version_no: number;
    structure: Record<string, unknown>;
    network_policy: "required" | "optional" | "disabled";
    citation_required: boolean;
    allowed_source_types: string[];
    recommended_channel_keys: string[];
  };
}>;

export type SourcePack = Readonly<{
  id: string;
  subject_id: string;
  subject_version_id: string;
  article_type_id: string;
  template_version_id: string;
  status: "draft" | "confirmed";
  conflict_status: "clear" | "pending" | "resolved";
  conflicts: ReadonlyArray<{
    key: string;
    options: ReadonlyArray<{ value: string; source_item_ids: string[] }>;
  }>;
  items: ReadonlyArray<{
    id: string;
    source_type: "subject" | "document" | "web";
    title: string;
    url: string;
    trust_level: number;
    verification_status: "verified" | "rejected";
    excerpt: string;
    user_confirmed: boolean;
  }>;
  snapshot_digest: string | null;
}>;

export type ArticleQuality = Readonly<{
  total_score: number;
  grade: "excellent" | "good" | "fair" | "optimization_recommended";
  dimensions: Record<string, number>;
  weights: Record<string, number>;
  suggestions: string[];
  first_free: boolean;
  advisory_only: true;
}>;

export type Article = Readonly<{
  id: string;
  subject_id: string;
  subject_version_id: string;
  article_type: { id: string; key: string; name: string } | null;
  custom_type: string;
  template_version_id: string | null;
  source_pack_id: string | null;
  title: string;
  content: string;
  status: "draft" | "generating" | "reviewing" | "ready" | "rejected";
  content_depth: "concise" | "standard" | "deep";
  moderation_status: "not_checked" | "passed" | "manual_review" | "rejected";
  current_quality_score: number | null;
  quality: ArticleQuality | null;
  citations: ReadonlyArray<{ source_item_id: string; paragraph_index: number }>;
  outline: {
    text: string;
    status: "empty" | "generating" | "ready" | "confirmed" | "failed";
    generation_count: number;
    version: number;
  } | null;
  version: number;
  autosaved_at: string | null;
}>;

export type ArticleJob = Readonly<{
  id: string;
  article_id: string;
  operation: string;
  status: "queued" | "running" | "succeeded" | "failed";
  billing: { quota_type: string | null; held: boolean; consumed: boolean };
  comparison_id: string | null;
  adaptation_id: string | null;
  safe_error_code: string;
}>;

export type PublishingChannel = Readonly<{
  id: string;
  key: string;
  name: string;
  official_url: string;
  channel_type: string;
  description: string;
  image_ratios: string[];
  template_version_id: string;
  rules: Record<string, unknown>;
  actual_publishing_supported: false;
}>;

export type ChannelAdaptation = Readonly<{
  id: string;
  article_id: string;
  channel: PublishingChannel;
  template_version_id: string;
  job_id: string;
  title: string;
  content: string;
  status: "queued" | "running" | "ready" | "failed";
  quality_score: number | null;
  safe_error_code: string;
  version: number;
}>;

export const getArticleTypes = () => get<{ items: ArticleType[] }>("/article-types");

export const createSourcePack = (
  subjectId: string,
  articleTypeId: string,
  documentSourceIds: string[],
  webSourceIds: string[],
) =>
  post<SourcePack>("/articles/source-packs", {
    subject_id: subjectId,
    article_type_id: articleTypeId,
    document_source_ids: documentSourceIds,
    web_source_ids: webSourceIds,
  });

export const confirmSourcePack = (
  pack: SourcePack,
  selectedItemIds: string[],
  conflictResolutions: Array<{ key: string; value: string }>,
) =>
  post<SourcePack>(`/articles/source-packs/${pack.id}/confirm`, {
    selected_item_ids: selectedItemIds,
    conflict_resolutions: conflictResolutions,
  });

export const createArticle = (
  subjectId: string,
  input: {
    article_type_id: string;
    content_depth: Article["content_depth"];
    title: string;
    source_pack_id: string;
  },
) => post<Article>(`/subjects/${subjectId}/articles`, input);

export const getArticle = (articleId: string) => get<Article>(`/articles/${articleId}`);

export const saveArticleDraft = (article: Article, title: string, content: string) =>
  write<Article>("PATCH", `/articles/${article.id}/draft`, {
    title,
    content,
    content_depth: article.content_depth,
    expected_version: article.version,
  });

export const generateOutline = (articleId: string) =>
  post<ArticleJob>(
    `/articles/${articleId}/outline/generate`,
    {},
    { "Idempotency-Key": crypto.randomUUID() },
  );

export const saveOutline = (article: Article, text: string, confirm: boolean) =>
  write<{ text: string; status: string; version: number }>(
    "PATCH",
    `/articles/${article.id}/outline`,
    { text, confirm, expected_version: article.outline?.version ?? 1 },
  );

export const generateArticle = (articleId: string) =>
  post<ArticleJob>(
    `/articles/${articleId}/generate`,
    {},
    { "Idempotency-Key": crypto.randomUUID() },
  );

export const getArticleJob = (jobId: string) => get<ArticleJob>(`/article-jobs/${jobId}`);

export const recheckQuality = (articleId: string) =>
  post<ArticleJob>(
    `/articles/${articleId}/quality-check`,
    {},
    { "Idempotency-Key": crypto.randomUUID() },
  );

export const optimizeArticle = (articleId: string, mode: "local" | "full", instruction: string) =>
  post<ArticleJob>(
    `/articles/${articleId}/optimize/${mode}`,
    { instruction, selection: "" },
    { "Idempotency-Key": crypto.randomUUID() },
  );

export const getComparison = (comparisonId: string) =>
  get<{
    id: string;
    original: { title: string; content: string };
    optimized: { title: string; content: string };
  }>(`/article-comparisons/${comparisonId}`);

export const chooseComparison = (comparisonId: string, choice: "original" | "optimized") =>
  post<Article>(`/article-comparisons/${comparisonId}/choose`, { choice });

export const getPublishingChannels = () =>
  get<{ items: PublishingChannel[] }>("/publishing-channels");

export const createChannelAdaptations = (articleId: string, channelIds: string[]) =>
  post<{
    items: Array<ChannelAdaptation & { job: ArticleJob }>;
    estimated_article_credits: number;
  }>(
    `/articles/${articleId}/channel-adaptations`,
    { channel_ids: channelIds },
    { "Idempotency-Key": crypto.randomUUID() },
  );

export const getChannelAdaptations = (articleId: string) =>
  get<{ items: ChannelAdaptation[] }>(`/articles/${articleId}/channel-adaptations`);

export const createArticleExport = (articleId: string, format: string) =>
  post<{ download_url: string }>(`/articles/${articleId}/exports`, { format });

export const checkPublication = (
  subjectId: string,
  articleId: string,
  channelId: string,
  url: string,
) =>
  post<{
    result: "success" | "failed" | "unknown";
    detected_title: string;
    match_summary: string;
    safe_failure_code: string;
  }>("/publication-checks", {
    subject_id: subjectId,
    article_id: articleId,
    channel_id: channelId,
    url,
  });
