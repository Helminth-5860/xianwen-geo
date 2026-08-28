import { get, post, remove, write } from "./auth-client";

export type PublishingMode = "managed" | "review" | "selected";
export type DistributionStrategy = "smart" | "all" | "custom";
export type ImageStrategy = "customer_only" | "customer_first" | "ai_auto";
export type ImageDensity = "compact" | "standard" | "rich";
export type FrequencyMode = "smart" | "fixed";
export type PlatformAccountStatus =
  | "unlinked"
  | "authorizing"
  | "connected"
  | "expired"
  | "action_required"
  | "suspended";

export type PublishingPreference = Readonly<{
  id: string;
  is_enabled: boolean;
  mode: PublishingMode;
  distribution_strategy: DistributionStrategy;
  custom_platform_keys: string[];
  image_strategy: ImageStrategy;
  image_density: ImageDensity;
  frequency_mode: FrequencyMode;
  posts_per_day: number;
  version: number;
  updated_at: string;
}>;

export type PlatformAccount = Readonly<{
  id: string;
  platform_key: string;
  platform_name: string;
  auth_method: "official_api" | "browser_session";
  status: PlatformAccountStatus;
  display_name: string;
  enabled_for_auto: boolean;
  session_expires_at: string | null;
  last_checked_at: string | null;
  needs_action: boolean;
  updated_at: string;
}>;

export type PublishingPlatform = Readonly<{
  key: string;
  name: string;
  category: "mainstream" | "professional";
  content_types: string[];
  auth_method: "official_api" | "browser_session";
  supports_cover: boolean;
  supports_inline_images: boolean;
  supports_tags: boolean;
  supports_scheduling: boolean;
  supports_public_publish: boolean;
  verification_state: "ready" | "validation";
  authorization_enabled: boolean;
  account: PlatformAccount | null;
}>;

export type PublicationTarget = Readonly<{
  id: string;
  platform_key: string;
  platform_name: string;
  status:
    | "waiting"
    | "ready"
    | "running"
    | "submitted"
    | "succeeded"
    | "failed"
    | "auth_required"
    | "paused";
  scheduled_at: string | null;
  submitted_at?: string | null;
  published_at: string | null;
  management_url?: string;
  public_url: string;
  attempts: number;
  error_message: string;
}>;

export type Publication = Readonly<{
  id: string;
  article_id: string;
  title: string;
  status: "preparing" | "queued" | "running" | "partial" | "succeeded" | "failed" | "cancelled";
  distribution_strategy: DistributionStrategy;
  image_strategy: ImageStrategy;
  scheduled_at: string | null;
  created_at: string;
  targets: PublicationTarget[];
}>;

export type PublishingState = Readonly<{
  subject: Readonly<{ id: string; official_name: string }>;
  preference: PublishingPreference;
  summary: Readonly<{
    platform_count: number;
    connected_count: number;
    needs_action_count: number;
    today_plan_count: number;
    today_published_count: number;
  }>;
  platforms: PublishingPlatform[];
  recent_publications: Publication[];
}>;

export type AuthorizationSession = Readonly<{
  id: string;
  platform_key: string;
  auth_method: "official_api" | "browser_session";
  status: "created" | "starting" | "waiting_user" | "succeeded" | "failed" | "expired";
  action_url: string;
  expires_at: string;
  completed_at: string | null;
  error_message: string;
  one_time_token?: string;
}>;

export const getPublishingState = (subjectId: string) =>
  get<PublishingState>(`/subjects/${subjectId}/publishing`);

export const updatePublishingPreference = (
  subjectId: string,
  input: Partial<Omit<PublishingPreference, "id" | "updated_at">> & { expected_version?: number },
) =>
  write<{ preference: PublishingPreference }>(
    "PATCH",
    `/subjects/${subjectId}/publishing/preferences`,
    input,
  );

export const startPlatformAuthorization = (subjectId: string, platformKey: string) =>
  post<{ authorization: AuthorizationSession }>(
    `/subjects/${subjectId}/publishing/authorization-sessions`,
    { platform_key: platformKey },
  );

export const getAuthorizationSession = (sessionId: string) =>
  get<{ authorization: AuthorizationSession }>(`/publishing/authorization-sessions/${sessionId}`);

export const setPlatformAutoEnabled = (
  subjectId: string,
  platformKey: string,
  enabledForAuto: boolean,
) =>
  write<{ account: PlatformAccount }>(
    "PATCH",
    `/subjects/${subjectId}/publishing/accounts/${platformKey}`,
    { enabled_for_auto: enabledForAuto },
  );

export const disconnectPlatform = (subjectId: string, platformKey: string) =>
  remove<void>(`/subjects/${subjectId}/publishing/accounts/${platformKey}`);

export const createPublication = (
  subjectId: string,
  input: { article_id: string; platform_keys?: string[]; scheduled_at?: string | null },
) => post<{ publication: Publication }>(`/subjects/${subjectId}/publishing/publications`, input);
