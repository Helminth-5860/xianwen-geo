// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { getAdminContext } = vi.hoisted(() => ({ getAdminContext: vi.fn() }));
vi.mock("@/lib/admin-rbac-client", () => ({ getAdminContext }));

import { AdminCapabilityProvider } from "../components/admin/admin-capability";
import { AuthApiError } from "../lib/auth-client";

afterEach(() => {
  cleanup();
  getAdminContext.mockReset();
});

describe("管理员 capability 壳层", () => {
  it("403 响应显示明确中文无权限状态", async () => {
    getAdminContext.mockRejectedValueOnce(
      new AuthApiError(new Response(null, { status: 403 }), {
        success: false,
        error: { code: "PERMISSION_DENIED", message: "没有权限执行此操作", details: {} },
        request_id: "00000000-0000-0000-0000-000000000002",
      }),
    );
    render(
      <AdminCapabilityProvider>
        <div>不应展示的后台内容</div>
      </AdminCapabilityProvider>,
    );

    expect(await screen.findByText("无权访问后台")).toBeTruthy();
    expect(screen.getByText("你没有权限查看或操作这项内容。")).toBeTruthy();
    expect(screen.queryByText("没有权限执行此操作")).toBeNull();
    expect(screen.queryByText("不应展示的后台内容")).toBeNull();
  });
});
