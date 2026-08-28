import { get, post, write } from "./auth-client";

export type ExecutionPriority = "urgent" | "high" | "medium" | "low";
export type ExecutionItemKind =
  "self_service" | "platform_assisted" | "manual_service" | "paid_media";
export type ExecutionItemStatus = "pending" | "in_progress" | "completed" | "cancelled";
export type ExecutionPlanStatus = "active" | "completed" | "cancelled";

export type ExecutionPreviewItem = Readonly<{
  key: string;
  title: string;
  problem: string;
  reason: string;
  recommendation: string;
  deliverables: string[];
  success_metric: string;
  expected_improvement: string;
  priority: ExecutionPriority;
  kind: ExecutionItemKind;
  estimated_days: number;
  estimated_price_cents: number;
  cost_note: string;
  selected_by_default: boolean;
  article_topic?: string;
  route?: string;
  period?: string;
}>;

export type ExecutionPackage = Readonly<{
  code: string;
  name: string;
  description: string;
  item_keys: string[];
  media_ids: string[];
  estimated_days: number;
  estimated_price_cents: number;
  recommended: boolean;
}>;

export type ExecutionRecommendedMedia = Readonly<{
  id: string;
  name: string;
  url: string | null;
  domain: string | null;
  logo_path: string | null;
  price_cents: number;
  reason: string;
  selected_by_default: boolean;
}>;

export type ExecutionPlanItem = Readonly<{
  key: string;
  title: string;
  kind: ExecutionItemKind;
  status: ExecutionItemStatus;
  recommendation: string;
  deliverables: string[];
  success_metric: string;
  estimated_days: number;
  estimated_price_cents: number;
  cost_note: string;
  article_topic?: string;
  route?: string;
  period?: string;
}>;

export type ExecutionPlanMedia = Readonly<{
  id: string;
  name: string;
  url: string | null;
  domain: string | null;
  logo_path: string | null;
  price_cents: number;
  inquiry_status: "not_submitted" | "pending" | "contacted" | "completed" | "cancelled";
}>;

export type ExecutionPlan = Readonly<{
  id: string;
  strategy_id: string;
  report_id: string;
  subject_id: string;
  package_code: string;
  package_name: string;
  status: ExecutionPlanStatus;
  version: number;
  estimated_days: number;
  estimated_price_cents: number;
  items: ExecutionPlanItem[];
  selected_media: ExecutionPlanMedia[];
  created_at: string;
  updated_at: string;
}>;

export type ExecutionPreviewResponse = Readonly<{
  preview: Readonly<{
    items: ExecutionPreviewItem[];
    packages: ExecutionPackage[];
    recommended_media: ExecutionRecommendedMedia[];
  }>;
  plan: ExecutionPlan | null;
}>;

export type ExecutionPlanPage = Readonly<{
  items: ExecutionPlan[];
  pagination: Readonly<{
    page: number;
    page_size: number;
    count: number;
    total_pages: number;
  }>;
}>;

export type ExecutionPlanAction =
  "start_item" | "complete_item" | "cancel_item" | "restore_item" | "cancel_plan";

type PlanEnvelope = ExecutionPlan | Readonly<{ plan: ExecutionPlan }>;

function unwrapPlan(value: PlanEnvelope): ExecutionPlan {
  return "plan" in value ? value.plan : value;
}

export const getExecutionPreview = (strategyId: string) =>
  get<ExecutionPreviewResponse>(`/strategies/${strategyId}/execution-preview`, {
    cache: "no-store",
  });

export async function createExecutionPlan(
  strategyId: string,
  input: { package_code: string; item_keys: string[]; media_ids: string[] },
  idempotencyKey: string,
) {
  return unwrapPlan(
    await post<PlanEnvelope>(`/strategies/${strategyId}/execution-plans`, input, {
      "Idempotency-Key": idempotencyKey,
    }),
  );
}

export const getExecutionPlans = (subjectId: string, page = 1) =>
  get<ExecutionPlanPage>(`/subjects/${subjectId}/execution-plans?page=${page}&page_size=20`, {
    cache: "no-store",
  });

export async function getExecutionPlan(planId: string) {
  return unwrapPlan(
    await get<PlanEnvelope>(`/execution-plans/${planId}`, {
      cache: "no-store",
    }),
  );
}

export async function updateExecutionPlan(
  planId: string,
  input: { action: ExecutionPlanAction; item_key?: string; expected_version: number },
) {
  return unwrapPlan(await write<PlanEnvelope>("PATCH", `/execution-plans/${planId}`, input));
}
