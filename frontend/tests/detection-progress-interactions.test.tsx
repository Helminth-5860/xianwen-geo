// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import DetectionProgressPage, {
  DETECTION_POLL_INTERVAL_MS,
  DETECTION_QUEUED_MODELS_POLL_INTERVAL_MS,
  DETECTION_REQUEST_TIMEOUT_MS,
  DETECTION_RUNNING_POLL_INTERVAL_MS,
  DETECTION_STALE_QUEUE_MS,
} from "../app/geo/detections/[detectionId]/page";
import type { GeoDetectionJob, GeoModelProgress } from "../lib/geo-detection-client";

vi.mock("next/navigation", () => ({ useParams: () => ({ detectionId: "detection-42" }) }));

const getDetectionJob = vi.fn();
const getDetectionModelProgress = vi.fn();
vi.mock("../lib/geo-detection-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/geo-detection-client")>(
    "../lib/geo-detection-client",
  );
  return {
    ...actual,
    getDetectionJob: (...args: unknown[]) => getDetectionJob(...args),
    getDetectionModelProgress: (...args: unknown[]) => getDetectionModelProgress(...args),
  };
});

const job = (
  status: GeoDetectionJob["status"] = "running",
  overrides: Partial<GeoDetectionJob> = {},
): GeoDetectionJob => ({
  id: "detection-42",
  subject_id: "subject-7",
  status,
  version: 3,
  planned_question_count: 2,
  planned_model_count: 8,
  planned_detection_points: 16,
  completed_calls: status === "queued" ? 0 : status === "running" ? 8 : 16,
  successful_calls: status === "queued" ? 0 : status === "running" ? 6 : 12,
  failed_calls: status === "queued" ? 0 : status === "running" ? 1 : 2,
  cancelled_calls: status === "queued" ? 0 : status === "running" ? 1 : 2,
  progress_percent: status === "queued" ? 0 : status === "running" ? 50 : 100,
  queue_priority: 10,
  queue_position: null,
  cancel_requested: false,
  quota: {
    status: status === "running" ? "partially_settled" : "settled",
    held: 16,
    consumed: 12,
    released: 4,
  },
  queued_at: "2026-08-20T00:00:00Z",
  started_at: status === "queued" ? null : "2026-08-20T00:00:01Z",
  finished_at: status === "running" ? null : "2026-08-20T00:01:00Z",
  cancelled_at: null,
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:10Z",
  ...overrides,
});

const statuses: GeoModelProgress["status"][] = [
  "queued",
  "running",
  "partial",
  "succeeded",
  "failed",
  "cancelled",
  "running",
  "succeeded",
];
const models: GeoModelProgress[] = statuses.map((status, index) => ({
  model_id: `model-${index}`,
  model_key: `model-${index + 1}`,
  provider_key: `provider-${index}`,
  provider_model_id: `provider-model-${index}`,
  status,
  planned_calls: index === 1 ? 4 : 2,
  completed_calls: index === 1 ? 3 : ["queued", "running"].includes(status) ? 1 : 2,
  successful_calls: index === 1 ? 2 : status === "succeeded" ? 2 : 0,
  failed_calls: index === 1 ? 1 : status === "failed" ? 2 : 0,
  cancelled_calls: status === "cancelled" ? 2 : 0,
  web_search_used_count: 0,
  degraded_count: 0,
}));

describe("DetectionProgressPage", () => {
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
  });
  beforeEach(() => {
    getDetectionJob.mockReset();
    getDetectionModelProgress.mockReset();
    getDetectionJob.mockResolvedValue(job());
    getDetectionModelProgress.mockResolvedValue({ items: models });
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("restores from the route id and renders mixed selected-model and quota facts", async () => {
    render(<DetectionProgressPage />);
    expect(screen.getByText("正在恢复检测进度")).toBeTruthy();
    expect(await screen.findByText("GEO 检测进度")).toBeTruthy();
    expect(getDetectionJob).toHaveBeenCalledWith("detection-42", expect.any(AbortSignal));
    expect(getDetectionModelProgress).toHaveBeenCalledWith("detection-42", expect.any(AbortSignal));
    expect(screen.getByText("模型执行状态（共 8 个）")).toBeTruthy();
    expect(screen.getAllByText("50%").length).toBeGreaterThan(0);
    expect(screen.getByText("计划／冻结")).toBeTruthy();
    expect(screen.getByText("实际扣除")).toBeTruthy();
    expect(screen.getByText("返还／释放")).toBeTruthy();
    expect(screen.getByText("部分结算")).toBeTruthy();
    expect(screen.getByText("调用进度：3 / 4")).toBeTruthy();
    for (let index = 1; index <= 8; index += 1) {
      expect(screen.getByText(`model-${index}`)).toBeTruthy();
    }
  });

  it("polls a non-terminal job using the conservative interval", async () => {
    vi.useFakeTimers();
    render(<DetectionProgressPage />);
    await act(async () => void (await Promise.resolve()));
    expect(getDetectionJob).toHaveBeenCalledTimes(1);
    await act(async () => void (await vi.advanceTimersByTimeAsync(DETECTION_POLL_INTERVAL_MS)));
    expect(getDetectionJob).toHaveBeenCalledTimes(2);
  });

  it("stops polling at terminal completion and shows the next step", async () => {
    vi.useFakeTimers();
    getDetectionJob.mockResolvedValue(job("succeeded"));
    render(<DetectionProgressPage />);
    await act(async () => void (await Promise.resolve()));
    expect(screen.getByRole("link", { name: "查看检测报告" }).getAttribute("href")).toBe(
      "/geo/detections/detection-42/report",
    );
    expect(screen.getByRole("link", { name: "返回主体" }).getAttribute("href")).toBe(
      "/subjects/subject-7",
    );
    await act(async () => void (await vi.advanceTimersByTimeAsync(DETECTION_POLL_INTERVAL_MS * 2)));
    expect(getDetectionJob).toHaveBeenCalledTimes(1);
  });

  it("shows an API failure and allows retry", async () => {
    getDetectionJob.mockRejectedValueOnce(new Error("网络暂不可用"));
    render(<DetectionProgressPage />);
    expect(await screen.findByText("检测进度加载失败")).toBeTruthy();
    expect(screen.getByText("网络暂不可用")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /重\s*试/ }));
    await waitFor(() => expect(getDetectionJob).toHaveBeenCalledTimes(2));
  });

  it("automatically recovers after a transient polling failure", async () => {
    vi.useFakeTimers();
    getDetectionJob
      .mockResolvedValueOnce(
        job("queued", {
          queue_position: 1,
          queued_at: new Date(Date.now() - 5_000).toISOString(),
        }),
      )
      .mockRejectedValueOnce(new Error("网络暂不可用"))
      .mockResolvedValue(job("running"));

    render(<DetectionProgressPage />);
    await act(async () => void (await Promise.resolve()));
    await act(async () => void (await vi.advanceTimersByTimeAsync(DETECTION_POLL_INTERVAL_MS)));
    expect(screen.getByText("检测进度刷新失败，系统会自动重试")).toBeTruthy();

    await act(async () => void (await vi.advanceTimersByTimeAsync(DETECTION_POLL_INTERVAL_MS)));
    expect(getDetectionJob).toHaveBeenCalledTimes(3);
    expect(screen.getAllByText("检测中").length).toBeGreaterThan(0);
    expect(screen.queryByText("检测进度刷新失败，系统会自动重试")).toBeNull();
  });

  it("times out a hanging detail request and keeps retrying without overlap", async () => {
    vi.useFakeTimers();
    let abortedRequests = 0;
    getDetectionJob.mockImplementation(
      (_detectionId: string, signal: AbortSignal) =>
        new Promise<GeoDetectionJob>((_resolve, reject) => {
          signal.addEventListener("abort", () => {
            abortedRequests += 1;
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          });
        }),
    );

    render(<DetectionProgressPage />);
    await act(
      async () => void (await vi.advanceTimersByTimeAsync(DETECTION_REQUEST_TIMEOUT_MS - 1)),
    );
    expect(getDetectionJob).toHaveBeenCalledTimes(1);

    await act(async () => void (await vi.advanceTimersByTimeAsync(1)));
    expect(abortedRequests).toBe(1);
    expect(screen.getByText("请求超时，系统正在自动重试")).toBeTruthy();
    await act(async () => void (await vi.advanceTimersByTimeAsync(DETECTION_POLL_INTERVAL_MS)));
    expect(getDetectionJob).toHaveBeenCalledTimes(2);
  });

  it("offers a manual model-detail retry after the job is terminal", async () => {
    getDetectionJob.mockResolvedValue(job("succeeded"));
    getDetectionModelProgress.mockRejectedValueOnce(new Error("模型明细接口暂不可用"));

    render(<DetectionProgressPage />);
    expect(await screen.findByText("模型明细暂时未更新")).toBeTruthy();
    expect(screen.queryByText("模型明细暂时未更新，系统会自动重试")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "重新加载明细" }));
    await waitFor(() => expect(getDetectionModelProgress).toHaveBeenCalledTimes(2));
  });

  it("keeps the overall job fresh when model progress temporarily fails", async () => {
    vi.useFakeTimers();
    getDetectionModelProgress.mockRejectedValue(new Error("模型明细接口暂不可用"));

    render(<DetectionProgressPage />);
    await act(async () => void (await Promise.resolve()));
    expect(screen.getByText("GEO 检测进度")).toBeTruthy();
    expect(screen.getByText("模型明细暂时未更新，系统会自动重试")).toBeTruthy();

    await act(
      async () => void (await vi.advanceTimersByTimeAsync(DETECTION_RUNNING_POLL_INTERVAL_MS)),
    );
    expect(getDetectionJob).toHaveBeenCalledTimes(2);
  });

  it("polls queued model details less often than the job summary", async () => {
    vi.useFakeTimers();
    getDetectionJob.mockResolvedValue(
      job("queued", {
        queue_position: 1,
        queued_at: new Date(Date.now() - 5_000).toISOString(),
      }),
    );

    render(<DetectionProgressPage />);
    await act(async () => void (await Promise.resolve()));
    expect(getDetectionModelProgress).toHaveBeenCalledTimes(1);

    await act(
      async () =>
        void (await vi.advanceTimersByTimeAsync(DETECTION_QUEUED_MODELS_POLL_INTERVAL_MS - 1)),
    );
    expect(getDetectionJob.mock.calls.length).toBeGreaterThan(1);
    expect(getDetectionModelProgress).toHaveBeenCalledTimes(1);

    await act(async () => void (await vi.advanceTimersByTimeAsync(1)));
    expect(getDetectionModelProgress).toHaveBeenCalledTimes(2);
  });

  it("shows queue duration, last refresh, and a stale queue warning", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-27T06:00:00Z"));
    getDetectionJob.mockResolvedValue(
      job("queued", {
        queue_position: 1,
        queued_at: new Date(Date.now() - DETECTION_STALE_QUEUE_MS - 5_000).toISOString(),
      }),
    );

    render(<DetectionProgressPage />);
    await act(async () => void (await Promise.resolve()));
    expect(screen.getByText(/已排队 1 分 5 秒/)).toBeTruthy();
    expect(screen.getByText("任务长时间未被执行器领取")).toBeTruthy();
    expect(screen.getByText(/最后刷新：/)).toBeTruthy();
  });
});
