// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import CompetitorComparisonPage from "../app/geo/data-center/competitors/page";
import type { CompetitorComparison, CompetitorComparisonEntity } from "../lib/competitors-client";

const subjectA = {
  id: "subject-a",
  official_name: "甲公司",
  subject_type: { id: "type-1", key: "company", name: "企业", icon_key: "company" },
};
const subjectB = {
  id: "subject-b",
  official_name: "乙公司",
  subject_type: { id: "type-1", key: "company", name: "企业", icon_key: "company" },
};

let workspace = { currentSubject: subjectA, loading: false };
const getCompetitorComparison = vi.fn();

vi.mock("../components/subject-workspace-context", () => ({
  useSubjectWorkspace: () => workspace,
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

function entity(
  id: string,
  kind: CompetitorComparisonEntity["kind"],
  name: string,
  overrides: Partial<CompetitorComparisonEntity["metrics"]> = {},
): CompetitorComparisonEntity {
  return {
    id,
    kind,
    name,
    website: "",
    metrics: {
      mention_count: 32,
      mention_rate: 32,
      question_coverage_count: 20,
      question_coverage_rate: 20,
      shared_question_count: null,
      gap_question_count: null,
      recommendation_rate: null,
      citation_count: null,
      ...overrides,
    },
  };
}

function comparison(
  subjectId: string,
  status: CompetitorComparison["status"],
  overrides: Partial<CompetitorComparison> = {},
): CompetitorComparison {
  return {
    subject_id: subjectId,
    subject_name: subjectId === "subject-a" ? "甲公司" : "乙公司",
    status,
    competitor_count: status === "no_competitors" ? 0 : 1,
    report_id: null,
    detection_id: null,
    generated_at: null,
    valid_answer_count: 0,
    question_count: 0,
    entities: [],
    opportunities: [],
    detail_url: null,
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

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
  workspace = { currentSubject: subjectA, loading: false };
  getCompetitorComparison.mockReset();
});

afterEach(cleanup);

describe("竞品对比", () => {
  it("没有竞品时只引导前往当前主体竞品管理", async () => {
    getCompetitorComparison.mockResolvedValue(comparison("subject-a", "no_competitors"));
    render(<CompetitorComparisonPage />);

    expect(await screen.findByText("尚未设置核心竞品")).toBeTruthy();
    expect(screen.getByRole("link", { name: "前往竞品管理" }).getAttribute("href")).toBe(
      "/subjects/subject-a/competitors",
    );
    expect(screen.queryByText("核心指标对比")).toBeNull();
  });

  it("有竞品但没有检测数据时不显示全零指标", async () => {
    getCompetitorComparison.mockResolvedValue(comparison("subject-a", "no_detection_data"));
    render(<CompetitorComparisonPage />);

    expect(await screen.findByText("已设置竞品，但当前暂无足够检测数据用于对比。")).toBeTruthy();
    expect(screen.getByRole("link", { name: "前往检测中心" }).getAttribute("href")).toBe(
      "/geo/detections",
    );
    expect(screen.queryByText("0.00%")).toBeNull();
    expect(screen.queryByText("核心指标对比")).toBeNull();
  });

  it("展示真实指标、空缺指标和每页二十条机会问题", async () => {
    const subject = entity("subject-a", "subject", "甲公司");
    const rival = entity("competitor-a", "competitor", "竞品甲", {
      mention_count: 45,
      mention_rate: 45,
      question_coverage_count: 30,
      question_coverage_rate: 30,
      shared_question_count: 20,
      gap_question_count: 25,
    });
    getCompetitorComparison.mockResolvedValue(
      comparison("subject-a", "ready", {
        competitor_count: 1,
        report_id: "report-1",
        detection_id: "detection-1",
        generated_at: "2026-08-29T08:00:00Z",
        valid_answer_count: 100,
        question_count: 40,
        entities: [subject, rival],
        opportunities: Array.from({ length: 21 }, (_, index) => ({
          question_id: `question-${index + 1}`,
          question: `机会问题 ${index + 1}`,
          competitor_ids: ["competitor-a"],
          competitor_names: ["竞品甲"],
        })),
        detail_url: "/geo/reports/report-1",
      }),
    );

    render(<CompetitorComparisonPage />);

    expect(await screen.findByText("核心指标对比")).toBeTruthy();
    expect(screen.getByText("100 个有效回答")).toBeTruthy();
    expect(screen.getAllByText("45.00%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("25").length).toBeGreaterThan(0);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getAllByText("已出现").length).toBe(20);
    expect(screen.getByText("机会问题 20")).toBeTruthy();
    expect(screen.queryByText("机会问题 21")).toBeNull();

    await userEvent.click(screen.getByTitle("2"));
    expect(await screen.findByText("机会问题 21")).toBeTruthy();
  });

  it("当前主体切换后忽略上一主体的迟到结果", async () => {
    const subjectAResult = deferred<CompetitorComparison>();
    getCompetitorComparison.mockImplementation((subjectId: string) =>
      subjectId === "subject-a"
        ? subjectAResult.promise
        : Promise.resolve(
            comparison("subject-b", "ready", {
              competitor_count: 1,
              valid_answer_count: 10,
              question_count: 5,
              entities: [
                entity("subject-b", "subject", "乙公司"),
                entity("competitor-b", "competitor", "乙方竞品"),
              ],
            }),
          ),
    );

    const { rerender } = render(<CompetitorComparisonPage />);
    workspace = { currentSubject: subjectB, loading: false };
    rerender(<CompetitorComparisonPage />);

    expect(await screen.findByRole("heading", { name: "乙方竞品" })).toBeTruthy();
    subjectAResult.resolve(
      comparison("subject-a", "ready", {
        competitor_count: 1,
        entities: [
          entity("subject-a", "subject", "甲公司"),
          entity("competitor-a", "competitor", "甲方旧竞品"),
        ],
      }),
    );
    await Promise.resolve();

    expect(screen.getByRole("heading", { name: "乙方竞品" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "甲方旧竞品" })).toBeNull();
  });
});
