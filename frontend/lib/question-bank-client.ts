import { get, post, write } from "./auth-client";

export type QuestionPriority = "high" | "medium" | "low";
export type QuestionType = "natural" | "brand_directed";
export type QuestionGenerationStatus =
  "queued" | "running" | "retry_wait" | "succeeded" | "failed" | "conflict" | "superseded";

const questionGenerationErrorMessages: Readonly<Record<string, string>> = {
  QUESTION_GENERATION_PROVIDER_UNAVAILABLE: "问题生成服务暂未启用，请联系管理员配置后再试",
  QUESTION_GENERATION_INVALID_RESPONSE: "AI 返回格式异常，请重新生成。",
  QUESTION_GENERATION_PROVIDER_ERROR: "问题生成服务暂时不可用，请稍后重试",
  QUESTION_GENERATION_INTERNAL_ERROR: "问题生成服务暂时不可用，请稍后重试",
  QUESTION_GENERATION_IN_PROGRESS: "已有问题生成任务正在处理中，请稍候",
  QUESTION_GENERATION_PROVIDER_TIMEOUT: "问题生成服务响应超时，请稍后重试",
  QUESTION_GENERATION_PROVIDER_RATE_LIMITED: "问题生成请求较多，请稍后重试",
  QUESTION_GENERATION_PROVIDER_TEMPORARY: "问题生成服务暂时不可用，请稍后重试",
  QUESTION_GENERATION_PROVIDER_REJECTED: "问题生成服务未接受本次请求，请稍后重试",
  QUESTION_GENERATION_IDEMPOTENCY_CONFLICT: "请求信息已经变化，请刷新页面后重试",
};

export function questionGenerationErrorMessage(
  code: string | null | undefined,
  fallback = "问题库生成失败，请稍后重试",
) {
  return (code && questionGenerationErrorMessages[code]) || fallback;
}

export type QuestionCatalogOption = Readonly<{
  id: string;
  key: string;
  name: string;
  version: number;
  guidance?: string;
}>;

export type QuestionDraftItem = Readonly<{
  id: string;
  text: string;
  primary_category: Pick<QuestionCatalogOption, "id" | "key" | "name">;
  tag_ids: string[];
  keyword_ids: string[];
  priority: QuestionPriority;
  question_type: QuestionType;
  participates_in_scoring: boolean;
  ai_reason: string;
  sort_order: number;
}>;

export type QuestionBankDraft = Readonly<{
  version: number;
  can_write: boolean;
  read_only_reason: string | null;
  question_limit: number | null;
  catalog: {
    categories: QuestionCatalogOption[];
    tags: QuestionCatalogOption[];
  };
  current_distillation_set: {
    id: string;
    version_no: number;
    item_count: number;
  } | null;
  draft_input: {
    subject_version_id: string;
    distillation_set_id: string;
    distillation_version_no: number;
  } | null;
  source_result_id: string | null;
  current_question_bank_version_no: number | null;
  items: QuestionDraftItem[];
}>;

export type QuestionGenerationJob = Readonly<{
  id: string;
  subject_id: string;
  subject_version_id: string;
  distillation_set_id: string;
  status: QuestionGenerationStatus;
  version: number;
  stable_error_code: string;
  question_limit: number;
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

export type QuestionBankVersionItem = Readonly<{
  id: string;
  text: string;
  priority: QuestionPriority;
  question_type: QuestionType;
  participates_in_scoring: boolean;
  ai_reason: string;
  sort_order: number;
}>;

export type QuestionBankVersion = Readonly<{
  id: string;
  version_no: number;
  subject_version_id: string;
  distillation_set_id: string;
  source_result_id: string | null;
  item_count: number;
  confirmed_at: string;
  items?: ReadonlyArray<QuestionBankVersionItem>;
}>;

export const getQuestionBankDraft = (subjectId: string) =>
  get<QuestionBankDraft>(`/subjects/${subjectId}/question-banks/draft`);

export const createQuestionGeneration = (
  subjectId: string,
  input: {
    distillationSetId: string;
    expectedWorkspaceVersion: number;
    regenerate: boolean;
  },
  idempotencyKey: string,
) =>
  post<QuestionGenerationJob>(
    `/subjects/${subjectId}/question-banks/generate`,
    {
      distillation_set_id: input.distillationSetId,
      expected_workspace_version: input.expectedWorkspaceVersion,
      regenerate: input.regenerate,
    },
    { "Idempotency-Key": idempotencyKey },
  );

export const getQuestionGenerationJob = (jobId: string) =>
  get<QuestionGenerationJob>(`/question-bank-jobs/${jobId}`);

export const saveQuestionBankDraft = (
  subjectId: string,
  expectedVersion: number,
  items: QuestionDraftItem[],
) =>
  write<QuestionBankDraft>("PATCH", `/subjects/${subjectId}/question-banks/draft`, {
    expected_version: expectedVersion,
    items: items.map((item) => ({
      text: item.text,
      primary_category_id: item.primary_category.id,
      tag_ids: item.tag_ids,
      keyword_ids: item.keyword_ids,
      priority: item.priority,
      question_type: item.question_type,
      participates_in_scoring: item.participates_in_scoring,
      ai_reason: item.ai_reason,
    })),
  });

export const confirmQuestionBank = (subjectId: string, expectedVersion: number) =>
  post<{ version: QuestionBankVersion }>(`/subjects/${subjectId}/question-banks/confirm`, {
    expected_version: expectedVersion,
  });

export const getQuestionBankVersions = (subjectId: string) =>
  get<{ versions: QuestionBankVersion[] }>(`/subjects/${subjectId}/question-banks/versions`);

export const getCurrentQuestionBank = (subjectId: string) =>
  get<QuestionBankVersion>(`/subjects/${subjectId}/question-banks/current`);
