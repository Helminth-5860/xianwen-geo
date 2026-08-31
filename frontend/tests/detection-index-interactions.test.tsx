// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import GeoDetectionIndexPage, {
  DETECTION_QUESTION_PAGE_SIZE,
  DETECTION_RESULT_PAGE_SIZE,
} from "../app/geo/detections/page";
import type { GeoDetectionJob } from "../lib/geo-detection-client";

const push = vi.fn();
const getDetectionOptions = vi.fn();
const getCurrentQuestionBank = vi.fn();
const getDetectionHistory = vi.fn();
const removeDetectionResult = vi.fn();
const estimateDetection = vi.fn();
const createDetection = vi.fn();

const subject = {
  id: "subject-1",
  subject_type: { id: "type-1", key: "company", name: "企业", icon_key: "company" },
  status: "active" as const,
  version: 3,
  is_current: true,
  current_version_no: 2,
  official_name: "显问科技",
  service_regions: "",
  retest_required: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("../components/subject-workspace-context", () => ({
  useSubjectWorkspace: () => ({ currentSubject: subject, loading: false }),
}));
vi.mock("../lib/geo-report-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/geo-report-client")>(
    "../lib/geo-report-client",
  );
  return {
    ...actual,
    getDetectionOptions: (...args: unknown[]) => getDetectionOptions(...args),
  };
});
vi.mock("../lib/question-bank-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/question-bank-client")>(
    "../lib/question-bank-client",
  );
  return {
    ...actual,
    getCurrentQuestionBank: (...args: unknown[]) => getCurrentQuestionBank(...args),
  };
});
vi.mock("../lib/geo-detection-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/geo-detection-client")>(
    "../lib/geo-detection-client",
  );
  return {
    ...actual,
    getDetectionHistory: (...args: unknown[]) => getDetectionHistory(...args),
    removeDetectionResult: (...args: unknown[]) => removeDetectionResult(...args),
    estimateDetection: (...args: unknown[]) => estimateDetection(...args),
    createDetection: (...args: unknown[]) => createDetection(...args),
  };
});

const questions = Array.from({ length: 25 }, (_, index) => ({
  id: `question-${index + 1}`,
  text: `检测问题 ${index + 1}`,
  priority: "high" as const,
  question_type: index % 2 === 0 ? ("natural" as const) : ("brand_directed" as const),
  participates_in_scoring: true,
  ai_reason: "",
  sort_order: index + 1,
}));

const modelKeys = ["deepseek", "doubao", "qwen", "hunyuan", "wenxin", "kimi", "glm", "spark"];
const modelNames = [
  "DeepSeek",
  "豆包",
  "通义千问",
  "腾讯混元",
  "文心一言",
  "Kimi",
  "智谱清言",
  "讯飞星火",
];

const detection = (index: number): GeoDetectionJob => ({
  id: `detection-${index + 1}`,
  subject_id: subject.id,
  status: "succeeded",
  version: 1,
  planned_question_count: 3,
  planned_model_count: 8,
  planned_detection_points: 24,
  completed_calls: 24,
  successful_calls: 24,
  failed_calls: 0,
  cancelled_calls: 0,
  progress_percent: 100,
  queue_priority: 10,
  queue_position: null,
  cancel_requested: false,
  quota: {
    quota_type: "geo_detection_runs",
    status: "settled",
    held: 1,
    consumed: 1,
    released: 0,
  },
  queued_at: `2026-08-${String(index + 1).padStart(2, "0")}T00:00:00Z`,
  started_at: `2026-08-${String(index + 1).padStart(2, "0")}T00:00:01Z`,
  finished_at: `2026-08-${String(index + 1).padStart(2, "0")}T00:01:00Z`,
  cancelled_at: null,
  created_at: `2026-08-${String(index + 1).padStart(2, "0")}T00:00:00Z`,
  updated_at: `2026-08-${String(index + 1).padStart(2, "0")}T00:01:00Z`,
});

const detections = Array.from({ length: 25 }, (_, index) => detection(index));

describe("GeoDetectionIndexPage", () => {
  beforeAll(() => {
    const browserGetComputedStyle = window.getComputedStyle.bind(window);
    Object.defineProperty(window, "getComputedStyle", {
      configurable: true,
      value: (element: Element) => browserGetComputedStyle(element),
    });
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
    global.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  });

  beforeEach(() => {
    push.mockReset();
    getDetectionOptions.mockReset();
    getCurrentQuestionBank.mockReset();
    getDetectionHistory.mockReset();
    removeDetectionResult.mockReset();
    estimateDetection.mockReset();
    createDetection.mockReset();

    getDetectionOptions.mockResolvedValue({
      models: modelKeys.map((modelKey, index) => ({
        id: `model-${index + 1}`,
        model_key: modelKey,
        display_name: modelNames[index],
        selected_by_default: true,
        enabled: true,
        paused: false,
        configured: true,
      })),
      max_questions_per_detection: 100,
      max_models_per_detection: 8,
      available_detection_runs: 1000,
      can_start_job: true,
    });
    getCurrentQuestionBank.mockResolvedValue({
      id: "question-bank-1",
      version_no: 1,
      subject_version_id: "subject-version-1",
      distillation_set_id: "distillation-1",
      source_result_id: null,
      item_count: questions.length,
      confirmed_at: "2026-08-20T00:00:00Z",
      items: questions,
    });
    getDetectionHistory.mockImplementation((_subjectId: string, page: number) => {
      const start = (page - 1) * DETECTION_RESULT_PAGE_SIZE;
      return Promise.resolve({
        items: detections.slice(start, start + DETECTION_RESULT_PAGE_SIZE),
        pagination: {
          page,
          page_size: DETECTION_RESULT_PAGE_SIZE,
          count: detections.length,
          total_pages: 2,
        },
      });
    });
    removeDetectionResult.mockResolvedValue({ removed: true });
  });

  afterEach(cleanup);

  it("shows no more than 20 questions and 20 results while displaying all model names and logos", async () => {
    render(<GeoDetectionIndexPage />);

    expect(await screen.findByText("显问科技")).toBeTruthy();
    expect(screen.getAllByLabelText(/^选择问题：/)).toHaveLength(DETECTION_QUESTION_PAGE_SIZE);
    expect(screen.queryByLabelText("选择问题：检测问题 21")).toBeNull();
    expect(screen.getAllByLabelText(/^选择检测结果：/)).toHaveLength(DETECTION_RESULT_PAGE_SIZE);
    expect(screen.getAllByRole("img", { name: /标识$/ })).toHaveLength(8);
    for (const name of modelNames) expect(screen.getByText(name)).toBeTruthy();
    expect(
      screen.getByText("1. 选择检测问题").closest(".geo-detection-planner__questions"),
    ).toBeTruthy();
    expect(
      screen.getByText("2. 选择 AI 模型").closest(".geo-detection-planner__sidebar"),
    ).toBeTruthy();
    expect(screen.getByText("检测结果").closest(".geo-detection-results")).toBeTruthy();
  });

  it("keeps question selection across pages", async () => {
    const user = userEvent.setup();
    render(<GeoDetectionIndexPage />);
    await screen.findByText("显问科技");

    const firstQuestion = screen.getByLabelText("选择问题：检测问题 1");
    await user.click(firstQuestion);
    expect((firstQuestion as HTMLInputElement).checked).toBe(false);

    const questionCard = screen.getByText("1. 选择检测问题").closest(".ant-card");
    expect(questionCard).toBeTruthy();
    await user.click(within(questionCard as HTMLElement).getByTitle("2"));
    expect(await screen.findByLabelText("选择问题：检测问题 21")).toBeTruthy();
    await user.click(within(questionCard as HTMLElement).getByTitle("1"));
    expect(
      ((await screen.findByLabelText("选择问题：检测问题 1")) as HTMLInputElement).checked,
    ).toBe(false);
  });

  it("opens completed results directly and deletes selected results after confirmation", async () => {
    const user = userEvent.setup();
    render(<GeoDetectionIndexPage />);
    await screen.findByText("显问科技");

    expect(screen.getAllByRole("link", { name: "查看结果" })[0]?.getAttribute("href")).toBe(
      "/geo/detections/detection-20/report",
    );
    await user.click(screen.getAllByLabelText(/^选择检测结果：/)[0]);
    await user.click(screen.getByRole("button", { name: /删除所选/ }));
    expect(screen.getByText("确认删除检测结果")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() =>
      expect(removeDetectionResult).toHaveBeenCalledWith(subject.id, "detection-20"),
    );
    expect(await screen.findByText("已删除 1 条检测结果。")).toBeTruthy();
    await waitFor(() => expect(getDetectionHistory).toHaveBeenCalledTimes(2));
  });
});
