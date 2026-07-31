// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminCapabilityContext } from "../components/admin/admin-capability";
import { UserStatusActions } from "../components/admin/user-status-actions";
import type { AdminContext } from "../lib/admin-rbac-client";

const baseContext: AdminContext = {
  id: "00000000-0000-0000-0000-000000000001",
  nickname: "审核管理员",
  phone_masked: "+86 139****9000",
  is_superuser: false,
  admin_status: "active",
  version: 1,
  admin_version: 1,
  role: null,
  data_scope: "all",
  permission_keys: [],
  menu_keys: ["menu.admin.users"],
};

function renderActions(permissionKeys: string[], accountStatus: "active" | "frozen" = "active") {
  const handlers = {
    onApprove: vi.fn(),
    onReject: vi.fn(),
    onFreeze: vi.fn(),
    onUnfreeze: vi.fn(),
  };
  render(
    <AdminCapabilityContext.Provider value={{ ...baseContext, permission_keys: permissionKeys }}>
      <UserStatusActions
        user={{ approval_status: "pending", account_status: accountStatus }}
        submitting={false}
        {...handlers}
      />
    </AdminCapabilityContext.Provider>,
  );
  return handlers;
}

afterEach(() => cleanup());

describe("XW-0104 用户操作 capability", () => {
  it("users.review 允许审核交互，但不能隐式获得冻结权限", async () => {
    const handlers = renderActions(["users.review"]);
    await userEvent.click(screen.getByRole("button", { name: /通过审核/ }));
    await userEvent.click(screen.getByRole("button", { name: /拒绝审核/ }));

    expect(handlers.onApprove).toHaveBeenCalledOnce();
    expect(handlers.onReject).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /冻结账号/ })).toBeNull();
    expect(screen.getByText("没有账号冻结权限，冻结和解冻操作不可用")).toBeTruthy();
  });

  it("users.freeze 允许冻结交互，但不能隐式获得审核权限", async () => {
    const handlers = renderActions(["users.freeze"]);
    await userEvent.click(screen.getByRole("button", { name: /冻结账号/ }));

    expect(handlers.onFreeze).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /通过审核/ })).toBeNull();
    expect(screen.getByText("没有用户审核权限，审核操作不可用")).toBeTruthy();
  });

  it("没有 capability 时所有敏感动作均不可操作并显示中文提示", () => {
    renderActions([]);

    expect(screen.queryByRole("button", { name: /通过审核|拒绝审核|冻结账号/ })).toBeNull();
    expect(screen.getByText("没有用户审核权限，审核操作不可用")).toBeTruthy();
    expect(screen.getByText("没有账号冻结权限，冻结和解冻操作不可用")).toBeTruthy();
  });

  it("users.freeze 可操作解冻，且渲染过程不输出完整手机号或敏感响应", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const handlers = renderActions(["users.freeze"], "frozen");
    await userEvent.click(screen.getByRole("button", { name: /解冻账号/ }));

    expect(handlers.onUnfreeze).toHaveBeenCalledOnce();
    expect(consoleSpy.mock.calls.flat().join(" ")).not.toContain("13900139000");
    expect(consoleSpy.mock.calls.flat().join(" ")).not.toContain("Authorization");
    consoleSpy.mockRestore();
  });
});
