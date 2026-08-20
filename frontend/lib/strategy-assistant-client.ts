import { get, post, write } from "./auth-client";

export type StrategyPeriod = "7d" | "30d" | "90d" | "custom";

export type StrategyBody = Readonly<{
  overview: string;
  priorities: ReadonlyArray<{
    title: string;
    rationale: string;
    actions: string[];
    success_metric: string;
  }>;
  schedule: ReadonlyArray<{ phase: string; focus: string; actions: string[] }>;
  article_topics: ReadonlyArray<{ title: string; reason: string; route: string }>;
}>;

export type Strategy = Readonly<{
  id: string;
  report_id: string;
  subject_id: string;
  subject_version_id: string;
  period: StrategyPeriod;
  period_days: number;
  status: "queued" | "running" | "succeeded" | "failed";
  billing: {
    mode: "free_initial" | "regeneration";
    first_free: boolean;
    held: boolean;
    remaining: number | null;
  };
  body: StrategyBody | null;
  note: { text: string; version: number; updated_at: string } | null;
  provenance: {
    provider_key: string;
    model_key: string;
    provider_model_id: string;
    adapter_version: string;
    prompt_version: string;
    schema_version: string;
    report_scoring_rule_version: string;
  };
  safe_error_code: string;
  created_at: string;
  generated_at: string | null;
  finished_at: string | null;
}>;

export type StrategyList = Readonly<{
  items: Strategy[];
  first_free_available: boolean;
  remaining_regenerations: number | null;
}>;

export const getStrategies = (reportId: string) =>
  get<StrategyList>(`/geo/reports/${reportId}/strategies`);

export const getStrategy = (strategyId: string) => get<Strategy>(`/strategy-jobs/${strategyId}`);

export const createStrategy = (
  reportId: string,
  input: {
    period: StrategyPeriod;
    custom_days?: number;
    regenerate: boolean;
  },
  idempotencyKey: string,
) =>
  post<Strategy>(`/geo/reports/${reportId}/strategies`, input, {
    "Idempotency-Key": idempotencyKey,
  });

export const saveStrategyNote = (strategyId: string, text: string, expectedVersion: number) =>
  write<{ text: string; version: number; updated_at: string }>(
    "PUT",
    `/strategies/${strategyId}/note`,
    { text, expected_version: expectedVersion },
  );

export type AssistantContext = Readonly<{
  current_subject: { id: string; version_id: string; name: string } | null;
  remaining_messages: number | null;
}>;

export type AssistantMessage = Readonly<{ role: "user" | "assistant"; content: string }>;

export type AssistantReply = Readonly<{
  answer: string;
  suggested_actions: ReadonlyArray<{ label: string; route: string }>;
  remaining_messages: number;
  usage_event_id: string;
  history_persisted: false;
}>;

export const getAssistantContext = () => get<AssistantContext>("/assistant/context");

export const askAssistant = (
  subjectId: string,
  messages: AssistantMessage[],
  idempotencyKey: string,
) =>
  post<AssistantReply>(
    "/assistant/respond",
    { subject_id: subjectId, messages },
    { "Idempotency-Key": idempotencyKey },
  );
