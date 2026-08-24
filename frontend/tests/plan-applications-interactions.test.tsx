// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import AdminPlanApplicationDetailPage from "../app/admin/plan-applications/[id]/page";
import PlanApplicationsPage from "../app/plan-applications/page";
import { AdminCapabilityContext } from "../components/admin/admin-capability";
import { PlanCatalog } from "../components/plans/plan-catalog";

const getCurrentUser = vi.fn();
const getPublicPlans = vi.fn();
const createPlanApplication = vi.fn();
const getPlanApplications = vi.fn();
const cancelPlanApplication = vi.fn();
const getAdminPlanApplication = vi.fn();
const changeAdminPlanApplication = vi.fn();
const openSubscriptionFromApplication = vi.fn();
const getRiskActions = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "application-1" }),
  usePathname: () => "/admin/plan-applications/application-1",
}));
vi.mock("../lib/auth-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/auth-client")>("../lib/auth-client");
  return { ...actual, getCurrentUser: (...args: unknown[]) => getCurrentUser(...args) };
});
vi.mock("../lib/plans-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/plans-client")>("../lib/plans-client");
  return {
    ...actual,
    getPublicPlans: (...args: unknown[]) => getPublicPlans(...args),
    createPlanApplication: (...args: unknown[]) => createPlanApplication(...args),
    getPlanApplications: (...args: unknown[]) => getPlanApplications(...args),
    cancelPlanApplication: (...args: unknown[]) => cancelPlanApplication(...args),
    getAdminPlanApplication: (...args: unknown[]) => getAdminPlanApplication(...args),
    changeAdminPlanApplication: (...args: unknown[]) => changeAdminPlanApplication(...args),
    openSubscriptionFromApplication: (...args: unknown[]) =>
      openSubscriptionFromApplication(...args),
  };
});
vi.mock("../lib/risk-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/risk-client")>("../lib/risk-client");
  return { ...actual, getRiskActions: (...args: unknown[]) => getRiskActions(...args) };
});

const plan = {
  id: "plan-1",
  plan_version_id: "version-1",
  version_no: 3,
  code: "standard",
  name: "标准套餐",
  description: "公开说明",
  price_display_mode: "fixed" as const,
  display_price: "99.00",
  display_currency: "CNY" as const,
  is_trial: false,
  valid_days: 30,
  benefits: { subject_active_limit: 3 },
  models: [{ model_key: "deepseek" as const, name: "DeepSeek", selected_by_default: true }],
  supports_formal_composite: true,
  sort_order: 1,
};
const application = {
  id: "application-1",
  plan_id: "plan-1",
  requested_plan_version_id: "version-1",
  requested_version_no: 3,
  public_plan_snapshot: plan,
  status: "pending" as const,
  source: "user_web" as const,
  user_note: "请联系",
  contacted_at: null,
  closed_at: null,
  cancelled_at: null,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  events: [],
};
const adminApplication = {
  ...application,
  applicant_id: "user-1",
  applicant_nickname: "申请用户",
  applicant_phone_masked: "138****8000",
  applicant_phone: "13800138000",
  current_owner: null,
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
  getPublicPlans.mockResolvedValue([plan, { ...plan, id: "trial", is_trial: true }]);
  createPlanApplication.mockResolvedValue(application);
  getPlanApplications.mockResolvedValue({
    results: [application],
    pagination: { page: 1, page_size: 20, count: 1, total_pages: 1 },
  });
  cancelPlanApplication.mockResolvedValue({ ...application, status: "cancelled", version: 2 });
  getAdminPlanApplication.mockResolvedValue(adminApplication);
  getRiskActions.mockResolvedValue([
    { key: "plan_application.contact", current_mode: "confirm" },
    { key: "plan_application.close", current_mode: "password" },
  ]);
  changeAdminPlanApplication.mockResolvedValue({
    ...adminApplication,
    status: "contacted",
    version: 2,
  });
  openSubscriptionFromApplication.mockResolvedValue({
    subscription_id: "subscription-1",
    application_id: "application-1",
    status: "active",
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("套餐申请真实交互", () => {
  it("登录用户通过 Modal 提交绑定版本，试用套餐不出现申请按钮", async () => {
    render(<PlanCatalog />);
    const buttons = await screen.findAllByRole("button", { name: "申请套餐 / 联系开通" });
    expect(buttons).toHaveLength(1);
    expect(screen.getByText("试用由管理员审核后发放")).toBeTruthy();
    await userEvent.click(buttons[0]);
    expect(await screen.findByText("标准套餐 · 第 3 版")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("申请备注"), "请联系");
    await userEvent.click(screen.getByRole("button", { name: "确认申请" }));
    await waitFor(() => expect(createPlanApplication).toHaveBeenCalledTimes(1));
    const [planId, versionId, note, key] = createPlanApplication.mock.calls[0];
    expect([planId, versionId, note]).toEqual(["plan-1", "version-1", "请联系"]);
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    expect(await screen.findByText(/申请编号：application-1/)).toBeTruthy();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("网络重试复用同一个内存幂等键", async () => {
    createPlanApplication
      .mockRejectedValueOnce(new Error("网络暂时不可用"))
      .mockResolvedValueOnce(application);
    render(<PlanCatalog />);
    await userEvent.click(await screen.findByRole("button", { name: "申请套餐 / 联系开通" }));
    await userEvent.click(screen.getByRole("button", { name: "确认申请" }));
    expect(await screen.findByText("网络暂时不可用")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "确认申请" }));
    await waitFor(() => expect(createPlanApplication).toHaveBeenCalledTimes(2));
    expect(createPlanApplication.mock.calls[0][3]).toBe(createPlanApplication.mock.calls[1][3]);
  });

  it("我的申请列表真实触发 expected_version 取消", async () => {
    render(<PlanApplicationsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "取消申请" }));
    await waitFor(() => expect(cancelPlanApplication).toHaveBeenCalledWith("application-1", 1));
  });

  it("管理员 capability 分别控制 contact/close 并走风险确认", async () => {
    const context = {
      permission_keys: ["plan_applications.contact"],
      menu_keys: ["menu.admin.plan-applications"],
    } as never;
    render(
      <AdminCapabilityContext.Provider value={context}>
        <AdminPlanApplicationDetailPage />
      </AdminCapabilityContext.Provider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "标记已联系" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认执行" }));
    await waitFor(() =>
      expect(changeAdminPlanApplication).toHaveBeenCalledWith(
        "application-1",
        "contact",
        1,
        expect.objectContaining({ confirmed: true }),
      ),
    );
    expect(screen.queryByRole("button", { name: "关闭申请" })).toBeNull();
  });

  it("无处理权限时明确提示且不渲染动作", async () => {
    const context = { permission_keys: [], menu_keys: [] } as never;
    render(
      <AdminCapabilityContext.Provider value={context}>
        <AdminPlanApplicationDetailPage />
      </AdminCapabilityContext.Provider>,
    );
    expect(await screen.findByText("当前账号没有处理此申请的权限")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "标记已联系" })).toBeNull();
    expect(screen.queryByRole("button", { name: "关闭申请" })).toBeNull();
  });
  it("subscriptions.open capability 控制开通并在二次确认后直接执行", async () => {
    const context = {
      permission_keys: ["subscriptions.open"],
      menu_keys: ["menu.admin.plan-applications"],
    } as never;
    render(
      <AdminCapabilityContext.Provider value={context}>
        <AdminPlanApplicationDetailPage />
      </AdminCapabilityContext.Provider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "开通订阅" }));
    expect(await screen.findByText("确认开通订阅")).toBeTruthy();
    await userEvent.click(screen.getByLabelText("确认离线套餐或退役版本仍需开通"));
    await userEvent.type(screen.getByLabelText("特殊状态开通原因"), "客户已书面确认");
    await userEvent.click(screen.getByRole("button", { name: "确认开通" }));
    await waitFor(() =>
      expect(openSubscriptionFromApplication).toHaveBeenCalledWith(
        "application-1",
        1,
        expect.objectContaining({
          confirmUnavailable: true,
          unavailableReason: "客户已书面确认",
        }),
      ),
    );
    await waitFor(() => expect(getAdminPlanApplication).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(/approval-1/)).toBeNull();
  });
});
