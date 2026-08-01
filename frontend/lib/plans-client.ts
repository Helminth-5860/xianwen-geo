import { get, post, write, type PageData } from "./auth-client";
import type { RiskExecution } from "./risk-client";

export type ModelKey =
  "deepseek" | "doubao" | "qwen" | "hunyuan" | "wenxin" | "kimi" | "glm" | "spark";
export type RiskInput = { confirmed?: boolean; current_password?: string };
export type PlanLimit = Readonly<{ key: string; value_type: string; value: unknown }>;
export type PlanModel = Readonly<{
  model_key: ModelKey;
  name: string;
  sort_order: number;
  selected_by_default: boolean;
}>;
export type PlanVersion = Readonly<{
  id: string;
  plan_id: string;
  version_no: number;
  status: "draft" | "published" | "retired";
  valid_days: number;
  queue_priority: number;
  version: number;
  snapshot_generated_at: string | null;
  limits: PlanLimit[];
  model_permissions: PlanModel[];
  supports_formal_composite: boolean;
}>;
export type Plan = Readonly<{
  id: string;
  code: string;
  name: string;
  description: string;
  price_display_mode: "fixed" | "contact";
  display_price: string | null;
  display_currency: "CNY";
  is_trial: boolean;
  status: "draft" | "published" | "offline" | "archived";
  sort_order: number;
  current_published_version_id: string | null;
  version: number;
  draft_version?: PlanVersion | null;
  current_published_version?: PlanVersion | null;
}>;
export type LimitDefinition = Readonly<{
  key: string;
  name: string;
  category: string;
  value_type: "integer" | "boolean" | "text" | "enum" | "json";
  storage_kind: "plan_limit" | "plan_version_field" | "model_permissions";
  minimum: number | null;
  maximum: number | null;
  required: boolean;
  default: unknown;
  enum_values: string[];
  description: string;
  status: "active" | "inactive";
}>;
export type PublicPlan = Readonly<{
  id: string;
  code: string;
  name: string;
  description: string;
  price_display_mode: "fixed" | "contact";
  display_price: string | null;
  display_currency: "CNY";
  is_trial: boolean;
  valid_days: number;
  benefits: Record<string, unknown>;
  models: { model_key: ModelKey; name: string; selected_by_default: boolean }[];
  supports_formal_composite: boolean;
  sort_order: number;
  plan_version_id: string;
  version_no: number;
}>;
export type PlanApplicationStatus = "pending" | "contacted" | "closed" | "cancelled";
export type PlanApplicationEvent = Readonly<{
  id: string;
  event_type: "submitted" | "contacted" | "closed" | "cancelled";
  from_status: string;
  to_status: PlanApplicationStatus;
  safe_summary: string;
  created_at: string;
}>;
export type PlanApplication = Readonly<{
  id: string;
  plan_id: string;
  requested_plan_version_id: string;
  requested_version_no: number;
  public_plan_snapshot: PublicPlan & Record<string, unknown>;
  status: PlanApplicationStatus;
  source: "user_web";
  user_note: string;
  contacted_at: string | null;
  closed_at: string | null;
  cancelled_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  events: PlanApplicationEvent[];
}>;
export type AdminPlanApplication = PlanApplication &
  Readonly<{
    applicant_id: string;
    applicant_nickname: string;
    applicant_phone_masked: string;
    applicant_phone?: string;
    current_owner: { id: string; nickname: string } | null;
  }>;

const risk = (input: RiskInput) => ({
  confirmed: input.confirmed ?? false,
  current_password: input.current_password ?? "",
});
export const getPublicPlans = () => get<PublicPlan[]>("/plans");
export const createPlanApplication = (
  planId: string,
  planVersionId: string,
  userNote: string,
  idempotencyKey: string,
) =>
  post<PlanApplication>(
    "/plan-applications",
    { plan_id: planId, plan_version_id: planVersionId, user_note: userNote },
    { "Idempotency-Key": idempotencyKey },
  );
export const getPlanApplications = (page = 1, status = "") => {
  const query = new URLSearchParams({ page: String(page) });
  if (status) query.set("status", status);
  return get<PageData<PlanApplication>>(`/plan-applications?${query.toString()}`);
};
export const getPlanApplication = (id: string) => get<PlanApplication>(`/plan-applications/${id}`);
export const cancelPlanApplication = (id: string, expectedVersion: number) =>
  post<PlanApplication>(`/plan-applications/${id}/cancel`, { expected_version: expectedVersion });
export const getAdminPlanApplications = (status = "", planId = "", page = 1) => {
  const query = new URLSearchParams({ page: String(page) });
  if (status) query.set("status", status);
  if (planId) query.set("plan_id", planId);
  return get<PageData<AdminPlanApplication>>(`/admin/plan-applications?${query.toString()}`);
};
export const getAdminPlanApplication = (id: string) =>
  get<AdminPlanApplication>(`/admin/plan-applications/${id}`);
export const changeAdminPlanApplication = (
  id: string,
  action: "contact" | "close",
  expectedVersion: number,
  input: RiskInput,
) =>
  post<RiskExecution<AdminPlanApplication>>(`/admin/plan-applications/${id}/${action}`, {
    expected_version: expectedVersion,
    ...risk(input),
  });
export const getPlans = (status = "", keyword = "") => {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (keyword) query.set("keyword", keyword);
  return get<PageData<Plan>>(`/admin/plans?${query.toString()}`);
};
export const getPlan = (id: string) => get<Plan>(`/admin/plans/${id}`);
export const getPlanVersion = (id: string) => get<PlanVersion>(`/admin/plan-versions/${id}`);
export const getLimitDefinitions = () => get<LimitDefinition[]>("/admin/plan-limit-definitions");
export const createPlan = (body: Record<string, unknown> & RiskInput) =>
  post<RiskExecution<Plan>>("/admin/plans", body);
export const updatePlan = (id: string, body: Record<string, unknown> & RiskInput) =>
  write<RiskExecution<Plan>>("PATCH", `/admin/plans/${id}`, body);
export const copyPlan = (id: string, body: Record<string, unknown> & RiskInput) =>
  post<RiskExecution<Plan>>(`/admin/plans/${id}/copy`, body);
export const createPlanVersion = (id: string, expected: number, input: RiskInput) =>
  post<RiskExecution<PlanVersion>>(`/admin/plans/${id}/versions`, {
    expected_plan_version: expected,
    ...risk(input),
  });
export const updatePlanVersion = (id: string, body: Record<string, unknown> & RiskInput) =>
  write<RiskExecution<PlanVersion>>("PATCH", `/admin/plan-versions/${id}`, body);
export const publishPlanVersion = (
  id: string,
  expected: number,
  informal: boolean,
  input: RiskInput,
) =>
  post<RiskExecution<PlanVersion>>(`/admin/plan-versions/${id}/publish`, {
    expected_version: expected,
    confirm_informal_composite: informal,
    ...risk(input),
  });
export const retirePlanVersion = (id: string, expected: number, input: RiskInput) =>
  post<RiskExecution<PlanVersion>>(`/admin/plan-versions/${id}/retire`, {
    expected_version: expected,
    ...risk(input),
  });
export const changePlanState = (
  id: string,
  action: "online" | "offline" | "archive",
  expected: number,
  input: RiskInput,
) =>
  post<RiskExecution<Plan>>(`/admin/plans/${id}/${action}`, {
    expected_version: expected,
    ...risk(input),
  });
