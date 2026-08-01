// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const { adminLoginWithPassword, sendAdminLoginSms, verifyAdminLoginSms, push } = vi.hoisted(() => ({
  adminLoginWithPassword: vi.fn(),
  sendAdminLoginSms: vi.fn(),
  verifyAdminLoginSms: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/admin-rbac-client", () => ({
  adminLoginWithPassword,
  sendAdminLoginSms,
  verifyAdminLoginSms,
}));

import AdminLoginPage from "../app/admin/login/page";

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("管理员两阶段登录", () => {
  it("challenge 只停留在组件内存并完成密码加短信流程", async () => {
    adminLoginWithPassword.mockResolvedValueOnce({
      requires_2fa: true,
      challenge_id: "opaque-memory-only-challenge",
      expires_in: 300,
    });
    sendAdminLoginSms.mockResolvedValueOnce({ sent: true, expires_in: 300, resend_after: 60 });
    verifyAdminLoginSms.mockResolvedValueOnce({});
    render(<AdminLoginPage />);

    fireEvent.change(screen.getByLabelText("手机号"), { target: { value: "13900139000" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Safe-password" } });
    fireEvent.click(screen.getByRole("button", { name: "继续安全验证" }));

    expect(await screen.findByLabelText("短信验证码")).toBeTruthy();
    expect(sendAdminLoginSms).toHaveBeenCalledWith("opaque-memory-only-challenge");
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(window.location.href).not.toContain("opaque-memory-only-challenge");

    fireEvent.change(screen.getByLabelText("短信验证码"), { target: { value: "618294" } });
    fireEvent.click(screen.getByRole("button", { name: "完成登录" }));

    await waitFor(() =>
      expect(verifyAdminLoginSms).toHaveBeenCalledWith("opaque-memory-only-challenge", "618294"),
    );
    expect(push).toHaveBeenCalledWith("/admin");
  });

  it("无需 2FA 的普通角色直接进入后台", async () => {
    adminLoginWithPassword.mockResolvedValueOnce({ requires_2fa: false, user: {} });
    render(<AdminLoginPage />);
    fireEvent.change(screen.getByLabelText("手机号"), { target: { value: "13700137000" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Safe-password" } });
    fireEvent.click(screen.getByRole("button", { name: "继续安全验证" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin"));
    expect(sendAdminLoginSms).not.toHaveBeenCalled();
  });
});
