import { get, post, remove } from "./auth-client";

export type PublicationVerificationStatus = "published" | "failed" | "unknown";

export type PublicationVerificationCheck = Readonly<{
  id: string;
  subject_id: string;
  requested_url: string;
  final_url: string;
  hostname: string;
  status: PublicationVerificationStatus;
  page_title: string;
  http_status: number | null;
  response_time_ms: number | null;
  result_message: string;
  safe_failure_code: string;
  checked_at: string;
}>;

export type PublicationVerificationStats = Readonly<{
  total: number;
  published: number;
  failed: number;
  unknown: number;
  success_rate: number;
}>;

export type PublicationVerificationPage = Readonly<{
  items: PublicationVerificationCheck[];
  pagination: {
    page: number;
    page_size: number;
    count: number;
    total_pages: number;
  };
  stats: PublicationVerificationStats;
}>;

export const verifyPublicationUrl = (subjectId: string, url: string) =>
  post<PublicationVerificationCheck>(`/subjects/${subjectId}/publication-verifications`, { url });

export const getPublicationVerifications = (
  subjectId: string,
  page = 1,
  pageSize = 10,
  status: PublicationVerificationStatus | "all" = "all",
) => {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (status !== "all") params.set("status", status);
  return get<PublicationVerificationPage>(
    `/subjects/${subjectId}/publication-verifications?${params.toString()}`,
  );
};

export const deletePublicationVerification = (subjectId: string, checkId: string) =>
  remove<{ deleted: true; id: string }>(
    `/subjects/${subjectId}/publication-verifications/${checkId}`,
  );

export const bulkDeletePublicationVerifications = (subjectId: string, ids: string[]) =>
  post<{ deleted: number }>(
    `/subjects/${subjectId}/publication-verifications/bulk-delete`,
    { ids },
  );
