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
export type PlanApplicationStatus = "pending" | "contacted" | "closed" | "cancelled" | "activated";
export type PlanApplicationEvent = Readonly<{
  id: string;
  event_type: "submitted" | "contacted" | "closed" | "cancelled" | "activated";
  from_status: string;
  to_status: PlanApplicationStatus;
  safe_summary: string;
  created_at: string;
}>;
export type PlanApplication = Readonly<{
  id: string;
  activated_at: string | null;
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
export type SubscriptionStatus = "active" | "expired" | "terminated";
export type Subscription = Readonly<{
  id: string;
  user_id?: string;
  user_nickname?: string;
  plan_id: string;
  plan_code: string;
  plan_name: string;
  plan_version_id: string;
  plan_version_no: number;
  status: SubscriptionStatus;
  source_type: "application" | "trial_grant" | "plan_change";
  source_change_id?: string | null;
  is_trial: boolean;
  starts_at: string;
  ends_at: string;
  cycle_anchor_day: number;
  cycle_anchor_time: string;
  entitlement_summary: {
    valid_days: number;
    limit_keys: string[];
    enabled_model_keys: ModelKey[];
  };
  version: number;
  source_application_id?: string | null;
  activated_at?: string;
  expired_at?: string | null;
  terminated_at?: string | null;
  termination_reason?: string;
  events?: {
    id: string;
    event_type: "activated" | "expired" | "terminated";
    safe_summary: string;
    created_at: string;
  }[];
}>;

export type SubscriptionChangeStatus = "scheduled" | "executed" | "cancelled" | "failed";
export type SubscriptionChangeType =
  "renewal" | "upgrade" | "downgrade" | "replacement" | "trial_conversion";
export type SubscriptionQuotaPolicy = "overwrite" | "accumulate" | "retain";
export type SubscriptionChange = Readonly<{
  id: string;
  from_subscription_id: string;
  target_plan_id: string;
  target_plan_name: string;
  target_plan_version_id?: string;
  target_plan_version_no: number;
  status: SubscriptionChangeStatus;
  change_type: SubscriptionChangeType;
  quota_policy: SubscriptionQuotaPolicy;
  effective_at: string;
  executed_at: string | null;
  cancelled_at: string | null;
  failed_at: string | null;
  stable_error_code: string;
  next_attempt_at?: string | null;
  retry_count?: number;
  version: number;
  reason?: string;
  unavailable_reason?: string;
  cancellation_reason?: string;
  user_id?: string;
  user_nickname?: string;
  created_at: string;
  updated_at?: string;
}>;
export type SubscriptionChangePreview = Readonly<{
  change_type: SubscriptionChangeType;
  target_plan_id: string;
  target_plan_version_id: string;
  source_plan_version_no: number;
  target_plan_version_no: number;
  quota_policy: SubscriptionQuotaPolicy;
  effective_at: string;
  ends_at: string | null;
  cycle_anchor_day: number;
  unavailable_confirmation_required: boolean;
  cycle_anchor_time: string;
  changed_limit_keys: string[];
  added_model_keys: ModelKey[];
  removed_model_keys: ModelKey[];
}>;
export type SubscriptionChangeInput = Readonly<{
  expectedVersion: number;
  targetPlanVersionId: string;
  changeType: SubscriptionChangeType;
  quotaPolicy: SubscriptionQuotaPolicy;
  confirmUnavailable?: boolean;
  unavailableReason?: string;
  reason: string;
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
export const getCurrentSubscription = () => get<{ current: Subscription | null }>("/subscription");
export const getAdminSubscriptions = (status = "", page = 1) => {
  const query = new URLSearchParams({ page: String(page) });
  if (status) query.set("status", status);
  return get<PageData<Subscription>>("/admin/subscriptions?" + query.toString());
};
export const getAdminSubscription = (id: string) => get<Subscription>("/admin/subscriptions/" + id);
export const openSubscriptionFromApplication = (
  id: string,
  expectedVersion: number,
  input: {
    selectedPlanVersionId?: string | null;
    confirmUnavailable?: boolean;
    unavailableReason?: string;
    confirmVersionOverride?: boolean;
    overrideReason?: string;
    openingNote?: string;
  } = {},
) =>
  post<RiskExecution<{ approval_required: true }>>("/admin/plan-applications/" + id + "/activate", {
    expected_version: expectedVersion,
    selected_plan_version_id: input.selectedPlanVersionId ?? null,
    confirm_unavailable: input.confirmUnavailable ?? false,
    unavailable_reason: input.unavailableReason ?? "",
    confirm_version_override: input.confirmVersionOverride ?? false,
    override_reason: input.overrideReason ?? "",
    opening_note: input.openingNote ?? "",
  });
export const grantTrialSubscription = (
  userId: string,
  expectedVersion: number,
  planId: string,
  openingNote = "",
) =>
  post<RiskExecution<{ approval_required: true }>>(
    "/admin/users/" + userId + "/subscriptions/trial",
    { expected_version: expectedVersion, plan_id: planId, opening_note: openingNote },
  );
export const terminateSubscription = (id: string, expectedVersion: number, reason: string) =>
  post<RiskExecution<{ approval_required: true }>>("/admin/subscriptions/" + id + "/terminate", {
    expected_version: expectedVersion,
    reason,
  });
export const previewSubscriptionChange = (
  id: string,
  input: Omit<SubscriptionChangeInput, "reason" | "confirmUnavailable" | "unavailableReason">,
) =>
  post<SubscriptionChangePreview>("/admin/subscriptions/" + id + "/change/preview", {
    expected_version: input.expectedVersion,
    target_plan_version_id: input.targetPlanVersionId,
    change_type: input.changeType,
    quota_policy: input.quotaPolicy,
  });
export const requestSubscriptionChange = (
  id: string,
  input: SubscriptionChangeInput,
  idempotencyKey: string,
) =>
  post<RiskExecution<{ approval_required: true }>>(
    "/admin/subscriptions/" + id + "/change",
    {
      expected_version: input.expectedVersion,
      target_plan_version_id: input.targetPlanVersionId,
      change_type: input.changeType,
      quota_policy: input.quotaPolicy,
      confirm_unavailable: input.confirmUnavailable ?? false,
      unavailable_reason: input.unavailableReason ?? "",
      reason: input.reason,
    },
    { "Idempotency-Key": idempotencyKey },
  );
export const getAdminSubscriptionChanges = (status = "", page = 1) => {
  const query = new URLSearchParams({ page: String(page) });
  if (status) query.set("status", status);
  return get<PageData<SubscriptionChange>>("/admin/subscription-changes?" + query.toString());
};
export const getAdminSubscriptionChange = (id: string) =>
  get<SubscriptionChange>("/admin/subscription-changes/" + id);
export const cancelSubscriptionChange = (
  id: string,
  expectedVersion: number,
  reason: string,
  idempotencyKey: string,
) =>
  post<RiskExecution<{ approval_required: true }>>(
    "/admin/subscription-changes/" + id + "/cancel",
    { expected_version: expectedVersion, reason },
    { "Idempotency-Key": idempotencyKey },
  );
export const getUserSubscriptionChanges = () =>
  get<{ results: SubscriptionChange[] }>("/subscription/changes");
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
