// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsDashboard } from "../components/admin/operations-dashboard";

const api = vi.hoisted(() => ({
  exportOperationsCustomers: vi.fn(),
  getModerationQueue: vi.fn(),
  getOperationsCustomers: vi.fn(),
  getOperationsDashboard: vi.fn(),
  getOperationsTasks: vi.fn(),
  getReleaseReadiness: vi.fn(),
}));

vi.mock("../lib/operations-client", () =>
  Object.fromEntries(
    Object.entries(api).map(([key, value]) => [key, (...args: unknown[]) => value(...args)]),
  ),
);

describe("Stage 3 operations and release-readiness dashboard", () => {
  beforeAll(() => {
    const nativeGetComputedStyle = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
      nativeGetComputedStyle(element),
    );
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
      })),
    });
    Object.defineProperty(URL, "createObjectURL", {
      writable: true,
      value: vi.fn(() => "blob:stage3-export"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      writable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  beforeEach(() => {
    api.exportOperationsCustomers.mockResolvedValue(new Blob(["customer_id\n"]));
    api.getOperationsDashboard.mockResolvedValue({
      customers: { total: 3, active: 2 },
      followups: { open: 2, overdue: 1 },
      feedback_open: 4,
      moderation: { articles: 1, images: 2 },
      task_counts: {},
      generated_at: "2026-08-21T00:00:00Z",
    });
    api.getReleaseReadiness.mockResolvedValue({
      status: "NOT_READY",
      generated_at: "2026-08-21T00:00:00Z",
      environment: "test",
      secrets_included: false,
      checks: [
        {
          key: "private_storage",
          status: "NOT_READY",
          required: true,
          code: "PRIVATE_STORAGE_NOT_CONFIGURED",
          safe_summary: { provider: "mock" },
        },
      ],
    });
    api.getOperationsCustomers.mockResolvedValue({ items: [], pagination: {} });
    api.getOperationsTasks.mockResolvedValue({ items: [], safe_projection: true });
    api.getModerationQueue.mockResolvedValue({ articles: [], images: [] });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows fail-closed external readiness without rendering raw configuration", async () => {
    render(<OperationsDashboard />);
    expect(await screen.findByText("发布状态：NOT_READY")).toBeTruthy();
    expect(screen.getByText("PRIVATE_STORAGE_NOT_CONFIGURED")).toBeTruthy();
    expect(screen.queryByText(/secret/i)).toBeNull();
    expect(screen.getByText("客户运营档案")).toBeTruthy();
    expect(screen.getByText("任务中心（无正文安全投影）")).toBeTruthy();
  });

  it("refreshes all operational projections together", async () => {
    const user = userEvent.setup();
    render(<OperationsDashboard />);
    await screen.findByText("发布状态：NOT_READY");
    await user.click(screen.getByRole("button", { name: "刷新安全状态" }));
    await waitFor(() => expect(api.getReleaseReadiness).toHaveBeenCalledTimes(2));
    expect(api.getOperationsTasks).toHaveBeenCalledTimes(2);
    expect(api.getOperationsCustomers).toHaveBeenCalledTimes(2);
  });

  it("runs the confirmed masked customer export through the dedicated API", async () => {
    const user = userEvent.setup();
    render(<OperationsDashboard />);
    await screen.findByText("发布状态：NOT_READY");
    await user.click(screen.getByRole("button", { name: "导出脱敏客户 CSV" }));
    await waitFor(() => expect(api.exportOperationsCustomers).toHaveBeenCalledTimes(1));
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:stage3-export");
  });
});
