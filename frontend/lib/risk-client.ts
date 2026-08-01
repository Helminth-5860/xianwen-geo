import { get, post, write, type PageData } from "./auth-client";

export type RiskMode = "confirm" | "password" | "two_person";

export type RiskAction = Readonly<{
  key: string;
  name: string;
  module: string;
  target_type: string;
  supported_modes: RiskMode[];
  default_mode: RiskMode;
  minimum_mode: RiskMode;
  status: "active" | "inactive";
  catalog_version: number;
  current_mode: RiskMode;
  policy_version: number;
}>;

export type RiskPolicy = Readonly<{
  action_key: string;
  current_mode: RiskMode;
  version: number;
  supported_modes: RiskMode[];
  default_mode: RiskMode;
  minimum_mode: RiskMode;
  updated_at: string;
}>;

export type ApprovalCreated = Readonly<{
  approval_required: true;
  approval_id: string;
  status: "pending";
  expires_at: string;
}>;

export type Approval = Readonly<{
  id: string;
  action_key: string;
  policy_version: number;
  requester_id: string;
  target_type: string;
  target_id: string;
  target_version: number;
  safe_summary: string;
  status:
    "pending" | "rejected" | "cancelled" | "expired" | "stale" | "executed" | "execution_failed";
  expires_at: string;
  approved_by_id: string | null;
  approved_at: string | null;
  rejected_by_id: string | null;
  rejected_at: string | null;
  rejection_reason: string;
  cancelled_at: string | null;
  executed_at: string | null;
  execution_result: Record<string, unknown>;
  stable_error_code: string;
  request_id: string;
  created_at: string;
  updated_at: string;
}>;

export type AuditEvent = Readonly<{
  id: string;
  category: string;
  action_key: string;
  outcome: string;
  actor_id: string | null;
  subject_id: string | null;
  requester_id: string | null;
  approver_id: string | null;
  target_type: string;
  target_id: string;
  request_id: string;
  approval_request_id: string | null;
  safe_before: Record<string, unknown>;
  safe_after: Record<string, unknown>;
  stable_error_code: string;
  ip_fingerprint: string;
  user_agent_digest: string;
  created_at: string;
}>;

export type RiskExecution<T> = T | ApprovalCreated;

export const isApprovalCreated = <T>(value: RiskExecution<T>): value is ApprovalCreated =>
  "approval_required" in (value as object) && (value as ApprovalCreated).approval_required === true;

export const getRiskActions = () => get<RiskAction[]>("/admin/risk-actions");
export const getRiskPolicies = () => get<RiskPolicy[]>("/admin/risk-policies");
export const updateRiskPolicy = (
  actionKey: string,
  body: {
    current_mode: RiskMode;
    expected_version: number;
    current_password: string;
    confirmed: true;
  },
) => write<RiskPolicy>("PATCH", `/admin/risk-policies/${actionKey}`, body);

export const getApprovals = (page = 1, status = "") => {
  const query = new URLSearchParams({ page: String(page) });
  if (status) query.set("status", status);
  return get<PageData<Approval>>(`/admin/approvals?${query.toString()}`);
};
export const getApproval = (id: string) => get<Approval>(`/admin/approvals/${id}`);
export const approveApproval = (id: string, currentPassword: string) =>
  post<Approval>(`/admin/approvals/${id}/approve`, {
    current_password: currentPassword,
  });
export const rejectApproval = (id: string, reason: string) =>
  post<Approval>(`/admin/approvals/${id}/reject`, { reason });
export const cancelApproval = (id: string) => post<Approval>(`/admin/approvals/${id}/cancel`, {});

export const getAuditEvents = (page = 1, actionKey = "", outcome = "") => {
  const query = new URLSearchParams({ page: String(page) });
  if (actionKey) query.set("action_key", actionKey);
  if (outcome) query.set("outcome", outcome);
  return get<PageData<AuditEvent>>(`/admin/audit-events?${query.toString()}`);
};
export const getAuditEvent = (id: string) => get<AuditEvent>(`/admin/audit-events/${id}`);
