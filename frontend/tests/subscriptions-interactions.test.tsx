// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import AdminSubscriptionDetailPage from "../app/admin/subscriptions/[id]/page";
import AdminSubscriptionsPage from "../app/admin/subscriptions/page";
import CurrentSubscriptionPage from "../app/subscription/page";
import QuotaUsagePage from "../app/subscription/usage/page";
import { TrialGrantAction } from "../components/admin/trial-grant-action";
import { AdminCapabilityContext } from "../components/admin/admin-capability";

const getCurrentSubscription = vi.fn();
const getPublicPlans = vi.fn();
const getAdminSubscriptions = vi.fn();
const getAdminSubscription = vi.fn();
const terminateSubscription = vi.fn();
const grantTrialSubscription = vi.fn();
const getCurrentQuotaAccounts = vi.fn();
const getUserQuotaLedger = vi.fn();
const getCurrentUser = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "subscription-1" }),
  usePathname: () => "/admin/subscriptions/subscription-1",
}));
vi.mock("../lib/plans-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/plans-client")>("../lib/plans-client");
  return {
    ...actual,
    getCurrentSubscription: (...args: unknown[]) => getCurrentSubscription(...args),
    getPublicPlans: (...args: unknown[]) => getPublicPlans(...args),
    getAdminSubscriptions: (...args: unknown[]) => getAdminSubscriptions(...args),
    getAdminSubscription: (...args: unknown[]) => getAdminSubscription(...args),
    grantTrialSubscription: (...args: unknown[]) => grantTrialSubscription(...args),
    terminateSubscription: (...args: unknown[]) => terminateSubscription(...args),
  };
});
vi.mock("../lib/auth-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/auth-client")>("../lib/auth-client");
  return {
    ...actual,
    getCurrentUser: (...args: unknown[]) => getCurrentUser(...args),
  };
});
vi.mock("../lib/quota-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/quota-client")>("../lib/quota-client");
  return {
    ...actual,
    getCurrentQuotaAccounts: (...args: unknown[]) => getCurrentQuotaAccounts(...args),
    getUserQuotaLedger: (...args: unknown[]) => getUserQuotaLedger(...args),
  };
});

const subscription = {
  id: "subscription-1",
  user_id: "user-1",
  user_nickname: "订阅用户",
  plan_id: "plan-1",
  plan_code: "standard",
  plan_name: "标准套餐",
  plan_version_id: "version-1",
  plan_version_no: 2,
  status: "active" as const,
  source_type: "application" as const,
  is_trial: false,
  starts_at: "2026-08-01T00:00:00Z",
  ends_at: "2026-09-01T00:00:00Z",
  cycle_anchor_day: 1,
  cycle_anchor_time: "08:00:00",
  entitlement_summary: {
    valid_days: 31,
    limit_keys: ["subject_active_limit"],
    enabled_model_keys: ["deepseek" as const],
  },
  version: 1,
  events: [],
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
});
beforeEach(() => {
  getCurrentUser.mockResolvedValue({ id: "user-1" });
  getCurrentSubscription.mockResolvedValue({ current: subscription });
  getPublicPlans.mockResolvedValue([
    {
      id: "plan-1",
      code: "standard",
      name: "标准套餐",
      description: "适合日常使用",
      price_display_mode: "fixed",
      display_price: "1980.00",
      display_currency: "CNY",
      is_trial: false,
      valid_days: 365,
      benefits: {},
      models: [],
      supports_formal_composite: true,
      sort_order: 1,
      plan_version_id: "version-1",
      version_no: 2,
    },
  ]);
  getAdminSubscriptions.mockResolvedValue({
    results: [subscription],
    pagination: { page: 1, page_size: 20, count: 1, total_pages: 1 },
  });
  getAdminSubscription.mockResolvedValue(subscription);
  grantTrialSubscription.mockResolvedValue({
    subscription_id: "subscription-trial",
    status: "active",
  });
  terminateSubscription.mockResolvedValue({
    subscription_id: "subscription-1",
    status: "terminated",
    version: 2,
  });
  getCurrentQuotaAccounts.mockResolvedValue({ accounts: [] });
  getUserQuotaLedger.mockResolvedValue({
    results: [],
    pagination: { page: 1, page_size: 20, count: 0, total_pages: 0 },
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("订阅页面真实交互", () => {
  it("用户当前订阅只渲染安全摘要且支持 current null", async () => {
    const { unmount } = render(<CurrentSubscriptionPage />);
    expect(await screen.findByText("标准套餐")).toBeTruthy();
    expect(screen.queryByText(/entitlement_snapshot|digest|内部备注/)).toBeNull();
    unmount();
    getCurrentSubscription.mockResolvedValue({ current: null });
    render(<CurrentSubscriptionPage />);
    expect(await screen.findByText("当前尚未开通套餐")).toBeTruthy();
  });

  it("客户套餐页只展示自然额度、检测限制和独立记录入口", async () => {
    getCurrentSubscription.mockResolvedValue({
      current: {
        ...subscription,
        plan_code: "professional-6980",
        plan_name: "专业版",
        ends_at: "2027-08-01T00:00:00Z",
      },
    });
    getCurrentQuotaAccounts.mockResolvedValue({
      accounts: [
        {
          quota_type: "geo_detection_runs",
          display_name: "GEO 检测",
          unit: "run",
          scope: "subscription",
          entitlement_amount: 60,
          available: 42,
          frozen: 0,
        },
        {
          quota_type: "assistant_messages",
          display_name: "AI 助手消息",
          unit: "message",
          scope: "account_cycle",
          entitlement_amount: 100,
          available: 99,
          frozen: 0,
        },
      ],
    });
    getUserQuotaLedger.mockResolvedValue({
      results: [
        {
          id: "ledger-1",
          quota_type: "geo_detection_runs",
          action: "consume",
          available_before: 43,
          available_delta: -1,
          available_after: 42,
          balance_before: 43,
          balance_after: 42,
          frozen_delta: -1,
          frozen_after: 0,
          description: "完成一次正式检测",
          related_object: "品牌检测",
          created_at: "2026-08-31T13:20:00Z",
        },
      ],
      pagination: { page: 1, page_size: 20, count: 1, total_pages: 1 },
    });

    render(<CurrentSubscriptionPage />);
    expect(await screen.findByText("¥6,980")).toBeTruthy();
    expect(await screen.findByText("已用 18 / 60 次")).toBeTruthy();
    expect(screen.getByText("剩余 42 次")).toBeTruthy();
    expect(screen.getByText("单次最多 20 个问题 × 8 个模型")).toBeTruthy();
    expect(screen.getByRole("link", { name: "查看额度使用记录 →" }).getAttribute("href")).toBe(
      "/subscription/usage",
    );
    expect(screen.queryByText("完成一次正式检测")).toBeNull();
    expect(getUserQuotaLedger).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toMatch(
      /assistant_messages|AI 助手消息|detection_points/,
    );
  });

  it("独立额度使用记录使用业务余额并隐藏技术初始化信息", async () => {
    getUserQuotaLedger.mockResolvedValue({
      results: [
        {
          id: "ledger-1",
          quota_type: "geo_detection_runs",
          action: "consume",
          amount: 1,
          available_before: 19,
          available_delta: 0,
          available_after: 19,
          balance_before: 20,
          balance_after: 19,
          frozen_delta: -1,
          frozen_after: 0,
          description: "完成一次正式检测",
          related_object: "品牌检测",
          created_at: "2026-08-31T13:20:00Z",
        },
        {
          id: "ledger-internal",
          quota_type: "geo_detection_runs",
          action: "initialize",
          amount: 60,
          available_before: 0,
          available_delta: 60,
          available_after: 60,
          frozen_delta: 0,
          frozen_after: 0,
          description: "套餐初始化",
          created_at: "2026-08-01T00:00:00Z",
        },
      ],
      pagination: { page: 1, page_size: 20, count: 2, total_pages: 1 },
    });

    render(<QuotaUsagePage />);
    const description = await screen.findByText("完成一次正式检测");
    const row = description.closest("tr");
    expect(row).toBeTruthy();
    expect(within(row as HTMLTableRowElement).getByText("消耗 1 次")).toBeTruthy();
    expect(within(row as HTMLTableRowElement).getByText("20")).toBeTruthy();
    expect(within(row as HTMLTableRowElement).getByText("19")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/套餐初始化|migration|provisioning/);
  });

  it("不限额度只显示产品文案而不显示内部大整数", async () => {
    getCurrentQuotaAccounts.mockResolvedValue({
      accounts: [
        {
          quota_type: "article_generations",
          display_name: "AI 文章",
          unit: "article",
          scope: "subscription",
          entitlement_amount: 9_223_372_036_854_776_000,
          available: 9_223_372_036_854_776_000,
          frozen: 0,
          used_amount: 0,
        },
      ],
    });

    render(<CurrentSubscriptionPage />);
    expect((await screen.findAllByText("不限")).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/922337|MAX_INT|sentinel/i);
  });

  it("管理员列表筛选并进入数据范围内详情", async () => {
    render(<AdminSubscriptionsPage />);
    expect(await screen.findByText("订阅用户")).toBeTruthy();
    await userEvent.click(screen.getByLabelText("订阅状态"));
    await userEvent.click(await screen.findByText("已终止"));
    await waitFor(() => expect(getAdminSubscriptions).toHaveBeenCalledWith("terminated"));
    expect(screen.getByRole("link", { name: "查看" }).getAttribute("href")).toBe(
      "/admin/subscriptions/subscription-1",
    );
  });

  it("有终止权限时二次确认后直接终止", async () => {
    const context = { permission_keys: ["subscriptions.terminate"], menu_keys: [] } as never;
    render(
      <AdminCapabilityContext.Provider value={context}>
        <AdminSubscriptionDetailPage />
      </AdminCapabilityContext.Provider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "终止订阅" }));
    await userEvent.type(screen.getByLabelText("终止原因"), "客户书面申请终止");
    await userEvent.click(screen.getByRole("button", { name: "确认终止" }));
    await waitFor(() =>
      expect(terminateSubscription).toHaveBeenCalledWith("subscription-1", 1, "客户书面申请终止"),
    );
    expect(document.body.textContent).not.toMatch(/审批|approval-terminate/);
  });

  it("无终止权限时不渲染动作并给出中文提示", async () => {
    const context = { permission_keys: [], menu_keys: [] } as never;
    render(
      <AdminCapabilityContext.Provider value={context}>
        <AdminSubscriptionDetailPage />
      </AdminCapabilityContext.Provider>,
    );
    expect(await screen.findByText("当前账号没有终止订阅权限")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "终止订阅" })).toBeNull();
  });

  it("有试用权限时仅提交 plan_id 和备注并直接发放", async () => {
    const onCompleted = vi.fn();
    const onError = vi.fn();
    const context = { permission_keys: ["subscriptions.grant_trial"], menu_keys: [] } as never;
    render(
      <AdminCapabilityContext.Provider value={context}>
        <TrialGrantAction
          userId="user-1"
          expectedVersion={3}
          onCompleted={onCompleted}
          onError={onError}
        />
      </AdminCapabilityContext.Provider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "发放试用套餐" }));
    await userEvent.type(screen.getByLabelText("试用套餐 ID"), "plan-trial-1");
    await userEvent.type(screen.getByLabelText("试用发放备注"), "人工审核后发放");
    await userEvent.click(screen.getByRole("button", { name: "确认发放" }));
    await waitFor(() =>
      expect(grantTrialSubscription).toHaveBeenCalledWith(
        "user-1",
        3,
        "plan-trial-1",
        "人工审核后发放",
      ),
    );
    expect(onCompleted).toHaveBeenCalledOnce();
    expect(onError).not.toHaveBeenCalled();
  });

  it("无试用权限时不显示发放按钮并给出中文提示", () => {
    const context = { permission_keys: [], menu_keys: [] } as never;
    render(
      <AdminCapabilityContext.Provider value={context}>
        <TrialGrantAction
          userId="user-1"
          expectedVersion={3}
          onCompleted={vi.fn()}
          onError={vi.fn()}
        />
      </AdminCapabilityContext.Provider>,
    );
    expect(screen.getByText("当前账号没有发放试用套餐权限")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "发放试用套餐" })).toBeNull();
  });
});
