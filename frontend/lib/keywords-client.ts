import { get, post, write } from "./auth-client";

export type KeywordStructureType = "short" | "long_tail" | "general";
export type KeywordRegionLevel = "country" | "province" | "city" | "district" | "custom";
export type KeywordSearchIntent = "informational" | "navigational" | "commercial" | "transactional";
export type KeywordPriority = "high" | "medium" | "low";

export type KeywordItem = Readonly<{
  id?: string;
  text: string;
  structure_type: KeywordStructureType;
  is_regional: boolean;
  region_level: KeywordRegionLevel | null;
  region_text: string | null;
  base_keyword_text: string | null;
  business_category: string | null;
  search_intent: KeywordSearchIntent | null;
  relevance_score: number | null;
  priority: KeywordPriority | null;
  ai_reason: string | null;
  sort_order: number;
}>;

export type KeywordSubjectVersion = Readonly<{
  id: string;
  version_no: number;
  official_name: string;
}>;

export type KeywordDraftState = Readonly<{
  version: number;
  subject_version: KeywordSubjectVersion | null;
  draft_subject_version: KeywordSubjectVersion | null;
  current_keyword_version_no: number | null;
  can_write: boolean;
  read_only_reason: string | null;
  items: KeywordItem[];
}>;

export type KeywordVersion = Readonly<{
  id: string;
  version_no: number;
  subject_version: KeywordSubjectVersion;
  item_count: number;
  created_at: string;
  items?: KeywordItem[];
}>;

export type KeywordGenerationStatus =
  "queued" | "running" | "retry_wait" | "succeeded" | "failed" | "conflict" | "superseded";

export type KeywordGenerationJob = Readonly<{
  id: string;
  subject_id: string;
  subject_version_id: string;
  status: KeywordGenerationStatus;
  version: number;
  stable_error_code: string;
  billing: {
    billing_mode: "free_initial" | "regeneration";
    held: boolean;
    remaining: number | null;
  };
  configuration: {
    target_count: number;
    include_short: boolean;
    include_long_tail: boolean;
    include_regional: boolean;
    regions: string[];
  };
  provenance: {
    provider_key: string;
    model_key: string;
    adapter_version: string;
    prompt_version: string;
  };
  result: {
    item_count: number;
    applied_keyword_set_version: number;
  } | null;
  attempts: number;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}>;

export type KeywordGenerationInput = Readonly<{
  expectedSubjectVersionId: string;
  expectedKeywordSetVersion: number;
  targetCount: number;
  includeShort: boolean;
  includeLongTail: boolean;
  includeRegional: boolean;
  regions: string[];
  regenerate: boolean;
}>;

export const getKeywordDraft = (subjectId: string) =>
  get<KeywordDraftState>(`/subjects/${subjectId}/keywords/draft`);

export const saveKeywordDraft = (
  subjectId: string,
  input: {
    expectedVersion: number;
    expectedSubjectVersionId: string;
    items: KeywordItem[];
  },
) =>
  write<KeywordDraftState>("PATCH", `/subjects/${subjectId}/keywords/draft`, {
    expected_version: input.expectedVersion,
    expected_subject_version_id: input.expectedSubjectVersionId,
    items: input.items.map((item) => ({
      id: item.id,
      text: item.text,
      structure_type: item.structure_type,
      is_regional: item.is_regional,
      region_level: item.region_level ?? "",
      region_text: item.region_text ?? "",
      base_keyword_text: item.base_keyword_text,
      business_category: item.business_category,
      search_intent: item.search_intent,
      relevance_score: item.relevance_score,
      priority: item.priority,
      ai_reason: item.ai_reason,
    })),
  });

export const commitKeywords = (
  subjectId: string,
  expectedVersion: number,
  expectedSubjectVersionId: string,
) =>
  post<{ version: KeywordVersion }>(`/subjects/${subjectId}/keywords/commit`, {
    expected_version: expectedVersion,
    expected_subject_version_id: expectedSubjectVersionId,
  });

export const getKeywordVersions = (subjectId: string) =>
  get<{ versions: KeywordVersion[] }>(`/subjects/${subjectId}/keywords/versions`);

export const getKeywordVersion = (subjectId: string, versionId: string) =>
  get<KeywordVersion>(`/subjects/${subjectId}/keywords/versions/${versionId}`);

export const createKeywordGeneration = (
  subjectId: string,
  input: KeywordGenerationInput,
  idempotencyKey: string,
) =>
  post<KeywordGenerationJob>(
    `/subjects/${subjectId}/keywords/generate`,
    {
      expected_subject_version_id: input.expectedSubjectVersionId,
      expected_keyword_set_version: input.expectedKeywordSetVersion,
      target_count: input.targetCount,
      include_short: input.includeShort,
      include_long_tail: input.includeLongTail,
      include_regional: input.includeRegional,
      regions: input.regions,
      regenerate: input.regenerate,
    },
    { "Idempotency-Key": idempotencyKey },
  );

export const getKeywordGenerationJob = (jobId: string) =>
  get<KeywordGenerationJob>(`/keyword-jobs/${jobId}`);
