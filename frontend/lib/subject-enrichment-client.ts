import { get, post } from "./auth-client";
import type { SubjectDetail } from "./subjects-client";

export type EnrichmentSource = Readonly<{
  source_type: "document" | "web";
  parsed_version_id: string;
  label: string;
  version_no: number;
  character_count: number;
}>;

export type EnrichmentTarget = Readonly<{
  field_key: string;
  label: string;
  field_type: string;
  current_value: unknown;
}>;

export type EnrichmentSuggestion = Readonly<{
  id: string;
  field_key: string;
  suggested_value: unknown;
  confidence: "high" | "medium" | "low";
  conflict: boolean;
  conflict_code: string;
  sources: ReadonlyArray<{ source_id: string; source_type: "document" | "web" }>;
}>;

export type EnrichmentJob = Readonly<{
  id: string;
  subject_id: string;
  status: "queued" | "running" | "retry_wait" | "succeeded" | "failed";
  version: number;
  stable_error_code: string;
  provider_key: "mock" | "unavailable";
  model_key: string;
  suggestions: EnrichmentSuggestion[];
  applied: boolean;
  created_at: string;
  updated_at: string;
}>;

export type EnrichmentSourcesResponse = Readonly<{
  sources: EnrichmentSource[];
  target_fields: EnrichmentTarget[];
  latest_job: EnrichmentJob | null;
}>;

export const getEnrichmentSources = (subjectId: string) =>
  get<EnrichmentSourcesResponse>(`/subjects/${subjectId}/ai-enrichment/sources`);

export const getEnrichmentJob = (subjectId: string, jobId: string) =>
  get<EnrichmentJob>(`/subjects/${subjectId}/ai-enrichment/${jobId}`);

export const createEnrichment = (
  subjectId: string,
  expectedSubjectVersion: number,
  sources: EnrichmentSource[],
  targetFieldKeys: string[],
) =>
  post<EnrichmentJob>(
    `/subjects/${subjectId}/ai-enrichment`,
    {
      expected_subject_version: expectedSubjectVersion,
      sources: sources.map((source) => ({
        source_type: source.source_type,
        parsed_version_id: source.parsed_version_id,
      })),
      target_field_keys: targetFieldKeys,
    },
    { "Idempotency-Key": crypto.randomUUID() + crypto.randomUUID() },
  );

export const confirmEnrichment = (
  subjectId: string,
  job: EnrichmentJob,
  expectedSubjectVersion: number,
  decisions: ReadonlyArray<{ suggestion_id: string; accepted: boolean }>,
) =>
  post<{ created: boolean; confirmation_id: string; subject: SubjectDetail }>(
    `/subjects/${subjectId}/ai-enrichment/${job.id}/confirm`,
    {
      expected_subject_version: expectedSubjectVersion,
      expected_job_version: job.version,
      decisions,
    },
  );
