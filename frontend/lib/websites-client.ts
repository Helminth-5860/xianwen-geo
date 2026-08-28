import { get, post } from "./auth-client";

export type WebsiteStyleKey = "professional" | "technology" | "premium";
export type WebsiteProjectStatus = "draft" | "generating" | "ready" | "failed";
export type WebsiteJobStatus = "queued" | "running" | "succeeded" | "failed";

export type WebsiteItem = Readonly<{ title: string; body: string }>;
export type WebsiteSection = Readonly<{
  type: "hero" | "text" | "cards" | "faq" | "contact";
  title: string;
  body: string;
  items: WebsiteItem[];
}>;
export type WebsitePage = Readonly<{
  key: "home" | "about" | "services" | "solutions" | "faq" | "contact";
  slug: string;
  title: string;
  seo_title: string;
  seo_description: string;
  sections: WebsiteSection[];
}>;
export type WebsiteSite = Readonly<{
  schema_version: 1;
  tagline: string;
  pages: WebsitePage[];
}>;

export type WebsiteContact = Readonly<{
  brand_name?: string;
  primary_business?: string;
  business_address?: string;
  contact_name?: string;
  contact_phone?: string;
}>;

export type WebsiteProject = Readonly<{
  id: string;
  subject_id: string;
  subject_version_id: string;
  style_key: WebsiteStyleKey;
  style_name: string;
  status: WebsiteProjectStatus;
  selected_asset_ids: string[];
  selected_document_ids: string[];
  site_schema_version: number;
  site: WebsiteSite | null;
  contact: WebsiteContact;
  generation_count: number;
  error_message: string;
  version: number;
  created_at: string;
  updated_at: string;
}>;

export type WebsiteJob = Readonly<{
  id: string;
  project_id: string;
  status: WebsiteJobStatus;
  error_message: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}>;

export type WebsiteReadiness = Readonly<{
  can_generate: boolean;
  subject_ready: boolean;
  product_count: number;
  keyword_count: number;
  question_count: number;
  image_count: number;
  library_image_count: number;
  uploaded_image_count: number;
}>;

export type WebsiteState = Readonly<{
  subject: Readonly<{ id: string; official_name: string }>;
  readiness: WebsiteReadiness;
  project: WebsiteProject | null;
  latest_job: WebsiteJob | null;
}>;

export const getWebsiteState = (subjectId: string) =>
  get<WebsiteState>(`/subjects/${subjectId}/website`);

export const getWebsiteJob = (jobId: string) =>
  get<{ job: WebsiteJob; project: WebsiteProject }>(`/website-jobs/${jobId}`);

export const getWebsiteDocumentUrl = (documentId: string) =>
  post<{ url: string; expires_in: number }>(`/documents/${documentId}/download-intents`, {});

export function generateWebsite(
  subjectId: string,
  input: {
    style_key: WebsiteStyleKey;
    image_asset_ids: string[];
    document_ids: string[];
  },
) {
  return post<{ project: WebsiteProject; job: WebsiteJob }>(
    `/subjects/${subjectId}/website/generate`,
    input,
    { "Idempotency-Key": crypto.randomUUID() },
  );
}
