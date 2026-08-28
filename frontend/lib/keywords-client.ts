import { get, post, write } from "./auth-client";

export type KeywordStructureType = "short" | "long_tail" | "general";
export type KeywordRegionLevel = "country" | "province" | "city" | "district" | "street" | "custom";
export type LegacyKeywordSearchIntent =
  "informational" | "navigational" | "commercial" | "transactional";
export type KeywordSearchIntent =
  | "informational"
  | "recommendation"
  | "comparison"
  | "transactional"
  | "local"
  | "navigational"
  | "trust"
  | "usage";
export type KeywordPriority = "high" | "medium" | "low";

export type KeywordRegionSelection = Readonly<{
  code: string;
  name: string;
  level: "country" | "province" | "city" | "district" | "street" | "custom";
  path: ReadonlyArray<Readonly<{ code: string; name: string }>>;
}>;

export const keywordBusinessCategoryOptions = [
  { value: "entity", label: "主体/实体" },
  { value: "industry", label: "行业" },
  { value: "product_category", label: "品类" },
  { value: "product", label: "产品" },
  { value: "service", label: "服务" },
  { value: "capability", label: "功能/能力" },
  { value: "goal", label: "需求" },
  { value: "pain_point", label: "痛点/问题" },
  { value: "solution", label: "解决方案" },
  { value: "scenario", label: "场景/用途" },
  { value: "audience", label: "客群/角色" },
  { value: "competitor", label: "竞品/替代" },
  { value: "trust", label: "证据/信任" },
  { value: "knowledge", label: "内容/知识主题" },
] satisfies Array<{ value: string; label: string }>;

export const keywordSearchIntentOptions: Array<{
  value: KeywordSearchIntent;
  label: string;
}> = [
  { value: "informational", label: "信息" },
  { value: "recommendation", label: "商业调查" },
  { value: "comparison", label: "对比" },
  { value: "transactional", label: "交易" },
  { value: "local", label: "本地" },
  { value: "navigational", label: "品牌导航" },
  { value: "trust", label: "信任验证" },
  { value: "usage", label: "售后/使用" },
];

const legacyIntentBySearchIntent: Readonly<Record<KeywordSearchIntent, LegacyKeywordSearchIntent>> =
  {
    informational: "informational",
    recommendation: "commercial",
    comparison: "commercial",
    transactional: "transactional",
    local: "commercial",
    navigational: "navigational",
    trust: "commercial",
    usage: "informational",
  };

export function legacyKeywordSearchIntent(
  values: readonly KeywordSearchIntent[],
): LegacyKeywordSearchIntent | null {
  const first = values[0];
  return first ? legacyIntentBySearchIntent[first] : null;
}

export type KeywordItem = Readonly<{
  id?: string;
  text: string;
  structure_type: KeywordStructureType;
  is_regional: boolean;
  region_level: KeywordRegionLevel | null;
  region_text: string | null;
  regions?: KeywordRegionSelection[];
  base_keyword_text: string | null;
  business_category: string | null;
  search_intent: LegacyKeywordSearchIntent | null;
  search_intents?: KeywordSearchIntent[];
  source?: "legacy" | "manual" | "bulk" | "smart_generation" | "custom_generation";
  notes?: string;
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

const keywordErrorMessages: Readonly<Record<string, string>> = {
  KEYWORD_GENERATION_PROVIDER_TIMEOUT: "AI 关键词生成时间较长，本次未完成，请重新生成。",
  KEYWORD_GENERATION_PROVIDER_RATE_LIMITED: "当前使用人数较多，请稍后重新生成关键词。",
  KEYWORD_GENERATION_PROVIDER_TEMPORARY: "AI 关键词服务暂时不可用，请稍后重新生成。",
  KEYWORD_GENERATION_PROVIDER_REJECTED: "本次关键词未能生成，请调整条件后重新尝试。",
  KEYWORD_GENERATION_INVALID_RESPONSE: "AI 返回内容暂时无法识别，请重新生成。",
  KEYWORD_GENERATION_INTERNAL_ERROR: "关键词生成未完成，请稍后重新尝试。",
  KEYWORD_VALUES_INVALID: "已有关键词数据不完整，请刷新后重新生成。",
  KEYWORD_VERSION_NO_CHANGES: "本次没有生成新的关键词，请调整条件后重新尝试。",
  KEYWORD_VERSION_CONFLICT: "关键词内容已经更新，请刷新后重新尝试。",
  KEYWORD_SUBJECT_VERSION_CONFLICT: "主体资料已经更新，请刷新后重新生成。",
  DISTILLATION_PROVIDER_TIMEOUT: "关键词蒸馏时间较长，本次未完成，请重新尝试。",
  DISTILLATION_PROVIDER_RATE_LIMITED: "当前使用人数较多，请稍后重新蒸馏。",
  DISTILLATION_PROVIDER_TEMPORARY: "关键词蒸馏服务暂时不可用，请稍后重新尝试。",
  DISTILLATION_PROVIDER_REJECTED: "本次关键词蒸馏未能完成，请稍后重新尝试。",
  DISTILLATION_INVALID_RESPONSE: "AI 返回内容暂时无法识别，请重新蒸馏。",
  DISTILLATION_INTERNAL_ERROR: "关键词蒸馏未完成，请稍后重新尝试。",
  DISTILLATION_VERSION_CONFLICT: "蒸馏内容已经更新，请刷新后重新尝试。",
  DISTILLATION_KEYWORD_VERSION_CONFLICT: "关键词已经更新，请重新蒸馏",
};

export function keywordJobErrorMessage(code: string, fallback: string) {
  return keywordErrorMessages[code] ?? fallback;
}

export const keywordJobStatusLabel: Readonly<Record<KeywordGenerationStatus, string>> = {
  queued: "等待生成",
  running: "正在生成",
  retry_wait: "等待再次处理",
  succeeded: "生成完成",
  failed: "生成未完成",
  conflict: "内容已更新",
  superseded: "已由新的生成覆盖",
};

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
    regions: KeywordRegionSelection[];
    generation_mode?: "smart" | "custom";
    categories?: string[];
    intents?: KeywordSearchIntent[];
    region_mode?: "unrestricted" | "subject" | "custom";
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
  regions: KeywordRegionSelection[];
  generationMode: "smart" | "custom";
  categories: string[];
  intents: KeywordSearchIntent[];
  regionMode: "unrestricted" | "subject" | "custom";
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
      regions: item.regions ?? [],
      base_keyword_text: item.base_keyword_text,
      business_category: item.business_category,
      search_intent: item.search_intent,
      search_intents: item.search_intents ?? [],
      source: item.source ?? "legacy",
      notes: item.notes ?? "",
      relevance_score: item.relevance_score,
      priority: item.priority,
      ai_reason: item.ai_reason,
    })),
  });

export type KeywordCandidateInput = Readonly<{
  text: string;
  category: string;
  intents: KeywordSearchIntent[];
  lengthType: "short" | "long_tail";
  regions: KeywordRegionSelection[];
  notes: string;
}>;

export const appendKeywordCandidates = (
  subjectId: string,
  input: {
    expectedVersion: number;
    expectedSubjectVersionId: string;
    source: "manual" | "bulk";
    items: KeywordCandidateInput[];
  },
) =>
  post<{
    added_count: number;
    skipped_duplicates: string[];
    candidate_pool: KeywordDraftState;
  }>(`/subjects/${subjectId}/keywords/candidates`, {
    expected_version: input.expectedVersion,
    expected_subject_version_id: input.expectedSubjectVersionId,
    source: input.source,
    items: input.items.map((item) => ({
      text: item.text,
      category: item.category,
      intents: item.intents,
      length_type: item.lengthType,
      regions: item.regions,
      notes: item.notes,
    })),
  });

export type KeywordAsset = Readonly<{
  id: string;
  text: string;
  source_text: string;
  related_keywords: string[];
  audiences: string[];
  scenarios: string[];
  category: string | null;
  intents: KeywordSearchIntent[];
  regions: KeywordRegionSelection[];
  source: string;
  enabled: boolean;
  usable_for_questions: boolean;
  deleted: boolean;
  updated_at: string;
}>;

export const getKeywordAssets = (subjectId: string) =>
  get<{ items: KeywordAsset[] }>(`/subjects/${subjectId}/keyword-assets`);

export const updateKeywordAsset = (
  subjectId: string,
  keywordId: string,
  patch: {
    displayText?: string;
    category?: string;
    intents?: KeywordSearchIntent[];
    regions?: KeywordRegionSelection[];
    enabled?: boolean;
    usableForQuestions?: boolean;
    deleted?: boolean;
  },
) =>
  write<KeywordAsset>("PATCH", `/subjects/${subjectId}/keyword-assets/${keywordId}`, {
    ...(patch.displayText === undefined ? {} : { display_text: patch.displayText }),
    ...(patch.category === undefined ? {} : { category: patch.category }),
    ...(patch.intents === undefined ? {} : { intents: patch.intents }),
    ...(patch.regions === undefined ? {} : { regions: patch.regions }),
    ...(patch.enabled === undefined ? {} : { enabled: patch.enabled }),
    ...(patch.usableForQuestions === undefined
      ? {}
      : { usable_for_questions: patch.usableForQuestions }),
    ...(patch.deleted === undefined ? {} : { deleted: patch.deleted }),
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
      generation_mode: input.generationMode,
      categories: input.categories,
      intents: input.intents,
      region_mode: input.regionMode,
      regenerate: input.regenerate,
    },
    { "Idempotency-Key": idempotencyKey },
  );

export const getKeywordGenerationJob = (jobId: string) =>
  get<KeywordGenerationJob>(`/keyword-jobs/${jobId}`);

export type DistillationAction = "keep" | "merge" | "delete" | "low_value";
export type DistillationStatus =
  "queued" | "running" | "retry_wait" | "succeeded" | "failed" | "conflict" | "superseded";

export const distillationJobStatusLabel: Readonly<Record<DistillationStatus, string>> = {
  queued: "等待蒸馏",
  running: "正在蒸馏",
  retry_wait: "等待再次处理",
  succeeded: "蒸馏完成",
  failed: "蒸馏未完成",
  conflict: "内容已更新",
  superseded: "已由新的蒸馏覆盖",
};

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
  pending_item_count: number;
  pending_items: DistillationSourceKeyword[];
  has_unconfirmed_result: boolean;
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
