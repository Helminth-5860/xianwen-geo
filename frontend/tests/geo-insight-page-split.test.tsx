// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import GeoExposurePage from "../app/geo/exposure/page";
import GeoReportHistoryPage from "../app/geo/reports/history/page";
import GeoReportsIndexPage from "../app/geo/reports/page";
import type { GeoReport, GeoReportComparison } from "../lib/geo-report-client";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const workspace = {
  currentSubject: {
    id: "subject-1",
    official_name: "示例主体",
    subject_type: { name: "企业" },
  },
  loading: false,
};

vi.mock("../components/subject-workspace-context", () => ({
  useSubjectWorkspace: () => workspace,
}));

const getReportHistory = vi.fn();
const getReportComparison = vi.fn();

vi.mock("../lib/geo-report-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/geo-report-client")>(
    "../lib/geo-report-client",
  );
  return {
    ...actual,
    getReportHistory: (...args: unknown[]) => getReportHistory(...args),
    getReportComparison: (...args: unknown[]) => getReportComparison(...args),
  };
});

function makeReport(
  id: string,
  generatedAt: string,
  geoScore: string,
  reputationScore: string,
  exposureIndex: string,
): GeoReport {
  return {
    id,
    detection_id: `detection-${id}`,
    subject_id: "subject-1",
    subject_version_id: `subject-version-${id}`,
    retest_mode: "",
    summary: {
      geo: { score: geoScore, grade: "优秀", status: "formal", formal_model_count: 8 },
      brand_reputation: {
        score: reputationScore,
        grade: "优秀",
        status: "formal",
        formal_model_count: 8,
      },
      exposure: {
        exposure_index: exposureIndex,
        grade: "中",
        status: "formal",
        disclaimer: "曝光潜力指数是系统评估指数，不是实际曝光人数。",
        mention_rate_score: "75.0000",
        recommendation_rate_score: "70.0000",
        ranking_performance_score: "68.0000",
        model_coverage_score: "87.5000",
      },
      models: [],
      dimensions: {
        mention: "80.0000",
        recommendation: "75.0000",
        rank: "70.0000",
        accuracy: "85.0000",
        sentiment: "75.0000",
        citation: "65.0000",
      },
      competitors: [
        {
          id: "competitor-1",
          canonical_name: "示例竞品",
          aliases: ["竞品别名"],
          entity_type: "brand",
          mention_count: 3,
        },
      ],
    },
    provenance: {
      scoring_rule_version: "geo-scoring-v1",
      questions: [],
      models: [],
    },
    comparison: null,
    generated_at: generatedAt,
  };
}

const baseline = makeReport("report-0", "2026-08-10T08:00:00Z", "79.2500", "75.0000", "69.5000");
const current = makeReport("report-1", "2026-08-20T08:00:00Z", "81.2500", "76.0000", "72.5000");

const comparable: GeoReportComparison = {
  baseline_report_id: baseline.id,
  status: "comparable",
  same_subject: true,
  same_questions: true,
  same_models: true,
  same_scoring_rule: true,
  subject_version_changed: true,
  scoring_version_changed: false,
  geo_score_delta: "2.0000",
  brand_reputation_score_delta: "1.0000",
  exposure_index_delta: "3.0000",
  dimension_deltas: {
    mention: "0.5000",
    recommendation: "1.5000",
    rank: "2.5000",
    accuracy: "3.5000",
    sentiment: "4.5000",
    citation: "5.5000",
  },
  model_deltas: [],
};

describe("GEO insight page responsibility split", () => {
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
  });

  beforeEach(() => {
    replace.mockReset();
    getReportHistory.mockReset();
    getReportComparison.mockReset();
    getReportHistory.mockResolvedValue({ items: [baseline, current] });
    getReportComparison.mockResolvedValue({ current, baseline, comparison: comparable });
  });

  afterEach(cleanup);

  it("opens the latest immutable report instead of rendering a mixed report dashboard", async () => {
    render(<GeoReportsIndexPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/geo/reports/report-1"));
    expect(getReportHistory).toHaveBeenCalledWith("subject-1");
    expect(screen.queryByText("历史检测报告")).toBeNull();
    expect(screen.queryByText("AI 曝光指数")).toBeNull();
  });

  it("compares two selected reports through the real comparison endpoint", async () => {
    render(<GeoReportHistoryPage />);

    expect(await screen.findByText("两份报告可正式比较")).toBeTruthy();
    expect(getReportHistory).toHaveBeenCalledWith("subject-1");
    expect(getReportComparison).toHaveBeenCalledWith("report-1", "report-0");
    expect(screen.getByText("涨跌 +2.0000")).toBeTruthy();
    expect(screen.getByText("涨跌 +1.0000")).toBeTruthy();
    expect(screen.getByText("涨跌 +3.0000")).toBeTruthy();
    expect(screen.getByText("六维评分涨跌")).toBeTruthy();
  });

  it("explains why two reports are not comparable and suppresses formal deltas", async () => {
    getReportComparison.mockResolvedValue({
      current,
      baseline,
      comparison: {
        ...comparable,
        status: "not_comparable",
        same_questions: false,
        same_scoring_rule: false,
        scoring_version_changed: true,
        geo_score_delta: null,
        brand_reputation_score_delta: null,
        exposure_index_delta: null,
        dimension_deltas: {},
      },
    });

    render(<GeoReportHistoryPage />);

    expect(await screen.findByText("两份报告不可正式比较")).toBeTruthy();
    expect(screen.getByText(/检测问题集合不同；评分规则版本不同/)).toBeTruthy();
    expect(screen.queryByText("涨跌 +2.0000")).toBeNull();
  });

  it("renders exposure metrics only on the independent exposure page", async () => {
    render(<GeoExposurePage />);

    expect(await screen.findByText("综合曝光指数")).toBeTruthy();
    expect(screen.getByText("提及率")).toBeTruthy();
    expect(screen.getByText("推荐率")).toBeTruthy();
    expect(screen.getByText("排名表现")).toBeTruthy();
    expect(screen.getByText("模型覆盖率")).toBeTruthy();
    expect(screen.queryByText("主要竞品曝光参考")).toBeNull();
    expect(screen.queryByText("核心指标涨跌")).toBeNull();
    expect(getReportComparison).not.toHaveBeenCalled();
  });
});
