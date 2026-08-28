import { get, write, type PageData } from "./auth-client";

export type RiskMode = "confirm" | "password";

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

export type AuditEvent = Readonly<{
  id: string;
  category: string;
  action_key: string;
  outcome: string;
  actor_id: string | null;
  subject_id: string | null;
  requester_id: string | null;
  target_type: string;
  target_id: string;
  request_id: string;
  safe_before: Record<string, unknown>;
  safe_after: Record<string, unknown>;
  stable_error_code: string;
  ip_fingerprint: string;
  user_agent_digest: string;
  created_at: string;
}>;

export type RiskExecution<T> = T;

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

export const getAuditEvents = (page = 1, actionKey = "", outcome = "") => {
  const query = new URLSearchParams({ page: String(page) });
  if (actionKey) query.set("action_key", actionKey);
  if (outcome) query.set("outcome", outcome);
  return get<PageData<AuditEvent>>(`/admin/audit-events?${query.toString()}`);
};
export const getAuditEvent = (id: string) => get<AuditEvent>(`/admin/audit-events/${id}`);
