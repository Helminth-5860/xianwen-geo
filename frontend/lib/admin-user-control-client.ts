import { get, post } from "./auth-client";

export type ControlCenterQuotaAccount = Readonly<{
  id: string;
  batch_type: "primary" | "carryover" | string;
  scope: string;
  entitlement_amount: string;
  available: string;
  frozen: string;
  used_amount: string;
  version: number;
  cycle_started_at: string | null;
  cycle_ends_at: string | null;
  spendable_until: string | null;
  adjustable: boolean;
}>;

export type ControlCenterQuota = Readonly<{
  quota_type: string;
  display_name: string;
  unit: string;
  unit_display_name: string;
  entitlement_amount: string;
  manual_adjustment_amount: string;
  total_amount: string;
  used_amount: string;
  frozen: string;
  available: string;
  accounts: readonly ControlCenterQuotaAccount[];
}>;

export type ControlCenterSubscription = Readonly<{
  id: string;
  plan_id: string;
  plan_name: string;
  plan_code: string;
  plan_version_id: string;
  plan_version_no: number;
  status: "active" | "expired" | "terminated" | string;
  source_type: string;
  is_trial: boolean;
  starts_at: string;
  ends_at: string;
  activated_at: string;
  version: number;
  opening_note: string;
}>;

export type ControlCenterLoginEvent = Readonly<{
  id: string;
  login_method: string;
  success: boolean;
  failure_reason: string;
  ip_address: string | null;
  user_agent: string;
  request_id: string;
  created_at: string;
}>;

export type ControlCenterPlanLimit = Readonly<{
  key: string;
  name: string;
  category: string;
  value_type: string;
  unit: string;
  quota_type: string;
  description: string;
  value: unknown;
}>;

export type ControlCenterLedgerEntry = Readonly<{
  id: string;
  account_id: string;
  quota_type: string;
  display_name: string;
  action: string;
  available_before: string;
  available_delta: string;
  available_after: string;
  frozen_before: string;
  frozen_delta: string;
  frozen_after: string;
  safe_reason: string;
  actor_id: string | null;
  actor_name: string;
  request_id: string;
  created_at: string;
}>;

export type ControlCenterAuditEntry = Readonly<{
  id: string;
  action_key: string;
  outcome: "success" | "failure";
  channel: string;
  actor_user_id_snapshot: string | null;
  actor_name_snapshot: string;
  actor_role_snapshot: string;
  target_user_id_snapshot: string | null;
  target_name_snapshot: string;
  quota_type: string;
  quota_before: string | null;
  quota_requested_delta: string | null;
  quota_delta: string | null;
  quota_after: string | null;
  ledger_entry_id: string | null;
  request_id: string;
  operation_ip: string | null;
  login_ip_snapshot: string | null;
  safe_reason: string;
  failure_reason: string;
  created_at: string;
}>;

export type AdminUserControlCenter = Readonly<{
  user: Readonly<{
    id: string;
    nickname: string;
    phone_masked: string;
    account_status: string;
    status_version: number;
    created_at: string;
    updated_at: string;
    tenant: Readonly<{
      id: string;
      key: string;
      display_name: string;
      brand_name: string;
      status: string;
    }> | null;
    assignment: Readonly<{
      assignment_id: string;
      version: number;
      assigned_at: string | null;
      owner_admin_id: string | null;
      owner_user_id: string | null;
      owner_name: string;
      owner_role: string;
    }> | null;
    login: Readonly<{
      last_success_at: string | null;
      last_success_ip: string | null;
      last_success_user_agent: string;
      recent: readonly ControlCenterLoginEvent[];
    }>;
  }>;
  subscription: ControlCenterSubscription | null;
  subscription_history: readonly ControlCenterSubscription[];
  quotas: readonly ControlCenterQuota[];
  plan_limits: readonly ControlCenterPlanLimit[];
  model_permissions: readonly Readonly<Record<string, unknown>>[];
  usage: Readonly<{
    window_days: number;
    items: readonly Readonly<{
      quota_type: string;
      display_name: string;
      amount: string;
      unit_display_name: string;
    }>[];
  }>;
  recent_ledger: readonly ControlCenterLedgerEntry[];
  recent_audit: readonly ControlCenterAuditEntry[];
}>;

export type ControlCenterQuotaAdjustmentAction = "grant" | "manual-deduct";

export function getAdminUserControlCenter(userId: string) {
  return get<AdminUserControlCenter>(`/admin/users/${userId}/control-center`, {
    cache: "no-store",
  });
}

export function adjustControlCenterQuota(input: {
  accountId: string;
  accountVersion: number;
  action: ControlCenterQuotaAdjustmentAction;
  amount: string;
  reason: string;
  idempotencyKey: string;
}) {
  return post<unknown>(
    `/admin/quota-accounts/${input.accountId}/adjust/${input.action}`,
    {
      expected_version: input.accountVersion,
      amount: input.amount,
      reason: input.reason,
      confirmed: true,
    },
    { "Idempotency-Key": input.idempotencyKey },
  );
}
