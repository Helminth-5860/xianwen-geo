export type StoredCookie = Readonly<{
  name: string;
  value: string;
  domain: string;
  path: string;
  expires?: number;
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: "Strict" | "Lax" | "None";
}>;

export type PlatformCredentials = Readonly<{
  cookies?: StoredCookie[];
  access_token?: string;
  refresh_token?: string;
  app_id?: string;
  app_secret?: string;
}>;

export type PublicationAsset = Readonly<{
  role: "cover" | "inline" | "information";
  url: string;
  alt?: string;
}>;

export type PublicationInput = Readonly<{
  targetId: string;
  title: string;
  contentHtml: string;
  contentText: string;
  summary?: string;
  tags: string[];
  assets: PublicationAsset[];
  credentials: PlatformCredentials;
  publishMode: "draft" | "public";
}>;

export type PublicationResult = Readonly<{
  success: boolean;
  platformKey: string;
  status: "drafted" | "published" | "failed" | "auth_required" | "action_required";
  externalPostId?: string;
  publicUrl?: string;
  editUrl?: string;
  safeErrorCode?: string;
}>;

export interface PlatformPublisher {
  readonly platformKey: string;
  readonly verifiedCapabilities: readonly ("auth" | "draft" | "public_publish" | "image_upload")[];
  checkAuth(credentials: PlatformCredentials): Promise<{ ok: boolean; displayName?: string; externalAccountId?: string }>;
  publish(input: PublicationInput): Promise<PublicationResult>;
}
