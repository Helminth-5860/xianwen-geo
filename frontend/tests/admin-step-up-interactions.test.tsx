// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  handler: null as (() => Promise<void>) | null,
  createChallenge: vi.fn(),
  verify: vi.fn(),
}));

vi.mock("@/lib/auth-client", () => ({
  setAdminStepUpHandler: (handler: (() => Promise<void>) | null) => {
    mocks.handler = handler;
  },
  userMessage: (reason: unknown) => (reason instanceof Error ? reason.message : "请求失败"),
}));

vi.mock("@/lib/admin-rbac-client", () => ({
  createAdminStepUpChallenge: mocks.createChallenge,
  verifyAdminStepUp: mocks.verify,
}));

import { AdminStepUpProvider } from "../components/admin/admin-step-up";

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  const nativeGetComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
    nativeGetComputedStyle(element),
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  mocks.handler = null;
  localStorage.clear();
  sessionStorage.clear();
});

describe("管理员高风险 Step-Up", () => {
  it("只在受保护操作请求时发送短信，验证后从内存继续原请求", async () => {
    mocks.createChallenge.mockResolvedValueOnce({
      challenge_id: "opaque-memory-challenge",
      sent: true,
      expires_in: 300,
      resend_after: 60,
    });
    mocks.verify.mockResolvedValueOnce({ verified: true, expires_in: 300 });
    const user = userEvent.setup();
    render(
      <AdminStepUpProvider>
        <div>普通后台内容</div>
      </AdminStepUpProvider>,
    );

    expect(await screen.findByText("普通后台内容")).toBeTruthy();
    expect(mocks.createChallenge).not.toHaveBeenCalled();
    let verification!: Promise<void>;
    await act(async () => {
      verification = mocks.handler!();
    });
    expect(await screen.findByText("高风险操作安全验证")).toBeTruthy();
    expect(mocks.createChallenge).toHaveBeenCalledTimes(1);
    expect(location.href).not.toContain("opaque-memory-challenge");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);

    await user.type(screen.getByLabelText("高风险操作短信验证码"), "618294");
    await user.click(screen.getByRole("button", { name: "验证并继续" }));
    await verification;
    await waitFor(() =>
      expect(mocks.verify).toHaveBeenCalledWith("opaque-memory-challenge", "618294"),
    );
    expect(screen.queryByText("高风险操作安全验证")).toBeNull();
  });

  it("错误验证码保留对话框且不会授予前端 proof", async () => {
    mocks.createChallenge.mockResolvedValueOnce({
      challenge_id: "opaque-wrong-code",
      sent: true,
      expires_in: 300,
      resend_after: 60,
    });
    mocks.verify.mockRejectedValueOnce(new Error("管理员安全验证无效，请重新开始"));
    const user = userEvent.setup();
    render(<AdminStepUpProvider>后台</AdminStepUpProvider>);

    await act(async () => {
      void mocks.handler!().catch(() => undefined);
    });
    await user.type(await screen.findByLabelText("高风险操作短信验证码"), "000000");
    await user.click(screen.getByRole("button", { name: "验证并继续" }));
    expect(await screen.findByText("管理员安全验证无效，请重新开始")).toBeTruthy();
    expect(screen.getByText("高风险操作安全验证")).toBeTruthy();
    expect(localStorage.length).toBe(0);
  });
});
