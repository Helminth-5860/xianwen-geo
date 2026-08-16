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

export type DistillationAction = "keep" | "merge" | "delete" | "low_value";
export type DistillationStatus =
  "queued" | "running" | "retry_wait" | "succeeded" | "failed" | "conflict" | "superseded";

export type DistillationSourceKeyword = Readonly<{
  id: string;
  text: string;
  structure_type: KeywordStructureType;
  is_regional: boolean;
  region_level: KeywordRegionLevel | null;
  region_text: string | null;
  sort_order: number;
}>;

export type DistillationDraftItem = Readonly<{
  source_keyword: DistillationSourceKeyword;
  action: DistillationAction;
  canonical_keyword_id: string | null;
  merge_group_key: string | null;
  ai_action: DistillationAction;
  ai_canonical_keyword_id: string | null;
  ai_merge_group_key: string | null;
  ai_reason: string;
  user_reason: string;
  user_overridden: boolean;
  sort_order: number;
}>;

export type DistillationDraftState = Readonly<{
  version: number;
  can_write: boolean;
  read_only_reason: string | null;
  current_keyword_set_version: {
    id: string;
    version_no: number;
    item_count: number;
  } | null;
  draft_input_version: {
    id: string;
    version_no: number;
    item_count: number;
  } | null;
  source_result_id: string | null;
  current_distillation_version_no: number | null;
  items: DistillationDraftItem[];
}>;

export type DistillationVersion = Readonly<{
  id: string;
  version_no: number;
  subject_version_id: string;
  keyword_set_version_id: string;
  source_result_id: string;
  item_count: number;
  confirmed_at: string;
  items: DistillationDraftItem[];
}>;

export type DistillationJob = Readonly<{
  id: string;
  subject_id: string;
  subject_version_id: string;
  keyword_set_version_id: string;
  status: DistillationStatus;
  version: number;
  stable_error_code: string;
  billing: {
    billing_mode: "free_initial" | "regeneration";
    held: boolean;
    remaining: number | null;
  };
  provenance: {
    provider_key: string;
    model_key: string;
    adapter_version: string;
    prompt_version: string;
  };
  result: { item_count: number; applied_workspace_version: number } | null;
  attempts: number;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}>;

export const createDistillation = (
  subjectId: string,
  input: {
    keywordSetVersionId: string;
    expectedWorkspaceVersion: number;
    regenerate: boolean;
  },
  idempotencyKey: string,
) =>
  post<DistillationJob>(
    `/subjects/${subjectId}/distillations`,
    {
      keyword_set_version_id: input.keywordSetVersionId,
      expected_workspace_version: input.expectedWorkspaceVersion,
      regenerate: input.regenerate,
    },
    { "Idempotency-Key": idempotencyKey },
  );

export const getDistillationJob = (jobId: string) =>
  get<DistillationJob>(`/distillation-jobs/${jobId}`);

export const getDistillationDraft = (subjectId: string) =>
  get<DistillationDraftState>(`/subjects/${subjectId}/distillations/draft`);

export const saveDistillationDraft = (
  subjectId: string,
  expectedVersion: number,
  items: DistillationDraftItem[],
) =>
  write<DistillationDraftState>("PATCH", `/subjects/${subjectId}/distillations/draft`, {
    expected_version: expectedVersion,
    items: items.map((item) => ({
      source_keyword_id: item.source_keyword.id,
      action: item.action,
      canonical_keyword_id: item.canonical_keyword_id,
      merge_group_key: item.merge_group_key,
      user_reason: item.user_reason,
    })),
  });

export const confirmDistillation = (subjectId: string, expectedVersion: number) =>
  post<{ version: DistillationVersion }>(`/subjects/${subjectId}/distillations/confirm`, {
    expected_version: expectedVersion,
  });

export const getCurrentDistillation = (subjectId: string) =>
  get<DistillationVersion>(`/subjects/${subjectId}/distillations/current`);
