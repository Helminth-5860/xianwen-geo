import { get, post, type PageData, write } from "./auth-client";

export type SubjectRiskType = Readonly<{
  id: string;
  key: string;
  name: string;
  description: string;
  enabled: boolean;
  manual_review_required: boolean;
  allow_geo_detection: boolean;
  allow_article_generation: boolean;
  allow_image_generation: boolean;
  require_authoritative_citations: boolean;
  require_disclaimer: boolean;
  sort_order: number;
  version: number;
}>;

export type SubjectRiskRule = Readonly<{
  id: string;
  key: string;
  risk_type: string;
  risk_type_key: string;
  subject_type: string | null;
  subject_type_key: string | null;
  field_key: string;
  operator: "equals_any" | "contains_any";
  patterns: string[];
  reason_type:
    "suspected_violation" | "suspected_impersonation" | "data_conflict" | "high_risk_industry";
  enabled: boolean;
  priority: number;
  version: number;
}>;

export type SubjectRiskCatalog = Readonly<{
  version: number;
  published_revision: null | {
    id: string;
    revision_no: number;
    draft_version: number;
    format_version: number;
    snapshot_digest: string;
    created_at: string;
  };
}>;

export type SubjectReview = Readonly<{
  id: string;
  user_id: string;
  subject_id: string;
  subject_version_id: string;
  version_no: number;
  official_name: string;
  status: "pending" | "approved" | "rejected" | "superseded";
  reason_types: string[];
  review_evidence: ReadonlyArray<{
    risk_type_key: string;
    rule_key: string;
    reason_type: string;
    field_key: string;
  }>;
  public_reason: string;
  internal_note: string;
  version: number;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}>;

export const getSubjectRiskCatalog = () => get<SubjectRiskCatalog>("/admin/subject-risk-catalog");

export const getSubjectRiskTypes = () =>
  get<{ catalog_version: number; risk_types: SubjectRiskType[] }>("/admin/subject-risk-types");

export const getSubjectRiskRules = () =>
  get<{ catalog_version: number; rules: SubjectRiskRule[] }>("/admin/subject-risk-rules");

export const createSubjectRiskType = (
  expectedCatalogVersion: number,
  input: Omit<SubjectRiskType, "id" | "version">,
) =>
  post<SubjectRiskType>("/admin/subject-risk-types", {
    expected_catalog_version: expectedCatalogVersion,
    ...input,
  });

export const createSubjectRiskRule = (
  expectedCatalogVersion: number,
  input: Omit<SubjectRiskRule, "id" | "version" | "risk_type_key" | "subject_type_key">,
) =>
  post<SubjectRiskRule>("/admin/subject-risk-rules", {
    expected_catalog_version: expectedCatalogVersion,
    ...input,
  });

export const updateSubjectRiskType = (
  item: SubjectRiskType,
  expectedCatalogVersion: number,
  input: Partial<Omit<SubjectRiskType, "id" | "key" | "version">>,
) =>
  write<SubjectRiskType>("PATCH", `/admin/subject-risk-types/${item.id}`, {
    expected_catalog_version: expectedCatalogVersion,
    expected_version: item.version,
    ...input,
  });

export const updateSubjectRiskRule = (
  item: SubjectRiskRule,
  expectedCatalogVersion: number,
  input: Partial<
    Omit<SubjectRiskRule, "id" | "key" | "version" | "risk_type_key" | "subject_type_key">
  >,
) =>
  write<SubjectRiskRule>("PATCH", `/admin/subject-risk-rules/${item.id}`, {
    expected_catalog_version: expectedCatalogVersion,
    expected_version: item.version,
    ...input,
  });

export const publishSubjectRiskCatalog = (expectedCatalogVersion: number) =>
  post<{ catalog_version: number; revision_id: string; revision_no: number }>(
    "/admin/subject-risk-catalog/publish",
    {
      expected_catalog_version: expectedCatalogVersion,
      confirmed: true,
    },
  );

export const getSubjectReviews = (page = 1, status = "") => {
  const query = new URLSearchParams({ page: String(page) });
  if (status) query.set("status", status);
  return get<PageData<SubjectReview>>(`/admin/subject-reviews?${query.toString()}`);
};

export const getSubjectReview = (id: string) => get<SubjectReview>(`/admin/subject-reviews/${id}`);

export const approveSubjectReview = (item: SubjectReview, publicReason = "", internalNote = "") =>
  post<SubjectReview>(`/admin/subject-reviews/${item.id}/approve`, {
    expected_version: item.version,
    public_reason: publicReason,
    internal_note: internalNote,
  });

export const rejectSubjectReview = (item: SubjectReview, publicReason: string, internalNote = "") =>
  post<SubjectReview>(`/admin/subject-reviews/${item.id}/reject`, {
    expected_version: item.version,
    public_reason: publicReason,
    internal_note: internalNote,
  });
