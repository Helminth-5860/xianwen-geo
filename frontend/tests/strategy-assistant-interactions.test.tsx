// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import ImprovementStrategyPage from "../app/geo/reports/[reportId]/strategy/strategy-page";
import type { Strategy, StrategyList } from "../lib/strategy-assistant-client";

const getStrategies = vi.fn();
const getStrategy = vi.fn();
const createStrategy = vi.fn();
const saveStrategyNote = vi.fn();

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
        route: "/subjects/subject-1/articles/new?topic=%E5%93%81%E7%89%8C",
      },
    ],
  },
  note: null,
  provenance: {
    provider_key: "deepseek",
    model_key: "deepseek",
    provider_model_id: "deepseek-chat",
    adapter_version: "deepseek-strategy-v1",
    prompt_version: "geo-improvement-strategy-v1",
    schema_version: "geo-improvement-strategy-schema-v1",
    report_scoring_rule_version: "geo-scoring-v1",
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

describe("Stage 1E strategy interactions", () => {
  beforeAll(() => {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation(() => ({
        matches: false,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    Object.defineProperty(globalThis, "crypto", {
      value: { randomUUID: () => "stage-1e-idempotency-key" },
      configurable: true,
    });
  });

  beforeEach(() => {
    for (const mock of [getStrategies, getStrategy, createStrategy, saveStrategyNote]) {
      mock.mockReset();
    }
    getStrategies.mockResolvedValue(firstFree);
  });

  afterEach(() => cleanup());

  it("selects a strategy period, shows first-free quota, and generates", async () => {
    createStrategy.mockResolvedValue(strategy);
    render(<ImprovementStrategyPage reportId="report-1" />);
    expect((await screen.findAllByText("首份策略免费")).length).toBeGreaterThan(0);
    expect(screen.getByText("剩余重新生成次数：3")).toBeTruthy();
    await userEvent.click(screen.getByText("90 天"));
    await userEvent.click(screen.getByRole("button", { name: "生成策略" }));
    await waitFor(() =>
      expect(createStrategy).toHaveBeenCalledWith(
        "report-1",
        { period: "90d", regenerate: false },
        "stage-1e-idempotency-key",
      ),
    );
    expect(await screen.findByText("优先完善权威事实页。")).toBeTruthy();
  });

  it("renders immutable AI strategy separately from editable notes and topic intent", async () => {
    getStrategies.mockResolvedValue({
      ...firstFree,
      items: [strategy],
      first_free_available: false,
    });
    saveStrategyNote.mockResolvedValue({
      text: "我的执行备注",
      version: 1,
      updated_at: "2026-08-20T11:00:00Z",
    });
    render(<ImprovementStrategyPage reportId="report-1" />);
    expect(await screen.findByText("AI 原始策略（不可编辑）")).toBeTruthy();
    expect(screen.queryByDisplayValue("优先完善权威事实页。")).toBeNull();
    const topicLink = screen.getByRole("link", { name: "带主题进入文章页" });
    expect(topicLink.getAttribute("href")).toContain("/subjects/subject-1/articles/new?topic=");
    expect(screen.getByText(/进入页面不会自动生成文章或扣除文章额度/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText("个人备注"), "我的执行备注");
    await userEvent.click(screen.getByRole("button", { name: "保存备注" }));
    await waitFor(() =>
      expect(saveStrategyNote).toHaveBeenCalledWith("strategy-1", "我的执行备注", 0),
    );
  });

  it("confirms regeneration charging semantics and exposes provider errors", async () => {
    getStrategies.mockResolvedValue({
      items: [strategy],
      first_free_available: false,
      remaining_regenerations: 2,
    });
    createStrategy.mockRejectedValue(new Error("DeepSeek 暂不可用，失败不扣次数"));
    render(<ImprovementStrategyPage reportId="report-1" />);
    expect(await screen.findByText("已使用首份免费策略")).toBeTruthy();
    expect(screen.getByText("剩余重新生成次数：2")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "重新生成策略" }));
    expect(await screen.findByText("DeepSeek 暂不可用，失败不扣次数")).toBeTruthy();
    expect(createStrategy.mock.calls[0][1]).toMatchObject({ regenerate: true });
  });
});
