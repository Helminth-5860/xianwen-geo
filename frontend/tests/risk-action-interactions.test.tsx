// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { RiskActionButton } from "../components/admin/risk-action-button";

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

afterEach(cleanup);

describe("高风险动作交互", () => {
  it("confirm 模式显式确认后执行", async () => {
    const execute = vi.fn().mockResolvedValue({ done: true });
    const onExecuted = vi.fn();
    render(
      <RiskActionButton
        actionName="冻结用户"
        mode="confirm"
        execute={execute}
        onExecuted={onExecuted}
        onApproval={vi.fn()}
      >
        冻结
      </RiskActionButton>,
    );

    await userEvent.click(screen.getByRole("button", { name: /冻\s*结/ }));
    expect(screen.getByText("确认后立即执行")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "确认执行" }));

    await waitFor(() =>
      expect(execute).toHaveBeenCalledWith({ confirmed: true, current_password: "", reason: "" }),
    );
    expect(onExecuted).toHaveBeenCalledWith({ done: true });
  });

  it("password 模式要求当前密码且只保存在组件内存", async () => {
    const execute = vi.fn().mockResolvedValue({ done: true });
    render(
      <RiskActionButton
        actionName="锁定管理员"
        mode="password"
        execute={execute}
        onExecuted={vi.fn()}
        onApproval={vi.fn()}
      >
        锁定
      </RiskActionButton>,
    );

    await userEvent.click(screen.getByRole("button", { name: /锁\s*定/ }));
    await userEvent.click(screen.getByRole("button", { name: "确认执行" }));
    expect(screen.getByText("请输入当前登录密码")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("当前登录密码"), "temporary-password");
    await userEvent.click(screen.getByRole("button", { name: "确认执行" }));

    await waitFor(() =>
      expect(execute).toHaveBeenCalledWith({
        confirmed: true,
        current_password: "temporary-password",
        reason: "",
      }),
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("two_person 模式显示第二审批人提示并返回最小请求编号", async () => {
    const onApproval = vi.fn();
    const execute = vi.fn().mockResolvedValue({
      approval_required: true,
      approval_id: "approval-1",
      status: "pending",
      expires_at: "2026-08-02T00:00:00Z",
    });
    render(
      <RiskActionButton
        actionName="停用管理员"
        mode="two_person"
        execute={execute}
        onExecuted={vi.fn()}
        onApproval={onApproval}
      >
        停用
      </RiskActionButton>,
    );

    await userEvent.click(screen.getByRole("button", { name: /停\s*用/ }));
    expect(screen.getByText(/另一名有效超级管理员审批/)).toBeTruthy();
    expect(screen.getByText(/没有第二名当前有效超级管理员/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "发起审批" }));

    await waitFor(() =>
      expect(onApproval).toHaveBeenCalledWith(
        expect.objectContaining({ approval_id: "approval-1" }),
      ),
    );
  });
});
