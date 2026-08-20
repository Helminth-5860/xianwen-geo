// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import DetectionProgressPage, {
  DETECTION_POLL_INTERVAL_MS,
} from "../app/geo/detections/[detectionId]/page";
import type { GeoDetectionJob, GeoModelProgress } from "../lib/geo-detection-client";

vi.mock("next/navigation", () => ({ useParams: () => ({ detectionId: "detection-42" }) }));

const getDetectionProgress = vi.fn();
vi.mock("../lib/geo-detection-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/geo-detection-client")>(
    "../lib/geo-detection-client",
  );
  return { ...actual, getDetectionProgress: (...args: unknown[]) => getDetectionProgress(...args) };
});

const job = (status: GeoDetectionJob["status"] = "running"): GeoDetectionJob => ({
  id: "detection-42",
  subject_id: "subject-7",
  status,
  version: 3,
  planned_question_count: 2,
  planned_model_count: 8,
  planned_detection_points: 16,
  completed_calls: status === "running" ? 8 : 16,
  successful_calls: status === "running" ? 6 : 12,
  failed_calls: status === "running" ? 1 : 2,
  cancelled_calls: status === "running" ? 1 : 2,
  progress_percent: status === "running" ? 50 : 100,
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
  started_at: "2026-08-20T00:00:01Z",
  finished_at: status === "running" ? null : "2026-08-20T00:01:00Z",
  cancelled_at: null,
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:10Z",
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
    getDetectionProgress.mockReset();
    getDetectionProgress.mockResolvedValue({ job: job(), models });
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("restores from the route id and renders mixed selected-model and quota facts", async () => {
    render(<DetectionProgressPage />);
    expect(screen.getByText("正在恢复检测进度")).toBeTruthy();
    expect(await screen.findByText("GEO 检测进度")).toBeTruthy();
    expect(getDetectionProgress).toHaveBeenCalledWith("detection-42");
    expect(screen.getByText("模型状态（8/8）")).toBeTruthy();
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
    expect(getDetectionProgress).toHaveBeenCalledTimes(1);
    await act(async () => void (await vi.advanceTimersByTimeAsync(DETECTION_POLL_INTERVAL_MS)));
    expect(getDetectionProgress).toHaveBeenCalledTimes(2);
  });

  it("stops polling at terminal completion and shows the next step", async () => {
    vi.useFakeTimers();
    getDetectionProgress.mockResolvedValue({ job: job("succeeded"), models });
    render(<DetectionProgressPage />);
    await act(async () => void (await Promise.resolve()));
    expect(screen.getByRole("link", { name: "返回主体" }).getAttribute("href")).toBe(
      "/subjects/subject-7",
    );
    await act(async () => void (await vi.advanceTimersByTimeAsync(DETECTION_POLL_INTERVAL_MS * 2)));
    expect(getDetectionProgress).toHaveBeenCalledTimes(1);
  });

  it("shows an API failure and allows retry", async () => {
    getDetectionProgress.mockRejectedValueOnce(new Error("网络暂不可用"));
    render(<DetectionProgressPage />);
    expect(await screen.findByText("检测进度加载失败")).toBeTruthy();
    expect(screen.getByText("网络暂不可用")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /重\s*试/ }));
    await waitFor(() => expect(getDetectionProgress).toHaveBeenCalledTimes(2));
  });
});
