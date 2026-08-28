// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import ExecutionPlanDetailPage from "../app/geo/execution/[planId]/execution-plan-page";
import ExecutionPlanIndexPage from "../app/geo/execution/page";
import type { ExecutionPlan } from "../lib/strategy-execution-client";

const replace = vi.fn();
const getExecutionPlan = vi.fn();
const getExecutionPlans = vi.fn();
const updateExecutionPlan = vi.fn();
const router = { replace };
const currentSubject = {
  id: "subject-1",
  official_name: "测试企业",
  subject_type: { name: "公司" },
};

vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("../components/subject-workspace-context", () => ({
  useSubjectWorkspace: () => ({
    currentSubject,
    loading: false,
  }),
}));
vi.mock("../lib/strategy-execution-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/strategy-execution-client")>(
    "../lib/strategy-execution-client",
  );
  return {
    ...actual,
    getExecutionPlan: (...args: unknown[]) => getExecutionPlan(...args),
    getExecutionPlans: (...args: unknown[]) => getExecutionPlans(...args),
    updateExecutionPlan: (...args: unknown[]) => updateExecutionPlan(...args),
  };
});

const plan: ExecutionPlan = {
  id: "plan-1",
  strategy_id: "strategy-1",
  report_id: "report-1",
  subject_id: "subject-1",
  package_code: "focused",
  package_name: "重点提升",
  status: "active",
  version: 1,
  estimated_days: 14,
  estimated_price_cents: 98000,
  items: [
    {
      key: "item-1",
      title: "完善主体资料",
      kind: "platform_assisted",
      status: "pending",
      recommendation: "补齐可核验的主体信息",
      deliverables: ["主体事实页"],
      success_metric: "资料完整并可核验",
      estimated_days: 3,
      estimated_price_cents: 0,
      cost_note: "按实际使用功能与套餐规则为准。",
      period: "第一阶段",
      route: "/subjects/subject-1",
    },
  ],
  selected_media: [
    {
      id: "media-1",
      name: "示例媒体",
      url: "https://example.com",
      domain: "example.com",
      logo_path: null,
      price_cents: 98000,
      inquiry_status: "pending",
    },
  ],
  created_at: "2026-08-28T10:00:00Z",
  updated_at: "2026-08-28T10:00:00Z",
};

describe("执行计划页面", () => {
  beforeAll(() => {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation(() => ({
        matches: true,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  beforeEach(() => {
    for (const mock of [replace, getExecutionPlan, getExecutionPlans, updateExecutionPlan]) {
      mock.mockReset();
    }
    getExecutionPlan.mockResolvedValue(plan);
    getExecutionPlans.mockResolvedValue({
      items: [plan],
      pagination: { page: 1, page_size: 20, count: 1, total_pages: 1 },
    });
    updateExecutionPlan.mockResolvedValue({
      ...plan,
      version: 2,
      items: [{ ...plan.items[0], status: "in_progress" }],
    });
  });

  afterEach(() => cleanup());

  it("列表只读取当前主体计划并显示进度入口", async () => {
    render(<ExecutionPlanIndexPage />);
    expect(await screen.findByText("重点提升")).toBeTruthy();
    expect(getExecutionPlans).toHaveBeenCalledWith("subject-1", 1);
    expect(screen.getByRole("link", { name: /查看并执行/ }).getAttribute("href")).toBe(
      "/geo/execution/plan-1",
    );
  });

  it("详情页按版本开始行动并显示媒体申请状态", async () => {
    render(<ExecutionPlanDetailPage planId="plan-1" />);
    expect(await screen.findByText("完善主体资料")).toBeTruthy();
    expect(screen.getByText("已提交管理员")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /开始执行/ }));
    await waitFor(() =>
      expect(updateExecutionPlan).toHaveBeenCalledWith("plan-1", {
        action: "start_item",
        item_key: "item-1",
        expected_version: 1,
      }),
    );
    expect(await screen.findByText("进行中")).toBeTruthy();
  });

  it("拒绝显示其他主体的执行计划", async () => {
    getExecutionPlan.mockResolvedValue({ ...plan, subject_id: "subject-2" });
    render(<ExecutionPlanDetailPage planId="plan-1" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/geo/execution"));
  });

  it("整个计划因取消而结束后仍可恢复非媒体行动", async () => {
    const cancelledPlan: ExecutionPlan = {
      ...plan,
      status: "cancelled",
      items: [{ ...plan.items[0], status: "cancelled" }],
      selected_media: [],
    };
    getExecutionPlan.mockResolvedValue(cancelledPlan);
    updateExecutionPlan.mockResolvedValue({
      ...cancelledPlan,
      status: "active",
      version: 2,
      items: [{ ...cancelledPlan.items[0], status: "pending" }],
    });
    render(<ExecutionPlanDetailPage planId="plan-1" />);
    await userEvent.click(await screen.findByRole("button", { name: /恢复/ }));
    await waitFor(() =>
      expect(updateExecutionPlan).toHaveBeenCalledWith("plan-1", {
        action: "restore_item",
        item_key: "item-1",
        expected_version: 1,
      }),
    );
  });
});
