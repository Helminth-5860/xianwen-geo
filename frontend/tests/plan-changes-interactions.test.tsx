// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import AdminSubscriptionChangeDetailPage from "../app/admin/subscription-changes/[id]/page";
import { AdminCapabilityContext } from "../components/admin/admin-capability";
import { SubscriptionChangeAction } from "../components/admin/subscription-change-action";
import { SubscriptionChangeHistory } from "../components/subscription-change-history";

const previewSubscriptionChange = vi.fn();
const requestSubscriptionChange = vi.fn();
const getAdminSubscriptionChange = vi.fn();
const cancelSubscriptionChange = vi.fn();
const getUserSubscriptionChanges = vi.fn();

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "change-1" }) }));
vi.mock("../lib/plans-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/plans-client")>("../lib/plans-client");
  return {
    ...actual,
    previewSubscriptionChange: (...args: unknown[]) => previewSubscriptionChange(...args),
    requestSubscriptionChange: (...args: unknown[]) => requestSubscriptionChange(...args),
    getAdminSubscriptionChange: (...args: unknown[]) => getAdminSubscriptionChange(...args),
    cancelSubscriptionChange: (...args: unknown[]) => cancelSubscriptionChange(...args),
    getUserSubscriptionChanges: (...args: unknown[]) => getUserSubscriptionChanges(...args),
  };
});

const idempotencyKey = "00000000-0000-4000-8000-000000000114";
const subscription = {
  id: "subscription-1",
  plan_id: "plan-1",
  plan_code: "standard",
  plan_name: "标准套餐",
  plan_version_id: "version-1",
  plan_version_no: 1,
  status: "active" as const,
  source_type: "application" as const,
  is_trial: false,
  starts_at: "2026-08-01T00:00:00Z",
  ends_at: "2026-09-01T00:00:00Z",
  cycle_anchor_day: 1,
  cycle_anchor_time: "08:00:00",
  entitlement_summary: { valid_days: 31, limit_keys: [], enabled_model_keys: [] },
  version: 2,
};
const change = {
  id: "change-1",
  from_subscription_id: "subscription-1",
  target_plan_id: "plan-2",
  target_plan_name: "专业套餐",
  target_plan_version_id: "version-2",
  target_plan_version_no: 3,
  status: "scheduled" as const,
  change_type: "renewal" as const,
  quota_policy: "retain" as const,
  effective_at: "2026-09-01T00:00:00Z",
  executed_at: null,
  cancelled_at: null,
  failed_at: null,
  stable_error_code: "",
  version: 1,
  created_at: "2026-08-02T00:00:00Z",
};

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
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: () => ({
      matches: false,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
  Object.defineProperty(globalThis.crypto, "randomUUID", {
    configurable: true,
    value: vi.fn(() => idempotencyKey),
  });
});

beforeEach(() => {
  previewSubscriptionChange.mockResolvedValue({
    change_type: "upgrade",
    target_plan_id: "plan-2",
    target_plan_version_id: "version-2",
    source_plan_version_no: 1,
    target_plan_version_no: 3,
    quota_policy: "retain",
    effective_at: "2026-08-02T00:00:00Z",
    ends_at: "2026-09-01T00:00:00Z",
    cycle_anchor_time: "08:00:00",
    cycle_anchor_day: 1,
    unavailable_confirmation_required: false,
    changed_limit_keys: ["article_generation"],
    added_model_keys: [],
    removed_model_keys: [],
  });
  requestSubscriptionChange.mockResolvedValue({
    change_id: "change-1",
    status: "scheduled",
    change_type: "renewal",
    effective_at: "2026-09-01T00:00:00Z",
    version: 1,
  });
  getAdminSubscriptionChange.mockResolvedValue(change);
  cancelSubscriptionChange.mockResolvedValue({
    change_id: "change-1",
    status: "cancelled",
    version: 2,
  });
  getUserSubscriptionChanges.mockResolvedValue({ results: [change] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("套餐变更真实交互", () => {
  it("具备权限时先预览服务端分类再用内存幂等键直接变更", async () => {
    const onCompleted = vi.fn();
    const onError = vi.fn();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    render(
      <AdminCapabilityContext.Provider
        value={{ permission_keys: ["subscriptions.change"], menu_keys: [] } as never}
      >
        <SubscriptionChangeAction
          subscription={subscription}
          onCompleted={onCompleted}
          onError={onError}
        />
      </AdminCapabilityContext.Provider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "变更套餐" }));
    await userEvent.type(screen.getByLabelText("目标套餐版本 ID"), "version-2");
    await userEvent.click(screen.getByLabelText("额度迁移策略"));
    await userEvent.click(await screen.findByText("保留为独立到期批次"));
    await userEvent.click(screen.getByRole("button", { name: "预览变更" }));
    expect(await screen.findByText("服务端分类：upgrade")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("套餐变更原因"), "客户确认升级专业套餐");
    await userEvent.click(screen.getByRole("button", { name: "确认变更" }));

    await waitFor(() =>
      expect(requestSubscriptionChange).toHaveBeenCalledWith(
        "subscription-1",
        expect.objectContaining({
          expectedVersion: 2,
          targetPlanVersionId: "version-2",
          quotaPolicy: "retain",
          reason: "客户确认升级专业套餐",
        }),
        idempotencyKey,
      ),
    );
    expect(onCompleted).toHaveBeenCalledOnce();
    expect(onError).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
    expect(window.location.href).not.toContain(idempotencyKey);
    setItem.mockRestore();
  });

  it("没有 capability 时变更操作不可用", () => {
    render(
      <AdminCapabilityContext.Provider value={{ permission_keys: [], menu_keys: [] } as never}>
        <SubscriptionChangeAction
          subscription={subscription}
          onCompleted={vi.fn()}
          onError={vi.fn()}
        />
      </AdminCapabilityContext.Provider>,
    );
    expect(screen.getByText("当前账号没有变更套餐权限")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "变更套餐" })).toBeNull();
  });

  it("服务端 403 使用明确中文错误且不泄漏敏感响应", async () => {
    previewSubscriptionChange.mockRejectedValue(new Error("没有权限执行套餐变更"));
    const onError = vi.fn();
    render(
      <AdminCapabilityContext.Provider
        value={{ permission_keys: ["subscriptions.change"], menu_keys: [] } as never}
      >
        <SubscriptionChangeAction
          subscription={subscription}
          onCompleted={vi.fn()}
          onError={onError}
        />
      </AdminCapabilityContext.Provider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "变更套餐" }));
    await userEvent.type(screen.getByLabelText("目标套餐版本 ID"), "version-2");
    await userEvent.click(screen.getByRole("button", { name: "预览变更" }));
    await waitFor(() => expect(onError).toHaveBeenCalledWith("没有权限执行套餐变更"));
    expect(document.body.textContent).not.toMatch(/Cookie|Idempotency-Key|request_digest/);
  });

  it("scheduled 变更可通过独立幂等键确认后直接取消", async () => {
    render(
      <AdminCapabilityContext.Provider
        value={{ permission_keys: ["subscriptions.change"], menu_keys: [] } as never}
      >
        <AdminSubscriptionChangeDetailPage />
      </AdminCapabilityContext.Provider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "取消排期" }));
    await userEvent.type(screen.getByLabelText("取消排期原因"), "客户撤销续费计划");
    await userEvent.click(screen.getByRole("button", { name: "确认取消" }));
    await waitFor(() =>
      expect(cancelSubscriptionChange).toHaveBeenCalledWith(
        "change-1",
        1,
        "客户撤销续费计划",
        idempotencyKey,
      ),
    );
    expect(document.body.textContent).not.toMatch(/审批|approval-cancel/);
  });

  it("用户变更记录只展示安全摘要，不暴露内部批次或迁移字段", async () => {
    render(<SubscriptionChangeHistory />);
    expect(await screen.findByText("专业套餐")).toBeTruthy();
    expect(screen.getByText(/调整方式：续费/)).toBeTruthy();
    expect(document.body.textContent).not.toContain("renewal");
    expect(document.body.textContent).not.toMatch(
      /business_id|batch_key|source_account|target_account|request_digest|idempotency/,
    );
  });

  it("failed renewal displays a stable error and cannot be cancelled", async () => {
    getAdminSubscriptionChange.mockResolvedValue({
      ...change,
      status: "failed",
      failed_at: "2026-09-01T00:05:00Z",
      stable_error_code: "RENEWAL_WINDOW_ELAPSED",
    });
    render(
      <AdminCapabilityContext.Provider
        value={{ permission_keys: ["subscriptions.change"], menu_keys: [] } as never}
      >
        <AdminSubscriptionChangeDetailPage />
      </AdminCapabilityContext.Provider>,
    );
    expect(await screen.findByText("RENEWAL_WINDOW_ELAPSED")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "??????" })).toBeNull();
    expect(cancelSubscriptionChange).not.toHaveBeenCalled();
  });
});
