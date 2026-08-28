import { get, post, remove, write } from "./auth-client";

export type PlatformAccount = Readonly<{
  id: string;
  display_name: string;
  external_account_id: string;
  auth_method: "browser_qr" | "official_credentials" | "hybrid";
  auth_status:
    | "authorizing"
    | "authorized"
    | "expired"
    | "needs_verification"
    | "revoked"
    | "failed";
  enabled_for_auto_publish: boolean;
  authorized_at: string | null;
  expires_at: string | null;
  last_auth_check_at: string | null;
  version: number;
}>;

export type PublicationPlatform = Readonly<{
  id: string;
  key: string;
  name: string;
  official_url: string;
  channel_type: string;
  auth_mode: "browser_qr" | "official_credentials" | "hybrid";
  publish_mode: "browser" | "official_api" | "hybrid";
  validation_status: "available" | "testing" | "paused";
  health_status: "healthy" | "degraded" | "unavailable";
  capabilities: Record<string, boolean>;
  minimum_interval_minutes: number;
  account: PlatformAccount | null;
}>;

export type AutoPublishPolicy = Readonly<{
  id: string;
  subject_id: string;
  enabled: boolean;
  operating_mode: "managed" | "review" | "selected";
  distribution_strategy: "smart" | "all_authorized" | "custom";
  custom_platform_keys: string[];
  frequency_mode: "smart" | "daily_1" | "daily_2" | "daily_3" | "custom";
  custom_daily_limit: number;
  image_strategy: "customer_only" | "prefer_customer" | "auto";
  image_richness: "simple" | "standard" | "rich";
  version: number;
  updated_at: string;
}>;

export type PublicationTarget = Readonly<{
  id: string;
  platform_key: string;
  platform_name: string;
  status:
    | "waiting"
    | "adapting"
    | "ready"
    | "scheduled"
    | "publishing"
    | "published"
    | "failed"
    | "requires_auth"
    | "skipped";
  scheduled_at: string | null;
  published_at: string | null;
  public_url: string;
  external_post_id: string;
  safe_error_code: string;
  attempts: number;
  adaptation_id: string | null;
}>;

export type PublicationVisual = Readonly<{
  id: string;
  image_id: string;
  image_url: string;
  role: "cover" | "illustration" | "thumbnail" | "card";
  ordinal: number;
  source_strategy: string;
}>;

export type PublicationJob = Readonly<{
  id: string;
  subject_id: string;
  article: { id: string; title: string };
  status:
    | "planning"
    | "preparing"
    | "scheduled"
    | "publishing"
    | "succeeded"
    | "partial"
    | "failed"
    | "cancelled";
  policy_snapshot: Record<string, unknown>;
  distribution_plan: Record<string, unknown>;
  visual_plan: Record<string, unknown>;
  scheduled_for: string | null;
  safe_error_code: string;
  created_at: string;
  finished_at: string | null;
  visuals: PublicationVisual[];
  targets: PublicationTarget[];
}>;

export type AuthorizationSession = Readonly<{
  id: string;
  platform_key: string;
  platform_name: string;
  status:
    | "queued"
    | "waiting"
    | "authorized"
    | "needs_interaction"
    | "expired"
    | "failed"
    | "cancelled";
  auth_method: string;
  login_snapshot_data_url: string;
  safe_error_code: string;
  expires_at: string;
  last_snapshot_at: string | null;
  account: PlatformAccount | null;
}>;

export type AutoPublishState = Readonly<{
  policy: AutoPublishPolicy;
  platforms: PublicationPlatform[];
  summary: {
    authorized: number;
    platform_total: number;
    today_planned: number;
    today_published: number;
    needs_attention: number;
  };
  today_targets: PublicationTarget[];
  recent_jobs: PublicationJob[];
}>;

export const getAutoPublishState = (subjectId: string) =>
  get<AutoPublishState>(`/subjects/${subjectId}/auto-publish`);

export const updateAutoPublishPolicy = (
  subjectId: string,
  input: Omit<AutoPublishPolicy, "id" | "subject_id" | "version" | "updated_at"> & {
    expected_version: number;
  },
) => write<{ policy: AutoPublishPolicy }>("PATCH", `/subjects/${subjectId}/auto-publish`, input);

export const beginPlatformAuthorization = (
  subjectId: string,
  platformKey: string,
  credentials?: { app_id: string; app_secret: string },
) =>
  post<{ authorization: AuthorizationSession }>(
    `/subjects/${subjectId}/auto-publish/authorizations`,
    {
      platform_key: platformKey,
      ...(credentials ? { credentials } : {}),
    },
  );

export const getPlatformAuthorization = (sessionId: string) =>
  get<{ authorization: AuthorizationSession }>(`/auto-publish/authorizations/${sessionId}`, {
    cache: "no-store",
  });

export const revokePlatformAccount = (subjectId: string, platformKey: string) =>
  remove<{ account: PlatformAccount }>(
    `/subjects/${subjectId}/auto-publish/platforms/${platformKey}/account`,
  );

export const setPlatformParticipation = (
  subjectId: string,
  platformKey: string,
  enabled: boolean,
  expectedVersion: number,
) =>
  write<{ account: PlatformAccount }>(
    "PATCH",
    `/subjects/${subjectId}/auto-publish/platforms/${platformKey}/account`,
    { enabled, expected_version: expectedVersion },
  );

export const createPublicationJob = (subjectId: string, articleId: string) =>
  post<{ job: PublicationJob }>(
    `/subjects/${subjectId}/auto-publish/jobs`,
    { article_id: articleId },
    { "Idempotency-Key": crypto.randomUUID() },
  );

export const getPublicationJob = (jobId: string) =>
  get<{ job: PublicationJob }>(`/auto-publish/jobs/${jobId}`, { cache: "no-store" });

export const approvePublicationJob = (jobId: string) =>
  post<{ job: PublicationJob }>(`/auto-publish/jobs/${jobId}/approve`, {});
