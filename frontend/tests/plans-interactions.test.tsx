// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { PlanCatalog } from "../components/plans/plan-catalog";
import NewPlanPage from "../app/admin/plans/new/page";
import AdminPlansPage from "../app/admin/plans/page";
import PlanDetailPage from "../app/admin/plans/[id]/page";

const push = vi.fn();
const routeParams = { id: "plan-1" };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useParams: () => routeParams,
}));
const getCurrentUser = vi.fn();
const getPublicPlans = vi.fn();
const getPlans = vi.fn();
const createPlan = vi.fn();
const getPlan = vi.fn();
const copyPlan = vi.fn();
const getRiskActions = vi.fn();
vi.mock("../lib/plans-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/plans-client")>("../lib/plans-client");
  return {
    ...actual,
    getPublicPlans: (...args: unknown[]) => getPublicPlans(...args),
    getPlans: (...args: unknown[]) => getPlans(...args),
    createPlan: (...args: unknown[]) => createPlan(...args),
    getPlan: (...args: unknown[]) => getPlan(...args),
    copyPlan: (...args: unknown[]) => copyPlan(...args),
  };
});
vi.mock("../lib/auth-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/auth-client")>("../lib/auth-client");
  return {
    ...actual,
    getCurrentUser: (...args: unknown[]) => getCurrentUser(...args),
  };
});
vi.mock("../lib/risk-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/risk-client")>("../lib/risk-client");
  return {
    ...actual,
    getRiskActions: (...args: unknown[]) => getRiskActions(...args),
  };
});
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
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const fixed = {
  id: "plan-1",
  code: "fixed",
  name: "固定套餐",
  description: "说明",
  price_display_mode: "fixed" as const,
  display_price: "88.00",
  display_currency: "CNY" as const,
  plan_version_id: "version-1",
  version_no: 1,
  is_trial: false,
  valid_days: 30,
  benefits: {},
  models: [{ model_key: "deepseek" as const, name: "DeepSeek", selected_by_default: true }],
  supports_formal_composite: true,
  sort_order: 1,
};
const contact = {
  ...fixed,
  id: "plan-2",
  code: "contact",
  name: "联系套餐",
  price_display_mode: "contact" as const,
  display_price: null,
  supports_formal_composite: false,
};

describe("套餐真实交互", () => {
  it("用户套餐同时显示固定价格、联系开通和综合分能力", async () => {
    getPublicPlans.mockResolvedValue([fixed, contact]);
    render(<PlanCatalog />);
    expect(await screen.findByText("¥88.00")).toBeTruthy();
    expect(screen.getByText("联系开通")).toBeTruthy();
    expect(screen.getByText("支持正式综合分")).toBeTruthy();
    expect(screen.getByText("不支持正式综合分")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "申请开通" })).toHaveLength(2);
    expect(screen.queryByText("立即购买")).toBeNull();
  });

  it("用户套餐为空时显示安全空状态", async () => {
    getPublicPlans.mockResolvedValue([]);
    render(<PlanCatalog />);
    expect(await screen.findByText("当前没有可申请的套餐，请稍后查看或联系管理员。")).toBeTruthy();
  });

  it("创建 contact 套餐不会提交展示价格", async () => {
    createPlan.mockResolvedValue({ id: "new-plan" });
    render(<NewPlanPage />);
    await userEvent.type(screen.getByLabelText("稳定编码"), "contact-plan");
    await userEvent.type(screen.getByLabelText("套餐名称"), "联系套餐");
    await userEvent.click(screen.getByRole("combobox", { name: "展示价格模式" }));
    await userEvent.click(await screen.findByText("联系开通"));
    await userEvent.click(screen.getByRole("button", { name: "确认创建" }));
    await waitFor(() =>
      expect(createPlan).toHaveBeenCalledWith(
        expect.objectContaining({
          code: "contact-plan",
          price_display_mode: "contact",
          display_price: null,
          confirmed: true,
        }),
      ),
    );
    expect(push).toHaveBeenCalledWith("/admin/plans/new-plan");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("管理员列表筛选并区分固定价格与联系开通", async () => {
    getPlans.mockResolvedValue({
      results: [
        { ...fixed, status: "published", version: 2, current_published_version_id: "v1" },
        { ...contact, status: "offline", version: 3, current_published_version_id: "v2" },
      ],
      pagination: { page: 1, page_size: 20, count: 2, total_pages: 1 },
    });
    render(<AdminPlansPage />);
    expect(await screen.findByText("¥88.00")).toBeTruthy();
    expect(screen.getByText("联系开通")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("套餐关键字"), "fixed");
    await userEvent.click(screen.getByRole("button", { name: /筛\s*选/ }));
    await waitFor(() => expect(getPlans).toHaveBeenLastCalledWith("", "fixed"));
  });
});
describe("套餐详情复制与版本差异", () => {
  it("通过真实确认交互复制套餐，并展示发布版与草稿版差异", async () => {
    const version = {
      id: "version-1",
      plan_id: "plan-1",
      version_no: 1,
      status: "published" as const,
      valid_days: 30,
      queue_priority: 10,
      version: 1,
      snapshot_generated_at: "2026-08-01T00:00:00Z",
      limits: [{ key: "subject_active_limit", value_type: "integer", value: 3 }],
      model_permissions: [
        {
          model_key: "deepseek" as const,
          name: "DeepSeek",
          sort_order: 0,
          selected_by_default: true,
        },
      ],
      supports_formal_composite: false,
    };
    getPlan.mockResolvedValue({
      ...fixed,
      status: "published",
      version: 2,
      current_published_version_id: "version-1",
      current_published_version: version,
      draft_version: {
        ...version,
        id: "version-2",
        version_no: 2,
        status: "draft",
        valid_days: 60,
      },
    });
    getRiskActions.mockResolvedValue([{ key: "plan.copy", current_mode: "confirm" }]);
    copyPlan.mockResolvedValue({ id: "copied-plan" });

    render(<PlanDetailPage />);
    expect((await screen.findByLabelText("版本差异")).textContent).toContain('"valid_days": 60');
    await userEvent.type(screen.getByLabelText("新套餐编码"), "copied-plan");
    await userEvent.type(screen.getByLabelText("新套餐名称"), "复制套餐");
    await userEvent.click(screen.getByRole("button", { name: "复制为新套餐" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认执行" }));

    await waitFor(() =>
      expect(copyPlan).toHaveBeenCalledWith(
        "plan-1",
        expect.objectContaining({
          new_code: "copied-plan",
          new_name: "复制套餐",
          source_version_id: "version-1",
          expected_source_plan_version: 2,
          confirmed: true,
        }),
      ),
    );
    expect(push).toHaveBeenCalledWith("/admin/plans/copied-plan");
  });
});
