// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

describe("公开注册页", () => {
  it("缺少 ref 时允许独立注册且不请求邀请验证", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<RegisterPage />);

    expect(await screen.findByText("无需邀请，完成验证即可注册独立用户。")).toBeTruthy();
    expect((screen.getByRole("button", { name: "注册并登录" }) as HTMLButtonElement).disabled).toBe(
      false,
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

    expect(await screen.findByText("注册后将关联管理员：代理甲")).toBeTruthy();
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "注册并登录" }) as HTMLButtonElement).disabled,
      ).toBe(false),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("无效 ref 显示提示但仍允许独立注册", async () => {
    window.history.replaceState({}, "", "/register?ref=invalid");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse(
        {
          success: false,
          error: { code: "VALIDATION_ERROR", message: "无效邀请", details: {} },
          request_id: "r-invalid",
        },
        422,
      ),
    );

    render(<RegisterPage />);

    expect(await screen.findByText("邀请或推荐关系已失效")).toBeTruthy();
    expect((screen.getByRole("button", { name: "注册并登录" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("注册校验失败时直接显示后端返回的中文字段原因", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ success: true, data: { csrf_token: "csrf-register" }, request_id: "r1" }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            success: false,
            error: {
              code: "VALIDATION_ERROR",
              message: "请求参数不正确",
              details: {
                fields: {
                  password: [{ message: "这个密码太常见了。", code: "password_too_common" }],
                },
              },
            },
            request_id: "r2",
          },
          422,
        ),
      );
    const user = userEvent.setup();

    render(<RegisterPage />);
    await user.type(screen.getByLabelText("手机号"), "13800138000");
    await user.type(screen.getByLabelText("昵称"), "体验用户");
    await user.type(screen.getByLabelText("短信验证码"), "438921");
    await user.type(screen.getByLabelText("设置密码"), "Correct-Horse-Battery-2026!");
    await user.type(screen.getByLabelText("确认密码"), "Correct-Horse-Battery-2026!");
    await user.click(screen.getByRole("button", { name: "注册并登录" }));

    expect(await screen.findByText("密码：这个密码太常见了。")).toBeTruthy();
    expect(screen.queryByText("请求参数不正确")).toBeNull();
  });
});
