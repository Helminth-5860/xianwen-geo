import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AuthApiError,
  loginWithSms,
  registerAccount,
  resetPassword,
  sendSms,
} from "../lib/auth-client";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.restoreAllMocks());

describe("集中认证客户端", () => {
  it("所有写请求先获取 CSRF，并统一携带 Cookie 和 X-CSRFToken", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ success: true, data: { csrf_token: "csrf-test-value" }, request_id: "r1" }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          success: true,
          data: { sent: true, expires_in: 300, resend_after: 60 },
          request_id: "r2",
        }),
      );

    await sendSms("13800138000", "register");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "GET", credentials: "include" });
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: "POST",
      credentials: "include",
      headers: expect.objectContaining({ "X-CSRFToken": "csrf-test-value" }),
    });
  });

  it("注册请求不发送确认密码，也不持久化认证令牌", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ success: true, data: { csrf_token: "csrf-register" }, request_id: "r1" }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          success: true,
          data: {
            id: "5d8fc11d-e52d-49db-93c0-eea241dd99e6",
            nickname: "测试用户",
            phone_masked: "+86 138****8000",
            approval_status: "pending",
            account_status: "active",
          },
          request_id: "r2",
        }),
      );

    await registerAccount({
      phone: "13800138000",
      nickname: "测试用户",
      smsCode: "438921",
      password: "Correct-Horse-Battery-2026!",
    });

    const requestBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(requestBody).toEqual({
      phone: "13800138000",
      nickname: "测试用户",
      sms_code: "438921",
      password: "Correct-Horse-Battery-2026!",
    });
    expect(requestBody).not.toHaveProperty("passwordConfirmation");
  });

  it("解析统一中文错误且不打印请求正文", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const consoleLog = vi.spyOn(console, "log").mockImplementation(() => undefined);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ success: true, data: { csrf_token: "csrf-error" }, request_id: "r1" }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            success: false,
            error: {
              code: "AUTH_CREDENTIALS_INVALID",
              message: "手机号或短信验证码不正确",
              details: {},
            },
            request_id: "r2",
          },
          401,
        ),
      );

    await expect(loginWithSms("13800138000", "438921")).rejects.toMatchObject({
      code: "AUTH_CREDENTIALS_INVALID",
      status: 401,
    } satisfies Partial<AuthApiError>);
    expect(consoleError).not.toHaveBeenCalled();
    expect(consoleLog).not.toHaveBeenCalled();
  });

  it("密码重置使用冻结的字段名", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ success: true, data: { csrf_token: "csrf-reset" }, request_id: "r1" }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ success: true, data: { reset: true }, request_id: "r2" }),
      );

    await resetPassword({
      phone: "13800138000",
      smsCode: "438921",
      newPassword: "New-Correct-Horse-2027!",
    });

    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      phone: "13800138000",
      sms_code: "438921",
      new_password: "New-Correct-Horse-2027!",
    });
  });
});
