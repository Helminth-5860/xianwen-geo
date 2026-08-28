import { get, post, type PageData } from "./auth-client";
import type { RiskExecution } from "./risk-client";

export type QuotaType =
  "detection_points" | "article_credits" | "image_credits" | "storage_bytes" | "assistant_messages";

export type QuotaAccount = Readonly<{
  id: string;
  user_id: string;
  user_nickname: string;
  subscription_id: string;
  quota_type: QuotaType;
  unit: string;
  scope: "subscription" | "account" | "account_cycle";
  entitlement_amount: number;
  available: number;
  frozen: number;
  cycle_started_at: string | null;
  cycle_ends_at: string | null;
  ledger_sequence: number;
  version: number;
}>;

export type QuotaAdjustmentAction = "grant" | "compensate" | "manual-deduct";

export const getAdminQuotaAccounts = (page = 1) =>
  get<PageData<QuotaAccount>>("/admin/quota-accounts?page=" + page);

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
