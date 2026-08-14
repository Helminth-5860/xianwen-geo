import { get, post } from "./auth-client";

export type WebSourceImport = Readonly<{
  id: string;
  subject_id: string;
  display_url: string;
  has_query: boolean;
  status: "queued" | "fetching" | "retry_wait" | "succeeded" | "failed";
  stable_error_code: string;
  version: number;
  latest_version: Readonly<{
    id: string;
    version_no: number;
    canonical_text: string;
  }> | null;
  current_confirmed_version: Readonly<{ id: string; version_no: number }> | null;
  created_at: string;
  updated_at: string;
}>;

export const listWebSources = (subjectId: string) =>
  get<{ results: WebSourceImport[] }>(`/subjects/${subjectId}/web-sources`);

export const getWebSource = (id: string) => get<WebSourceImport>(`/web-sources/${id}`);

export const importWebSource = (subjectId: string, url: string) =>
  post<WebSourceImport>(
    "/web-sources/import",
    { subject_id: subjectId, url },
    { "Idempotency-Key": crypto.randomUUID() },
  );

export const confirmWebSource = (
  source: WebSourceImport,
  sourceParsedVersionId: string,
  confirmedText: string,
) =>
  post<{
    version: number;
    confirmed_version: { id: string; version_no: number };
    created: boolean;
  }>(`/web-sources/${source.id}/confirm`, {
    expected_version: source.version,
    source_parsed_version_id: sourceParsedVersionId,
    confirmed_text: confirmedText,
  });
