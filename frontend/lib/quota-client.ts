import { get, post, type PageData } from "./auth-client";
import type { RiskExecution } from "./risk-client";

export { formatQuotaAmount, isUnlimitedQuotaAmount } from "./quota-format";

export const CUSTOMER_QUOTA_TYPES = [
  "geo_detection_runs",
  "article_generations",
  "auto_publish_count",
  "image_generations",
  "source_index_scans",
  "negative_index_scans",
  "website_audits",
  "website_generations",
  "video_script_generations",
  "competitor_comparisons",
  "keyword_generated_items",
  "question_generated_items",
] as const;

export type CustomerQuotaType = (typeof CUSTOMER_QUOTA_TYPES)[number];
export type LegacyQuotaType =
  | "detection_points"
  | "article_credits"
  | "image_credits"
  | "video_credits"
  | "storage_bytes"
  | "assistant_messages";
export type QuotaType = CustomerQuotaType | LegacyQuotaType | (string & {});

export const CUSTOMER_QUOTA_PRESENTATION: Readonly<
  Record<CustomerQuotaType, { name: string; unit: string; shortDescription: string }>
> = Object.freeze({
  geo_detection_runs: { name: "GEO 检测", unit: "次", shortDescription: "完成一次正式检测" },
  article_generations: { name: "AI 文章", unit: "篇", shortDescription: "成功生成文章" },
  auto_publish_count: { name: "自动发文", unit: "篇", shortDescription: "成功自动发布文章" },
  image_generations: { name: "AI 图片", unit: "张", shortDescription: "成功生成图片" },
  source_index_scans: { name: "信源扫描", unit: "次", shortDescription: "完成一次信源分析" },
  negative_index_scans: {
    name: "负面信息扫描",
    unit: "次",
    shortDescription: "完成一次负面信息分析",
  },
  website_audits: { name: "官网检测", unit: "次", shortDescription: "完成一次官网检测" },
  website_generations: { name: "官网生成", unit: "次", shortDescription: "成功生成官网方案" },
  video_script_generations: { name: "视频脚本", unit: "条", shortDescription: "成功生成视频脚本" },
  competitor_comparisons: { name: "竞品对比", unit: "次", shortDescription: "完成一次竞品对比" },
  keyword_generated_items: { name: "智能关键词", unit: "条", shortDescription: "成功新增关键词" },
  question_generated_items: { name: "AI 问题库", unit: "条", shortDescription: "成功新增问题" },
});

const LEGACY_TO_CUSTOMER: Readonly<Partial<Record<LegacyQuotaType, CustomerQuotaType>>> = {
  detection_points: "geo_detection_runs",
  article_credits: "article_generations",
  image_credits: "image_generations",
};

export type QuotaAccount = Readonly<{
  id: string;
  user_id: string;
  user_nickname: string;
  subscription_id: string;
  subscription_plan_name?: string;
  plan_name?: string;
  quota_type: QuotaType;
  display_name?: string;
  unit: string;
  scope: "subscription" | "account" | "account_cycle" | string;
  entitlement_amount: number;
  total_amount?: number;
  available: number;
  frozen: number;
  used_amount?: number;
  cycle_started_at: string | null;
  cycle_ends_at: string | null;
  ledger_sequence: number;
  last_adjusted_at?: string | null;
  last_ledger_created_at?: string | null;
  last_adjustment?: Readonly<{
    action: string;
    action_name: string;
    reason: string;
    operator_name: string;
    created_at: string;
  }> | null;
  version: number;
}>;

export type UserQuotaSummary = Readonly<{
  quota_type: QuotaType;
  display_name?: string;
  unit: string;
  scope: string;
  entitlement_amount: number;
  total_amount?: number;
  available: number;
  frozen: number;
  used_amount?: number;
  unlimited?: boolean;
}>;

export type UserQuotaLedgerEntry = Readonly<{
  id: string;
  quota_type: QuotaType;
  display_name?: string;
  action: string;
  action_label?: string;
  available_before?: number;
  available_delta: number;
  available_after: number;
  frozen_before?: number;
  frozen_delta: number;
  frozen_after: number;
  amount?: number;
  change_amount?: number;
  balance_before?: number;
  balance_after?: number;
  unit_display_name?: string;
  business_type?: string;
  safe_reason?: string;
  description?: string;
  related_object?: string;
  status_label?: string;
  created_at: string;
}>;

export type QuotaAdjustmentAction = "grant" | "compensate" | "manual-deduct" | "refund";

export function customerQuotaType(value: QuotaType): CustomerQuotaType | null {
  if ((CUSTOMER_QUOTA_TYPES as readonly string[]).includes(value)) {
    return value as CustomerQuotaType;
  }
  return LEGACY_TO_CUSTOMER[value as LegacyQuotaType] ?? null;
}

export function customerQuotaPresentation(value: QuotaType) {
  const normalized = customerQuotaType(value);
  return normalized ? CUSTOMER_QUOTA_PRESENTATION[normalized] : null;
}

export function normalizeCustomerQuotaAccounts(accounts: readonly UserQuotaSummary[]) {
  const rows = new Map<CustomerQuotaType, UserQuotaSummary>();
  for (const account of accounts) {
    const normalized = customerQuotaType(account.quota_type);
    if (!normalized) continue;
    const current = rows.get(normalized);
    const isCurrentType = account.quota_type === normalized;
    if (!current || isCurrentType) rows.set(normalized, account);
  }
  return CUSTOMER_QUOTA_TYPES.flatMap((quotaType) => {
    const account = rows.get(quotaType);
    return account ? [{ ...account, quota_type: quotaType }] : [];
  });
}

export const getCurrentQuotaAccounts = () => get<{ accounts: UserQuotaSummary[] }>("/quotas");

export const getUserQuotaLedger = (page = 1, quotaType = "") => {
  const query = new URLSearchParams({ page: String(page), page_size: "20" });
  if (quotaType) query.set("quota_type", quotaType);
  return get<PageData<UserQuotaLedgerEntry>>(`/quota-ledger?${query.toString()}`);
};

export const getAdminQuotaAccounts = (page = 1, quotaType = "", keyword = "") => {
  const query = new URLSearchParams({ page: String(page), page_size: "20" });
  if (quotaType) query.set("quota_type", quotaType);
  if (keyword.trim()) query.set("keyword", keyword.trim());
  return get<PageData<QuotaAccount>>(`/admin/quota-accounts?${query.toString()}`);
};

export const adjustQuotaAccount = (
  accountId: string,
  action: QuotaAdjustmentAction,
  expectedVersion: number,
  amount: number,
  reason: string,
  idempotencyKey: string,
) =>
  post<
    RiskExecution<{
      account_id: string;
      ledger_entry_id: string;
      available: number;
      frozen: number;
      version: number;
      replayed: boolean;
    }>
  >(
    "/admin/quota-accounts/" + accountId + "/adjust/" + action,
    { expected_version: expectedVersion, amount, reason, confirmed: true },
    { "Idempotency-Key": idempotencyKey },
  );
