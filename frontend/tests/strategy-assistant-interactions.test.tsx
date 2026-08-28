// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import ImprovementStrategyPage from "../app/geo/reports/[reportId]/strategy/strategy-page";
import type { GeoReport } from "../lib/geo-report-client";
import type { Strategy, StrategyList } from "../lib/strategy-assistant-client";
import type { ExecutionPreviewResponse } from "../lib/strategy-execution-client";

const replace = vi.fn();
const push = vi.fn();
const getReport = vi.fn();
const getStrategies = vi.fn();
const getStrategy = vi.fn();
const createStrategy = vi.fn();
const saveStrategyNote = vi.fn();
const getExecutionPreview = vi.fn();
const createExecutionPlan = vi.fn();
const router = { replace, push };
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
vi.mock("../lib/geo-report-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/geo-report-client")>(
    "../lib/geo-report-client",
  );
  return { ...actual, getReport: (...args: unknown[]) => getReport(...args) };
});
vi.mock("../lib/strategy-assistant-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/strategy-assistant-client")>(
    "../lib/strategy-assistant-client",
  );
  return {
    ...actual,
    getStrategies: (...args: unknown[]) => getStrategies(...args),
    getStrategy: (...args: unknown[]) => getStrategy(...args),
    createStrategy: (...args: unknown[]) => createStrategy(...args),
    saveStrategyNote: (...args: unknown[]) => saveStrategyNote(...args),
  };
});
vi.mock("../lib/strategy-execution-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/strategy-execution-client")>(
    "../lib/strategy-execution-client",
  );
  return {
    ...actual,
    getExecutionPreview: (...args: unknown[]) => getExecutionPreview(...args),
    createExecutionPlan: (...args: unknown[]) => createExecutionPlan(...args),
  };
});

const report: GeoReport = {
  id: "report-1",
  detection_id: "detection-1",
  subject_id: "subject-1",
  subject_version_id: "version-1",
  retest_mode: "",
  summary: {
    geo: { score: "53.2", status: "formal" },
    brand_reputation: { score: "60", status: "formal" },
    exposure: {
      exposure_index: "59.6",
      grade: "待提升",
      status: "formal",
      disclaimer: "",
      mention_rate_score: "55",
      recommendation_rate_score: "41",
      ranking_performance_score: "38",
      model_coverage_score: "62",
    },
    models: [],
    dimensions: {},
    competitors: [
      {
        id: "c-1",
        canonical_name: "竞品",
        aliases: [],
        entity_type: "品牌",
        mention_count: 3,
      },
    ],
  },
  provenance: { scoring_rule_version: "v1", questions: [], models: [] },
  comparison: null,
  generated_at: "2026-08-20T10:00:00Z",
};

const strategy: Strategy = {
  id: "strategy-1",
  report_id: "report-1",
  subject_id: "subject-1",
  subject_version_id: "version-1",
  period: "30d",
  period_days: 30,
  status: "succeeded",
  billing: { mode: "free_initial", first_free: true, held: false, remaining: 3 },
  body: {
    overview: "优先完善权威事实页。",
    priorities: [
      {
        title: "提升可信引用",
        rationale: "引用维度仍有空间。",
        actions: ["整理权威公开资料"],
        success_metric: "引用得分提升",
      },
    ],
    schedule: [{ phase: "第一阶段", focus: "事实整理", actions: ["确认公开信息"] }],
    article_topics: [
      {
        title: "品牌事实指南",
        reason: "强化准确引用",
        route: "/subjects/subject-1/articles/new?topic=brand",
      },
    ],
  },
  note: null,
  provenance: {
    provider_key: "deepseek",
    model_key: "deepseek",
    provider_model_id: "deepseek-chat",
    adapter_version: "strategy-v1",
    prompt_version: "strategy-v1",
    schema_version: "strategy-v1",
    report_scoring_rule_version: "score-v1",
  },
  safe_error_code: "",
  created_at: "2026-08-20T10:00:00Z",
  generated_at: "2026-08-20T10:01:00Z",
  finished_at: "2026-08-20T10:01:00Z",
};

const firstFree: StrategyList = {
  items: [],
  first_free_available: true,
  remaining_regenerations: 3,
};

const preview: ExecutionPreviewResponse = {
  preview: {
    items: [
      {
        key: "priority-01",
        title: "完善主体事实页",
        problem: "公开事实不足",
        reason: "帮助平台准确理解主体",
        recommendation: "补齐可核验资料",
        deliverables: ["主体事实页"],
        success_metric: "资料完整并可公开核验",
        expected_improvement: "提升理解完整度",
        priority: "urgent",
        kind: "platform_assisted",
        estimated_days: 3,
        estimated_price_cents: 0,
        cost_note: "按实际使用功能与套餐规则为准。",
        selected_by_default: true,
      },
    ],
    packages: [
      {
        code: "focused",
        name: "重点提升",
        description: "先处理主要短板",
        item_keys: ["priority-01"],
        media_ids: ["media-1"],
        estimated_days: 7,
        estimated_price_cents: 98000,
        recommended: true,
      },
    ],
    recommended_media: [
      {
        id: "media-1",
        name: "示例媒体",
        url: "https://example.com",
        domain: "example.com",
        logo_path: null,
        price_cents: 98000,
        reason: "补充公开信源",
        selected_by_default: false,
      },
    ],
  },
  plan: null,
};

describe("优化方案与执行计划交互", () => {
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
    Object.defineProperty(globalThis, "crypto", {
      value: { randomUUID: () => "idempotency-key" },
      configurable: true,
    });
  });

  beforeEach(() => {
    for (const mock of [
      replace,
      push,
      getReport,
      getStrategies,
      getStrategy,
      createStrategy,
      saveStrategyNote,
      getExecutionPreview,
      createExecutionPlan,
    ]) {
      mock.mockReset();
    }
    getReport.mockResolvedValue(report);
    getStrategies.mockResolvedValue(firstFree);
    getExecutionPreview.mockResolvedValue(preview);
  });

  afterEach(() => cleanup());

  it("并行读取报告和方案后可选择周期生成", async () => {
    createStrategy.mockResolvedValue(strategy);
    render(<ImprovementStrategyPage reportId="report-1" />);
    expect(await screen.findByText("首份方案免费")).toBeTruthy();
    await userEvent.click(screen.getByText("90 天"));
    await userEvent.click(screen.getByRole("button", { name: "生成优化方案" }));
    await waitFor(() =>
      expect(createStrategy).toHaveBeenCalledWith(
        "report-1",
        { period: "90d", regenerate: false },
        "idempotency-key",
      ),
    );
    expect(await screen.findByText("当前最需要解决的短板")).toBeTruthy();
  });

  it("显示真实差距、行动和媒体费用，并在二次确认后建立计划", async () => {
    getStrategies.mockResolvedValue({
      ...firstFree,
      items: [strategy],
      first_free_available: false,
    });
    createExecutionPlan.mockResolvedValue({ id: "plan-1" });
    render(<ImprovementStrategyPage reportId="report-1" />);
    expect(await screen.findByText("距离建议目标")).toBeTruthy();
    expect((await screen.findAllByText("重点提升")).length).toBeGreaterThan(0);
    expect(screen.getByText("示例媒体")).toBeTruthy();
    expect(screen.getAllByText("¥980").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "确认并建立执行计划" }));
    expect(await screen.findByText("本次提交的付费媒体")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "确认并进入执行计划" }));
    await waitFor(() =>
      expect(createExecutionPlan).toHaveBeenCalledWith(
        "strategy-1",
        {
          package_code: "focused",
          item_keys: ["priority-01"],
          media_ids: ["media-1"],
        },
        "idempotency-key",
      ),
    );
    expect(push).toHaveBeenCalledWith("/geo/execution/plan-1");
  });

  it("主体不匹配时返回方案列表，且不暴露内部错误", async () => {
    getReport.mockResolvedValue({ ...report, subject_id: "subject-2" });
    render(<ImprovementStrategyPage reportId="report-1" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/geo/strategy"));
    cleanup();
    getReport.mockRejectedValue(new Error("PROVIDER_RUNTIME_HTTP_ERROR"));
    render(<ImprovementStrategyPage reportId="report-1" />);
    expect(await screen.findByText("当前操作未能完成，请稍后重新尝试。")).toBeTruthy();
  });
});
