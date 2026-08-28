// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { AdminCapabilityContext } from "../components/admin/admin-capability";
import { UserStatusActions } from "../components/admin/user-status-actions";
import type { AdminContext } from "../lib/admin-rbac-client";

const baseContext: AdminContext = {
  id: "00000000-0000-0000-0000-000000000001",
  user_id: "00000000-0000-0000-0000-000000000002",
  nickname: "账号管理员",
  phone_masked: "+86 139****9000",
  is_superuser: false,
  admin_status: "active",
  version: 1,
  logout_version: 1,
  admin_version: 1,
  role: null,
  data_scope: "all",
  permission_keys: [],
  menu_keys: ["menu.admin.users"],
  commercial_identity: "ADMIN",
  tenant_id: null,
  tenant_name: null,
};

function renderActions(permissionKeys: string[], accountStatus: "active" | "frozen" = "active") {
  const handlers = {
    executeFreeze: vi.fn().mockResolvedValue({
      account_status: "frozen",
    }),
    onRiskExecuted: vi.fn(),
    onUnfreeze: vi.fn(),
  };
  render(
    <AdminCapabilityContext.Provider value={{ ...baseContext, permission_keys: permissionKeys }}>
      <UserStatusActions
        user={{ account_status: accountStatus }}
        submitting={false}
        freezeMode="confirm"
        {...handlers}
      />
    </AdminCapabilityContext.Provider>,
  );
  return handlers;
}

beforeAll(() => {
  const nativeGetComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
    nativeGetComputedStyle(element),
  );
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

afterEach(() => cleanup());

describe("用户账号状态 capability", () => {
  it("users.freeze 允许禁用交互", async () => {
    const handlers = renderActions(["users.freeze"]);
    await userEvent.click(screen.getByRole("button", { name: /禁用账号/ }));
    await userEvent.click(screen.getByRole("button", { name: "确认执行" }));

    expect(handlers.executeFreeze).toHaveBeenCalledOnce();
  });

  it("没有 capability 时账号状态动作不可操作并显示中文提示", () => {
    renderActions([]);

    expect(screen.queryByRole("button", { name: /禁用账号/ })).toBeNull();
    expect(screen.getByText("没有账号状态管理权限，禁用和恢复操作不可用")).toBeTruthy();
  });

  it("users.freeze 可恢复账号，且渲染过程不输出完整手机号或敏感响应", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const handlers = renderActions(["users.freeze"], "frozen");
    await userEvent.click(screen.getByRole("button", { name: /恢复账号/ }));

    expect(handlers.onUnfreeze).toHaveBeenCalledOnce();
    expect(consoleSpy.mock.calls.flat().join(" ")).not.toContain("13900139000");
    expect(consoleSpy.mock.calls.flat().join(" ")).not.toContain("Authorization");
    consoleSpy.mockRestore();
  });
});
