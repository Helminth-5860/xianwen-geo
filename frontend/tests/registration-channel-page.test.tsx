// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import RegisterPage from "../app/register/page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
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
  window.history.replaceState({}, "", "/register");
  vi.restoreAllMocks();
});

describe("代理专属注册页", () => {
  it("缺少 ref 时拒绝启用注册表单且不请求短信", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<RegisterPage />);

    expect(await screen.findByText("注册链接无效或已过期")).toBeTruthy();
    expect((screen.getByRole("button", { name: "注册并登录" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("后端验证 opaque ref 后显示渠道并启用注册表单", async () => {
    window.history.replaceState({}, "", "/register?ref=opaque%3Asigned%2Bref");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({
        success: true,
        data: { valid: true, channel_name: "代理甲" },
        request_id: "r-ref",
      }),
    );

    render(<RegisterPage />);

    expect(await screen.findByText("已验证代理渠道：代理甲")).toBeTruthy();
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "注册并登录" }) as HTMLButtonElement).disabled,
      ).toBe(false),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
