import { get, post, remove, write } from "./auth-client";

export type WhiteLabel = Readonly<{
  enabled: boolean;
  uses_default_brand: boolean;
  config: {
    brand_name: string;
    logo_document_version_id: string | null;
    cover_document_version_id: string | null;
    primary_color: string;
    header_text: string;
    footer_text: string;
    contact: string;
    statement: string;
    version: number;
  } | null;
  effective_brand: { brand_name: string; white_label: boolean; primary_color: string };
}>;

export type ReportShare = Readonly<{
  id: string;
  report_id: string;
  subject_id: string;
  password_required: boolean;
  expires_at: string | null;
  closed_at: string | null;
  status: "active" | "expired" | "closed";
  access_count: number;
  last_accessed_at: string | null;
  created_at: string;
  url?: string;
}>;

export const getWhiteLabel = (subjectId: string) =>
  get<WhiteLabel>(`/subjects/${subjectId}/white-label`);

export const saveWhiteLabel = (
  subjectId: string,
  input: {
    brand_name: string;
    primary_color: string;
    header_text: string;
    footer_text: string;
    contact: string;
    statement: string;
    expected_version: number;
  },
) =>
  write<WhiteLabel>("PUT", `/subjects/${subjectId}/white-label`, {
    ...input,
    logo_document_version_id: null,
    cover_document_version_id: null,
  });

export const getReportShares = (reportId: string) =>
  get<{ items: ReportShare[] }>(`/geo/reports/${reportId}/shares`);

export const createReportShare = (reportId: string, password: string, expiresInDays: number) =>
  post<ReportShare>(`/geo/reports/${reportId}/shares`, {
    password,
    expires_in_days: expiresInDays,
  });

export const closeReportShare = (shareId: string) =>
  remove<ReportShare>(`/report-shares/${shareId}`);
