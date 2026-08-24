import { get, getCsrfToken, readEnvelope } from "./auth-client";
import { publicEnvironment } from "./env";

export type OperationsPage<T> = Readonly<{
  items: T[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
}>;

export type OperationsDashboard = Readonly<{
  customers: { total: number; active: number };
  followups: { open: number; overdue: number };
  feedback_open: number;
  moderation: { articles: number; images: number };
  task_counts: Record<string, number>;
  generated_at: string;
}>;

export type ReleaseCheck = Readonly<{
  key: string;
  status: "READY" | "NOT_READY";
  required: boolean;
  code: string;
  safe_summary: Record<string, unknown>;
}>;

export type ReleaseReadiness = Readonly<{
  status: "READY" | "NOT_READY";
  generated_at: string;
  environment: string;
  checks: ReleaseCheck[];
  secrets_included: false;
}>;

export type OperationsCustomer = Readonly<{
  id: string;
  phone: string;
  nickname: string;
  account_status: string;
  profile: {
    status: { id: string; key: string; name: string } | null;
    source: string;
    internal_note: string;
    version: number;
  };
  tags: { id: string; key: string; name: string }[];
  owner: { id: string; nickname: string } | null;
  subscription: { id: string; plan_key: string; is_trial: boolean; ends_at: string } | null;
  subject_count: number;
  open_followup_count: number;
}>;

export type OperationsTask = Readonly<{
  id: string;
  type: string;
  status: string;
  user_id: string;
  created_at: string;
  safe_error_code: string;
}>;

export type ModerationQueue = Readonly<{
  articles: { id: string; user_id: string; subject_id: string; status: string; version: number }[];
  images: { id: string; user_id: string; subject_id: string; status: string; version: number }[];
}>;

export const getOperationsDashboard = () => get<OperationsDashboard>("/admin/operations/dashboard");
export const getReleaseReadiness = () => get<ReleaseReadiness>("/admin/release-readiness");
export const getOperationsCustomers = () =>
  get<OperationsPage<OperationsCustomer>>("/admin/operations/customers?page=1&page_size=50");
export const getOperationsTasks = () =>
  get<{ items: OperationsTask[]; safe_projection: true }>("/admin/tasks");
export const getModerationQueue = () => get<ModerationQueue>("/admin/moderation");

export async function exportOperationsCustomers(): Promise<Blob> {
  const csrfToken = await getCsrfToken();
  const response = await fetch(
    `${publicEnvironment.apiBaseUrl}/admin/operations/exports/customers`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "text/csv",
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({ format: "csv", confirmation: "EXPORT_SCOPED_CUSTOMERS" }),
    },
  );
  if (!response.ok) {
    await readEnvelope<never>(response);
    throw new Error("导出失败，请稍后再试");
  }
  return response.blob();
}
