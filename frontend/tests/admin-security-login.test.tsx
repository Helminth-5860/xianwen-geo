// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const { adminLoginWithPassword, push } = vi.hoisted(() => ({
  adminLoginWithPassword: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/admin-rbac-client", () => ({
  adminLoginWithPassword,
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

describe("管理员密码登录", () => {
  it("密码有效时直接建立后台会话且不展示短信步骤", async () => {
    adminLoginWithPassword.mockResolvedValueOnce({
      requires_2fa: false,
      user: { home_route: "/admin" },
    });
    render(<AdminLoginPage />);

    fireEvent.change(screen.getByLabelText("手机号"), { target: { value: "13900139000" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Safe-password" } });
    fireEvent.click(screen.getByRole("button", { name: "登录后台" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin"));
    expect(screen.queryByLabelText("短信验证码")).toBeNull();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("密码失败时保留在登录页并显示安全错误", async () => {
    adminLoginWithPassword.mockRejectedValueOnce(new Error("手机号或密码不正确"));
    render(<AdminLoginPage />);
    fireEvent.change(screen.getByLabelText("手机号"), { target: { value: "13700137000" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "登录后台" }));
    expect(await screen.findByText("手机号或密码不正确")).toBeTruthy();
    expect(push).not.toHaveBeenCalled();
  });
});
