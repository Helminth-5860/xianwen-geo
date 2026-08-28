import { get, post, write } from "./auth-client";

export type AIModelCostUnit = "per_million_tokens" | "per_request" | null;

export type AIModelRuntimeConfig = Readonly<{
  model_id: string;
  provider_key: string;
  model_key: string;
  canonical_display_name: string;
  display_name: string;
  display_name_override: string;
  canonical_order: number;
  purpose: "geo_detection";
  is_builtin: true;
  provider_model_id: string;
  api_version: string;
  enabled: boolean;
  sort_order: number;
  network_access_enabled: boolean;
  web_search_failure_policy: "degrade_formal" | "degrade_reference" | "fail";
  timeout_seconds: number;
  max_retries: number;
  retry_base_seconds: number;
  retry_backoff: "fixed" | "exponential";
  max_concurrency: number;
  cost_unit: AIModelCostUnit;
  currency: "CNY";
  input_cost: string | null;
  output_cost: string | null;
  request_cost: string | null;
  paused: boolean;
  pause_reason: string;
  version: number;
  created_at: string;
  updated_at: string;
}>;

export type AIModelRuntimeConfigInput = {
  display_name_override: string;
  provider_model_id: string;
  api_version: string;
  sort_order: number;
  network_access_enabled: boolean;
  web_search_failure_policy: AIModelRuntimeConfig["web_search_failure_policy"];
  timeout_seconds: number;
  max_retries: number;
  retry_base_seconds: number;
  retry_backoff: AIModelRuntimeConfig["retry_backoff"];
  max_concurrency: number;
  cost_unit: AIModelCostUnit;
  currency: "CNY";
  input_cost: number | null;
  output_cost: number | null;
  request_cost: number | null;
};

export const getAIModels = () => get<AIModelRuntimeConfig[]>("/admin/ai-models");

export const updateAIModelRuntimeConfig = (
  model: AIModelRuntimeConfig,
  input: AIModelRuntimeConfigInput,
) =>
  write<AIModelRuntimeConfig>("PATCH", `/admin/ai-model-runtime-configs/${model.model_id}`, {
    expected_version: model.version,
    ...input,
  });

export const changeAIModelEnabled = (model: AIModelRuntimeConfig, action: "enable" | "disable") =>
  post<AIModelRuntimeConfig>(`/admin/ai-models/${model.model_id}/${action}`, {
    expected_version: model.version,
  });

export const pauseAIModel = (model: AIModelRuntimeConfig, reason: string) =>
  post<AIModelRuntimeConfig>(`/admin/ai-models/${model.model_id}/pause`, {
    expected_version: model.version,
    reason,
  });

export const unpauseAIModel = (model: AIModelRuntimeConfig) =>
  post<AIModelRuntimeConfig>(`/admin/ai-models/${model.model_id}/unpause`, {
    expected_version: model.version,
  });
