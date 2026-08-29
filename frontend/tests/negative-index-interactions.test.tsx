// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import NegativeIndexPage from "../app/geo/data-center/negative-index/page";
import type {
  NegativeEvent,
  NegativeEventDetail,
  NegativeIndexScanDetail,
  NegativeIndexScanSummary,
  NegativeIndexState,
} from "../lib/negative-index-client";

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
const getNegativeIndexState = vi.fn();
const startNegativeIndexScan = vi.fn();
const getNegativeIndexScan = vi.fn();
const getNegativeIndexEvents = vi.fn();
const getNegativeEvent = vi.fn();

vi.mock("../components/subject-workspace-context", () => ({
  useSubjectWorkspace: () => workspace,
}));

vi.mock("../lib/negative-index-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/negative-index-client")>(
    "../lib/negative-index-client",
  );
  return {
    ...actual,
    getNegativeIndexState: (...args: unknown[]) => getNegativeIndexState(...args),
    startNegativeIndexScan: (...args: unknown[]) => startNegativeIndexScan(...args),
    getNegativeIndexScan: (...args: unknown[]) => getNegativeIndexScan(...args),
    getNegativeIndexEvents: (...args: unknown[]) => getNegativeIndexEvents(...args),
    getNegativeEvent: (...args: unknown[]) => getNegativeEvent(...args),
  };
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function scan(
  id: string,
  subjectId: string,
  overrides: Partial<NegativeIndexScanSummary> = {},
): NegativeIndexScanSummary {
  return {
    id,
    subject_id: subjectId,
    status: "succeeded",
    stage: "completed",
    provider: "public-search",
    ai_provider: "semantic-analysis",
    ai_model_key: "analysis-model",
    query_count: 8,
    provider_request_count: 8,
    provider_error_count: 0,
    raw_result_count: 32,
    unique_result_count: 24,
    candidate_count: 6,
    negative_item_count: 3,
    event_count: 2,
    high_risk_event_count: 1,
    recent_30d_event_count: 1,
    verified_item_count: 1,
    index_score: "42.00",
    risk_level: "watch",
    factor_scores: {},
    progress: {},
    formula_version: "v1",
    classifier_version: "v1",
    stable_error_code: "",
    elapsed_seconds: 12,
    started_at: "2026-08-29T08:00:00Z",
    finished_at: "2026-08-29T08:00:12Z",
    created_at: "2026-08-29T08:00:00Z",
    ...overrides,
  };
}

function result(id: string, subjectId: string): NegativeIndexScanDetail {
  return {
    ...scan(id, subjectId),
    category_distribution: [{ category: "media_negative", count: 2 }],
    status_distribution: [{ status: "reported", count: 2 }],
  };
}

function event(id: string, title: string): NegativeEvent {
  return {
    id,
    category: "media_negative",
    claim_type: "reported_fact",
    status: "reported",
    title,
    summary: `${title}摘要`,
    severity_score: 50,
    evidence_score: 70,
    visibility_score: 60,
    freshness_score: 80,
    current_risk: "45.00",
    source_count: 2,
    independent_domain_count: 2,
    first_seen_at: "2026-08-28T08:00:00Z",
    last_seen_at: "2026-08-29T08:00:00Z",
  };
}

function eventDetail(item: NegativeEvent, summary = item.summary): NegativeEventDetail {
  return {
    ...item,
    summary,
    sources: [
      {
        id: `source-${item.id}`,
        original_url: "https://example.com/report",
        domain: "example.com",
        root_domain: "example.com",
        website: "示例媒体",
        title: "公开报道",
        snippet: "公开报道摘要",
        published_at: "2026-08-29T08:00:00Z",
        source_type: "news_media",
        authority_score: 80,
        relevance_score: 90,
        visibility_score: 60,
        freshness_score: 80,
        best_rank: 1,
        matched_query_count: 1,
        matched_queries: ["测试"],
        rule_signal_score: 70,
        negative_confidence: 80,
        severity_score: 50,
        evidence_confidence: 70,
        category: item.category,
        claim_type: item.claim_type,
        event_status: item.status,
        event_title: item.title,
        ai_summary: "",
        classification_source: "rule",
        verification_status: "succeeded",
        verification_excerpt: "已核验的公开内容",
        verification_error_code: "",
      },
    ],
  };
}

function emptyState(): NegativeIndexState {
  return { active_scan: null, latest_result: null, history: [] };
}

beforeAll(() => {
  const browserGetComputedStyle = window.getComputedStyle.bind(window);
  Object.defineProperty(window, "getComputedStyle", {
    configurable: true,
    value: (element: Element) => browserGetComputedStyle(element),
  });
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
  workspace = { currentSubject: subjectA, loading: false };
  getNegativeIndexState.mockReset();
  startNegativeIndexScan.mockReset();
  getNegativeIndexScan.mockReset();
  getNegativeIndexEvents.mockReset();
  getNegativeEvent.mockReset();
  getNegativeIndexState.mockResolvedValue(emptyState());
  getNegativeIndexEvents.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
});

afterEach(cleanup);

describe("负面信息指数页面", () => {
  it("按当前主体启动扫描并只展示中文产品文案", async () => {
    const user = userEvent.setup();
    startNegativeIndexScan.mockResolvedValue(
      scan("scan-running", subjectA.id, {
        status: "running",
        stage: "searching",
        unique_result_count: 3,
      }),
    );

    render(<NegativeIndexPage />);

    expect(await screen.findByRole("heading", { name: "负面信息指数" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "开始首次扫描" }));

    await waitFor(() => expect(startNegativeIndexScan).toHaveBeenCalledWith(subjectA.id));
    expect(await screen.findByText("正在扫描公开网络")).toBeTruthy();
    expect(screen.queryByText(/AI|百度请求|原始结果/)).toBeNull();
  });

  it("每页固定读取二十条事件，支持翻页和查看公开证据", async () => {
    const latest = result("scan-a", subjectA.id);
    const events = Array.from({ length: 21 }, (_, index) =>
      event(`event-${index + 1}`, `风险事件 ${index + 1}`),
    );
    getNegativeIndexState.mockResolvedValue({
      active_scan: null,
      latest_result: latest,
      history: [latest],
    });
    getNegativeIndexEvents.mockImplementation(
      (_scanId: string, options: { page: number; pageSize: number }) => {
        const start = (options.page - 1) * options.pageSize;
        return Promise.resolve({
          count: events.length,
          next: options.page === 1 ? "next" : null,
          previous: options.page === 2 ? "previous" : null,
          results: events.slice(start, start + options.pageSize),
        });
      },
    );
    getNegativeEvent.mockImplementation((eventId: string) => {
      const selected = events.find((item) => item.id === eventId) ?? events[0];
      return Promise.resolve(eventDetail(selected, "风险事件详情摘要"));
    });
    const user = userEvent.setup();

    render(<NegativeIndexPage />);

    expect(await screen.findByText("风险事件 1")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /风险事件/ })).toHaveLength(20);
    expect(getNegativeIndexEvents).toHaveBeenCalledWith(
      latest.id,
      expect.objectContaining({ page: 1, pageSize: 20 }),
    );

    await user.click(screen.getByTitle("2"));
    expect(await screen.findByText("风险事件 21")).toBeTruthy();
    expect(getNegativeIndexEvents).toHaveBeenLastCalledWith(
      latest.id,
      expect.objectContaining({ page: 2, pageSize: 20 }),
    );

    await user.click(screen.getByRole("button", { name: "风险事件 21" }));
    expect(await screen.findByText("风险事件详情摘要")).toBeTruthy();
    expect(screen.getByRole("link", { name: /查看原文/ }).getAttribute("href")).toBe(
      "https://example.com/report",
    );
    expect(screen.queryByText(/AI|百度请求|原始结果/)).toBeNull();
  });

  it("切换主体后清空旧事件和详情，并从第一页读取新主体数据", async () => {
    const resultA = result("scan-a", subjectA.id);
    const resultB = result("scan-b", subjectB.id);
    const eventA = event("event-a", "甲公司旧事件");
    const eventB = event("event-b", "乙公司新事件");
    const detailA = deferred<NegativeEventDetail>();
    const eventsB = deferred<{
      count: number;
      next: string | null;
      previous: string | null;
      results: NegativeEvent[];
    }>();

    getNegativeIndexState.mockImplementation((subjectId: string) =>
      Promise.resolve({
        active_scan: null,
        latest_result: subjectId === subjectA.id ? resultA : resultB,
        history: [subjectId === subjectA.id ? resultA : resultB],
      }),
    );
    getNegativeIndexEvents.mockImplementation(
      (scanId: string, options: { page: number; pageSize: number }) => {
        if (scanId === resultB.id) return eventsB.promise;
        return Promise.resolve({
          count: 21,
          next: options.page === 1 ? "next" : null,
          previous: options.page === 2 ? "previous" : null,
          results:
            options.page === 1
              ? Array.from({ length: 20 }, (_, index) =>
                  event(`a-${index}`, `甲公司事件 ${index + 1}`),
                )
              : [eventA],
        });
      },
    );
    getNegativeEvent.mockReturnValue(detailA.promise);
    const user = userEvent.setup();
    const view = render(<NegativeIndexPage />);

    expect(await screen.findByText("甲公司事件 1")).toBeTruthy();
    await user.click(screen.getByTitle("2"));
    expect(await screen.findByText(eventA.title)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: eventA.title }));

    workspace = { currentSubject: subjectB, loading: false };
    view.rerender(<NegativeIndexPage />);

    await waitFor(() => expect(getNegativeIndexState).toHaveBeenCalledWith(subjectB.id));
    await waitFor(() =>
      expect(getNegativeIndexEvents).toHaveBeenCalledWith(
        resultB.id,
        expect.objectContaining({ page: 1, pageSize: 20 }),
      ),
    );
    expect(screen.queryByText(eventA.title)).toBeNull();

    await act(async () => {
      detailA.resolve(eventDetail(eventA, "不应重新出现的旧主体详情"));
      await detailA.promise;
    });
    expect(screen.queryByText("不应重新出现的旧主体详情")).toBeNull();

    await act(async () => {
      eventsB.resolve({ count: 1, next: null, previous: null, results: [eventB] });
      await eventsB.promise;
    });
    expect(await screen.findByText(eventB.title)).toBeTruthy();
    expect(screen.queryByText(eventA.title)).toBeNull();
  });

  it("关闭正在加载的详情后，迟到的结果不会重新打开详情", async () => {
    const latest = result("scan-a", subjectA.id);
    const item = event("event-a", "等待查看的事件");
    const pendingDetail = deferred<NegativeEventDetail>();
    getNegativeIndexState.mockResolvedValue({
      active_scan: null,
      latest_result: latest,
      history: [latest],
    });
    getNegativeIndexEvents.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [item],
    });
    getNegativeEvent.mockReturnValue(pendingDetail.promise);
    const user = userEvent.setup();

    render(<NegativeIndexPage />);
    await user.click(await screen.findByRole("button", { name: item.title }));
    const closeButton = document.querySelector<HTMLButtonElement>(".ant-modal-close");
    expect(closeButton).toBeTruthy();
    await user.click(closeButton as HTMLButtonElement);

    await act(async () => {
      pendingDetail.resolve(eventDetail(item, "迟到的详情内容"));
      await pendingDetail.promise;
    });
    await waitFor(() => expect(screen.queryByText("迟到的详情内容")).toBeNull());
  });
});
