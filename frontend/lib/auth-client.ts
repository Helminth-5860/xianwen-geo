import { publicEnvironment } from "./env";

export type AccountUser = Readonly<{
  id: string;
  nickname: string;
  phone_masked: string;
  approval_status: "pending" | "approved" | "rejected";
  account_status: "active" | "frozen" | "cancel_pending" | "cancelled";
  approval_reason?: string;
}>;

export type SmsPurpose = "register" | "login" | "password_reset";

type SuccessEnvelope<T> = Readonly<{
  success: true;
  data: T;
  request_id: string;
}>;

type ErrorEnvelope = Readonly<{
  success: false;
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
  request_id: string;
}>;

export class AuthApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string;

  constructor(response: Response, payload: ErrorEnvelope) {
    super(payload.error.message || "请求失败，请稍后再试");
    this.name = "AuthApiError";
    this.code = payload.error.code;
    this.status = response.status;
    this.details = payload.error.details;
    this.requestId = payload.request_id;
  }
}

export async function readEnvelope<T>(response: Response): Promise<T> {
  let payload: SuccessEnvelope<T> | ErrorEnvelope;
  try {
    payload = (await response.json()) as SuccessEnvelope<T> | ErrorEnvelope;
  } catch {
    throw new Error("服务响应格式不正确，请稍后再试");
  }
  if (!response.ok || !payload.success) {
    if (!payload.success) {
      throw new AuthApiError(response, payload);
    }
    throw new Error("请求失败，请稍后再试");
  }
  return payload.data;
}

export async function getCsrfToken(): Promise<string> {
  const response = await fetch(`${publicEnvironment.apiBaseUrl}/auth/csrf`, {
    method: "GET",
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  const data = await readEnvelope<{ csrf_token: string }>(response);
  return data.csrf_token;
}

export async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${publicEnvironment.apiBaseUrl}${path}`, {
    method: "GET",
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  return readEnvelope<T>(response);
}

export async function post<T>(
  path: string,
  body: Record<string, unknown>,
  extraHeaders: Readonly<Record<string, string>> = {},
): Promise<T> {
  const csrfToken = await getCsrfToken();
  const response = await fetch(`${publicEnvironment.apiBaseUrl}${path}`, {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
      ...extraHeaders,
    },
    body: JSON.stringify(body),
  });
  return readEnvelope<T>(response);
}

export async function write<T>(
  method: "PATCH" | "PUT",
  path: string,
  body: Record<string, unknown>,
) {
  const csrfToken = await getCsrfToken();
  const response = await fetch(`${publicEnvironment.apiBaseUrl}${path}`, {
    method,
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
    },
    body: JSON.stringify(body),
  });
  return readEnvelope<T>(response);
}
export function sendSms(phone: string, purpose: SmsPurpose) {
  return post<{ sent: true; expires_in: number; resend_after: number }>("/auth/sms/send", {
    phone,
    purpose,
  });
}

export function registerAccount(input: {
  phone: string;
  nickname: string;
  smsCode: string;
  password: string;
}) {
  return post<AccountUser>("/auth/register", {
    phone: input.phone,
    nickname: input.nickname,
    sms_code: input.smsCode,
    password: input.password,
  });
}

export function loginWithPassword(phone: string, password: string) {
  return post<AccountUser>("/auth/login/password", { phone, password });
}

export function loginWithSms(phone: string, smsCode: string) {
  return post<AccountUser>("/auth/login/sms", { phone, sms_code: smsCode });
}

export function resetPassword(input: { phone: string; smsCode: string; newPassword: string }) {
  return post<{ reset: true }>("/auth/password/reset", {
    phone: input.phone,
    sms_code: input.smsCode,
    new_password: input.newPassword,
  });
}
export type AdminUser = Readonly<{
  id: string;
  nickname: string;
  phone_masked: string;
  approval_status: AccountUser["approval_status"];
  account_status: AccountUser["account_status"];
  status_version: number;
  approval_reason?: string | null;
  approved_at: string | null;
  created_at: string;
}>;

export type StatusEvent = Readonly<{
  id: string;
  status_domain: "approval" | "account";
  event_type: "approved" | "rejected" | "resubmitted" | "frozen" | "unfrozen";
  from_value: string;
  to_value: string;
  reason: string;
  actor_id: string | null;
  request_id: string;
  created_at: string;
}>;

export type AccountNotification = Readonly<{
  id: string;
  notification_type:
    | "approval_approved"
    | "approval_rejected"
    | "account_frozen"
    | "account_unfrozen"
    | "plan_application_submitted"
    | "plan_application_contacted"
    | "plan_application_closed"
    | "plan_application_cancelled";
  title: string;
  safe_summary: string;
  read_at: string | null;
  created_at: string;
  related_plan_application_id?: string | null;
}>;

export type PageData<T> = Readonly<{
  results: T[];
  pagination: {
    page: number;
    page_size: number;
    count: number;
    total_pages: number;
  };
}>;

export function getCurrentUser() {
  return get<AccountUser>("/me");
}

export function resubmitApproval(nickname?: string) {
  return post<AccountUser>("/me/approval/resubmit", nickname === undefined ? {} : { nickname });
}

export function getNotifications(page = 1) {
  return get<PageData<AccountNotification>>(`/notifications?page=${page}`);
}

export function markNotificationRead(notificationId: string) {
  return post<AccountNotification>(`/notifications/${notificationId}/read`, {});
}

export function getAdminUsers(params: {
  approvalStatus?: string;
  accountStatus?: string;
  phone?: string;
  page?: number;
}) {
  const query = new URLSearchParams();
  if (params.approvalStatus) query.set("approval_status", params.approvalStatus);
  if (params.accountStatus) query.set("account_status", params.accountStatus);
  if (params.phone) query.set("phone", params.phone);
  query.set("page", String(params.page ?? 1));
  return get<PageData<AdminUser>>(`/admin/users?${query.toString()}`);
}

export function getAdminUser(userId: string) {
  return get<AdminUser>(`/admin/users/${userId}`);
}

export function getAdminUserHistory(userId: string) {
  return get<PageData<StatusEvent>>(`/admin/users/${userId}/history`);
}

export function reviewAdminUser(
  userId: string,
  decision: "approve" | "reject",
  reason = "",
  expectedVersion?: number,
  credentials: { confirmed?: true; current_password?: string } = {},
) {
  return post<AdminUser | import("./risk-client").ApprovalCreated>(
    `/admin/users/${userId}/review`,
    { decision, reason, expected_version: expectedVersion, ...credentials },
  );
}

export function freezeAdminUser(
  userId: string,
  expectedVersion: number,
  credentials: { confirmed: true; current_password: string },
) {
  return post<AdminUser | import("./risk-client").ApprovalCreated>(
    `/admin/users/${userId}/freeze`,
    { expected_version: expectedVersion, ...credentials },
  );
}

export function unfreezeAdminUser(userId: string) {
  return post<AdminUser>(`/admin/users/${userId}/unfreeze`, {});
}

export function userMessage(error: unknown): string {
  if (error instanceof AuthApiError || error instanceof Error) {
    return error.message;
  }
  return "请求失败，请稍后再试";
}
