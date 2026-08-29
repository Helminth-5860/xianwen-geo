// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import CompetitorComparisonPage from "../app/geo/data-center/competitors/page";

const getCompetitorComparison = vi.fn();

vi.mock("../components/subject-workspace-context", () => ({
  useSubjectWorkspace: () => ({
    currentSubject: {
      id: "subject-1",
      official_name: "显问科技",
      subject_type: { name: "企业" },
    },
    loading: false,
  }),
}));

vi.mock("../lib/competitors-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/competitors-client")>(
    "../lib/competitors-client",
  );
  return {
    ...actual,
    getCompetitorComparison: (...args: unknown[]) => getCompetitorComparison(...args),
  };
});

beforeAll(() => {
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
  getCompetitorComparison.mockReset();
  getCompetitorComparison.mockResolvedValue({
    subject_id: "subject-1",
    subject_name: "显问科技",
    status: "no_competitors",
    competitor_count: 0,
    report_id: null,
    detection_id: null,
    generated_at: null,
    valid_answer_count: 0,
    question_count: 0,
    entities: [],
    opportunities: [],
    detail_url: null,
  });
});

afterEach(cleanup);

describe("竞品对比入口", () => {
  it("使用竞品管理空状态，不再显示旧占位内容", async () => {
    render(<CompetitorComparisonPage />);

    expect(await screen.findByRole("heading", { name: "竞品对比" })).toBeTruthy();
    expect(await screen.findByText("尚未设置核心竞品")).toBeTruthy();
    expect(screen.getByRole("link", { name: "前往竞品管理" }).getAttribute("href")).toBe(
      "/subjects/subject-1/competitors",
    );
    expect(screen.queryByText("当前暂无可展示的竞品对比")).toBeNull();
  });
});
