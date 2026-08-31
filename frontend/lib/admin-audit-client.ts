import { get, type PageData } from "./auth-client";

export type SensitiveAuditLog = Readonly<{
  id: string;
  action_key: string;
  outcome: "success" | "failure";
  channel: string;
  actor_user_id_snapshot: string | null;
  actor_name_snapshot: string;
  actor_role_snapshot: string;
  actor_tenant_id_snapshot: string | null;
  actor_tenant_name_snapshot: string;
  target_user_id_snapshot: string | null;
  target_name_snapshot: string;
  target_tenant_id_snapshot: string | null;
  target_tenant_name_snapshot: string;
  quota_type: string;
  quota_before: number | null;
  quota_requested_delta: number | null;
  quota_delta: number | null;
  quota_after: number | null;
  ledger_entry_id: string | null;
  request_id: string;
  operation_ip: string | null;
  login_ip_snapshot: string | null;
  safe_reason: string;
  failure_reason: string;
  user_agent?: string;
  details?: Record<string, unknown>;
  created_at: string;
}>;

export type SensitiveAuditFilters = Readonly<{
  q?: string;
  actionKey?: string;
  outcome?: "success" | "failure" | "";
  days?: number;
  dateFrom?: string;
  dateTo?: string;
}>;

export function getSensitiveAuditLogs(
  page = 1,
  filters: SensitiveAuditFilters = { days: 7 },
) {
  const query = new URLSearchParams({ page: String(page), page_size: "20" });
  if (filters.q?.trim()) query.set("q", filters.q.trim());
  if (filters.actionKey) query.set("action_key", filters.actionKey);
  if (filters.outcome) query.set("outcome", filters.outcome);
  if (filters.dateFrom || filters.dateTo) {
    if (filters.dateFrom) query.set("date_from", filters.dateFrom);
    if (filters.dateTo) query.set("date_to", filters.dateTo);
  } else {
    query.set("days", String(filters.days ?? 7));
  }
  return get<PageData<SensitiveAuditLog>>(`/admin/sensitive-audit-logs?${query.toString()}`);
}

export const getSensitiveAuditLog = (id: string) =>
  get<SensitiveAuditLog>(`/admin/sensitive-audit-logs/${id}`);
