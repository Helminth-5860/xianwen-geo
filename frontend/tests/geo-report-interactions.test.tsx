// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import GeoReportPage, {
  REPORT_READY_MAX_POLL_ATTEMPTS,
  REPORT_READY_POLL_INTERVAL_MS,
} from "../app/geo/reports/report-page";
import { AuthApiError } from "../lib/auth-client";
import type { GeoReport, ReportQuestionPage } from "../lib/geo-report-client";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const getReport = vi.fn();
const getReportForDetection = vi.fn();
const getReportQuestions = vi.fn();
const getReportAnswer = vi.fn();
const getReportHistory = vi.fn();
const getReportTrends = vi.fn();
const createReportExport = vi.fn();
const getReportExport = vi.fn();
const quickRetest = vi.fn();
const adjustedRetest = vi.fn();
const getDetectionOptions = vi.fn();

vi.mock("../lib/geo-report-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/geo-report-client")>(
    "../lib/geo-report-client",
  );
  return {
    ...actual,
    getReport: (...args: unknown[]) => getReport(...args),
    getReportForDetection: (...args: unknown[]) => getReportForDetection(...args),
    getReportQuestions: (...args: unknown[]) => getReportQuestions(...args),
    getReportAnswer: (...args: unknown[]) => getReportAnswer(...args),
    getReportHistory: (...args: unknown[]) => getReportHistory(...args),
    getReportTrends: (...args: unknown[]) => getReportTrends(...args),
    createReportExport: (...args: unknown[]) => createReportExport(...args),
    getReportExport: (...args: unknown[]) => getReportExport(...args),
    quickRetest: (...args: unknown[]) => quickRetest(...args),
    adjustedRetest: (...args: unknown[]) => adjustedRetest(...args),
    getDetectionOptions: (...args: unknown[]) => getDetectionOptions(...args),
  };
});

const getCurrentQuestionBank = vi.fn();
vi.mock("../lib/question-bank-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/question-bank-client")>(
    "../lib/question-bank-client",
  );
  return {
    ...actual,
    getCurrentQuestionBank: (...args: unknown[]) => getCurrentQuestionBank(...args),
  };
});

const report: GeoReport = {
  id: "report-1",
  detection_id: "detection-1",
  subject_id: "subject-1",
  subject_version_id: "subject-version-2",
  retest_mode: "quick",
  summary: {
    geo: { score: "81.2500", grade: "优秀", status: "formal", formal_model_count: 8 },
    brand_reputation: {
      score: "76.0000",
      grade: "优秀",
      status: "formal",
      formal_model_count: 8,
    },
    exposure: {
      exposure_index: "72.5000",
      grade: "中",
      status: "formal",
      disclaimer: "曝光潜力指数是系统评估指数，不是实际曝光人数。",
      mention_rate_score: "75.0000",
      recommendation_rate_score: "70.0000",
      ranking_performance_score: "68.0000",
      model_coverage_score: "87.5000",
    },
    models: [
      {
        model_id: "model-1",
        model_key: "deepseek",
        status: "succeeded",
        planned_calls: 2,
        completed_calls: 2,
        successful_calls: 2,
        failed_calls: 0,
        cancelled_calls: 0,
        geo: { score: "81.2500", status: "formal" },
        brand_reputation: { score: "76.0000", status: "formal" },
      },
    ],
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
    questions: [{ source_question_id: "question-1", text: "用户会如何选择？" }],
    models: [{ model_id: "model-1", model_key: "deepseek" }],
  },
  comparison: {
    baseline_report_id: "report-0",
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
    dimension_deltas: {},
    model_deltas: [],
  },
  generated_at: "2026-08-20T08:00:00Z",
};

const questions: ReportQuestionPage = {
  results: [
    {
      question_id: "snapshot-question-1",
      source_question_id: "question-1",
      question_type: "natural",
      text: "用户会如何选择？",
      results: [
        {
          call_id: "call-1",
          model_id: "model-1",
          model_key: "deepseek",
          status: "succeeded",
          safe_error_summary: {},
          answer_available: true,
          snippet: "这是默认展示的关键片段。",
          score: { total: "81.2500" },
          citations: [],
        },
      ],
    },
  ],
  pagination: { page: 1, page_size: 10, count: 1, total_pages: 1 },
};

describe("GeoReportPage", () => {
  beforeAll(() => {
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
      value: { randomUUID: () => "idempotency-1" },
      configurable: true,
    });
  });

  beforeEach(() => {
    push.mockReset();
    for (const mock of [
      getReport,
      getReportForDetection,
      getReportQuestions,
      getReportAnswer,
      getReportHistory,
      getReportTrends,
      createReportExport,
      getReportExport,
      quickRetest,
      adjustedRetest,
      getDetectionOptions,
      getCurrentQuestionBank,
    ]) {
      mock.mockReset();
    }
    getReport.mockResolvedValue(report);
    getReportQuestions.mockResolvedValue(questions);
    getReportHistory.mockResolvedValue({ items: [report] });
    getReportTrends.mockResolvedValue({
      items: [
        {
          report_id: report.id,
          generated_at: report.generated_at,
          subject_version_id: report.subject_version_id,
          geo_score: report.summary.geo.score,
          comparison: report.comparison,
        },
      ],
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("stops waiting when report scoring never becomes available", async () => {
    vi.useFakeTimers();
    const pending = new AuthApiError(new Response(null, { status: 409 }), {
      success: false,
      error: {
        code: "GEO_DETECTION_STATE_CONFLICT",
        message: "报告尚未就绪",
        details: {},
      },
      request_id: "request-pending",
    });
    getReportForDetection.mockRejectedValue(pending);

    render(<GeoReportPage detectionId="detection-pending" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    for (let attempt = 0; attempt < REPORT_READY_MAX_POLL_ATTEMPTS + 2; attempt += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(REPORT_READY_POLL_INTERVAL_MS);
      });
    }

    expect(
      screen.getByText(/系统已停止等待，检测结果不会丢失；后续配置报告模型后可重新检查/),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "返回检测结果" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "重新检查报告" })).toBeTruthy();
    expect(getReportForDetection).toHaveBeenCalledTimes(REPORT_READY_MAX_POLL_ATTEMPTS);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REPORT_READY_POLL_INTERVAL_MS * 5);
    });
    expect(getReportForDetection).toHaveBeenCalledTimes(REPORT_READY_MAX_POLL_ATTEMPTS);
  });

  it("renders the frozen report modules and only fetches full text after expansion", async () => {
    getReportAnswer.mockResolvedValue({
      call_id: "call-1",
      model_key: "deepseek",
      answer: "这是按需获取的完整原始回答。",
      citations: [],
    });
    render(<GeoReportPage reportId="report-1" />);
    expect(await screen.findByText("GEO 检测报告")).toBeTruthy();
    expect(await screen.findByText("这是默认展示的关键片段。")).toBeTruthy();
    expect(screen.getByText("主体资料版本已变化；本报告使用复测时的当前版本")).toBeTruthy();
    expect(screen.getByText("主要竞品曝光参考")).toBeTruthy();
    expect(getReportAnswer).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "展开完整原始回答" }));
    expect(await screen.findByText("这是按需获取的完整原始回答。")).toBeTruthy();
    expect(getReportAnswer).toHaveBeenCalledWith("call-1");
  });

  it("starts exact quick retest and routes into the existing progress page", async () => {
    quickRetest.mockResolvedValue({
      detection_id: "detection-new",
      status: "queued",
      replayed: false,
    });
    render(<GeoReportPage reportId="report-1" />);
    await screen.findByText("导出与复测");
    expect(screen.getByText(/不会替换不可用模型/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "快速复测" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/geo/detections/detection-new"));
  });

  it("shows the blocking model reason without silently changing to adjusted retest", async () => {
    const blocked = new AuthApiError(new Response(null, { status: 409 }), {
      success: false,
      error: {
        code: "GEO_DETECTION_PROVIDER_UNAVAILABLE",
        message: "模型不可用",
        details: { model_key: "deepseek", reason: "model_paused" },
      },
      request_id: "request-1",
    });
    quickRetest.mockRejectedValue(blocked);
    render(<GeoReportPage reportId="report-1" />);
    await screen.findByText("导出与复测");
    await userEvent.click(screen.getByRole("button", { name: "快速复测" }));
    expect(await screen.findByText(/deepseek：原报告模型正在维护暂停/)).toBeTruthy();
    expect(screen.getByText(/使用调整后复测重新选择/)).toBeTruthy();
    expect(push).not.toHaveBeenCalled();
  });
});
