import { publicEnvironment } from "./env";

export type AccountUser = Readonly<{
  id: string;
  nickname: string;
  phone_masked: string;
  approval_status: "pending" | "approved" | "rejected";
  account_status: "active" | "frozen" | "cancel_pending" | "cancelled";
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

async function readEnvelope<T>(response: Response): Promise<T> {
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

async function getCsrfToken(): Promise<string> {
  const response = await fetch(`${publicEnvironment.apiBaseUrl}/auth/csrf`, {
    method: "GET",
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  const data = await readEnvelope<{ csrf_token: string }>(response);
  return data.csrf_token;
}

async function post<T>(path: string, body: Record<string, string>): Promise<T> {
  const csrfToken = await getCsrfToken();
  const response = await fetch(`${publicEnvironment.apiBaseUrl}${path}`, {
    method: "POST",
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

export function userMessage(error: unknown): string {
  if (error instanceof AuthApiError || error instanceof Error) {
    return error.message;
  }
  return "请求失败，请稍后再试";
}
