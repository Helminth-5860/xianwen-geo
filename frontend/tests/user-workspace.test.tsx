// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import PublicHome from "../app/page";
import WorkspacePage from "../app/workspace/page";
import { UserWorkspaceNavigation } from "../components/user-workspace-navigation";

const getCurrentUser = vi.fn();
const getSubjects = vi.fn();
const getReportHistory = vi.fn();
const getQuestionBankDraft = vi.fn();
let pathname = "/workspace";
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ replace }),
}));
vi.mock("../lib/auth-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/auth-client")>("../lib/auth-client");
  return { ...actual, getCurrentUser: (...args: unknown[]) => getCurrentUser(...args) };
});
vi.mock("../lib/subjects-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/subjects-client")>("../lib/subjects-client");
  return { ...actual, getSubjects: (...args: unknown[]) => getSubjects(...args) };
});
vi.mock("../lib/geo-report-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/geo-report-client")>(
    "../lib/geo-report-client",
  );
  return { ...actual, getReportHistory: (...args: unknown[]) => getReportHistory(...args) };
});
vi.mock("../lib/question-bank-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/question-bank-client")>(
    "../lib/question-bank-client",
  );
  return {
    ...actual,
    getQuestionBankDraft: (...args: unknown[]) => getQuestionBankDraft(...args),
  };
});

const user = {
  id: "user-1",
  nickname: "预览用户",
  phone_masked: "masked",
  approval_status: "approved" as const,
  account_status: "active" as const,
  commercial_identity: "END_USER" as const,
  home_route: "/workspace" as const,
  tenant: {
    id: "tenant-1",
    key: "preview",
    display_name: "预览租户",
    brand_name: "显问 GEO",
    logo_reference: "",
  },
};

const subject = {
  id: "subject-1",
  subject_type: { id: "type-1", key: "company", name: "企业", icon_key: "company" },
  status: "active" as const,
  version: 3,
  is_current: true,
  current_version_no: 2,
  official_name: "显问科技",
  retest_required: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};

const latestReport = {
  id: "report-1",
  detection_id: "detection-1",
  subject_id: "subject-1",
  subject_version_id: "subject-version-1",
  retest_mode: "" as const,
  summary: {
    geo: { score: "68.2", grade: "B", status: "formal" as const },
    brand_reputation: { score: "72.0", grade: "B", status: "formal" as const },
    exposure: {
      exposure_index: "61.4",
      grade: "B",
      status: "formal" as const,
      disclaimer: "",
      mention_rate_score: "58.0",
      recommendation_rate_score: "47.0",
      ranking_performance_score: "63.0",
      model_coverage_score: "75.0",
    },
    models: [],
    dimensions: {},
    competitors: [],
  },
  provenance: { scoring_rule_version: "v1", questions: [], models: [] },
  comparison: null,
  generated_at: "2026-08-22T08:00:00Z",
};

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
  pathname = "/workspace";
  getCurrentUser.mockResolvedValue(user);
  getSubjects.mockResolvedValue({
    subjects: [subject],
    context: { current_subject_id: subject.id, version: 1 },
  });
  getReportHistory.mockResolvedValue({ items: [latestReport] });
  getQuestionBankDraft.mockResolvedValue({ current_question_bank_version_no: 3 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("GEO 产品工作台", () => {
  it("已登录用户从公开首页进入工作台", async () => {
    render(<PublicHome />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspace"));
  });

  it("工作台直接展示当前主体、真实 GEO 指标和完整优化主线", async () => {
    render(<WorkspacePage />);
    expect(await screen.findByRole("heading", { name: "GEO 总览" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "显问科技" })).toBeTruthy();
    expect(screen.getAllByText("68.2").length).toBeGreaterThan(0);
    expect(screen.getByText("1. 主体与知识")).toBeTruthy();
    expect(screen.getByText("3. AI 可见度检测")).toBeTruthy();
    expect(screen.getByText("5. 优化策略")).toBeTruthy();
    expect(screen.getByText("7. 复测验证")).toBeTruthy();
    expect(screen.queryByText("欢迎回来")).toBeNull();
    expect(screen.queryByText("当前没有生效套餐，但工作台功能仍然可见")).toBeNull();
    expect(screen.queryByText("显问 AI 助手")).toBeNull();
    expect(screen.queryByText("套餐目录")).toBeNull();
  });

  it("没有当前主体时只引导进入 GEO 主流程，不展示官网式功能介绍", async () => {
    getSubjects.mockResolvedValue({
      subjects: [],
      context: { current_subject_id: null, version: 0 },
    });
    render(<WorkspacePage />);
    expect(await screen.findByText("还没有当前 GEO 主体")).toBeTruthy();
    expect(screen.getByRole("link", { name: "创建并选择主体" }).getAttribute("href")).toBe(
      "/subjects",
    );
    expect(screen.queryByText("显问 AI 助手")).toBeNull();
  });

  it("未登录访问工作台时回登录页，而不是显示产品宣传页", async () => {
    getCurrentUser.mockRejectedValue(Object.assign(new Error("unauthenticated"), { status: 401 }));
    render(<WorkspacePage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("创建账号")).toBeNull();
  });

  it("左侧导航按 GEO 主线组织，并彻底移除内部 AI 对话入口", async () => {
    const { rerender } = render(<UserWorkspaceNavigation />);
    expect(await screen.findByRole("navigation", { name: "GEO 工作台导航" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "GEO 总览" }).getAttribute("href")).toBe("/workspace");
    expect(screen.getByRole("link", { name: "关键词与问题" }).getAttribute("href")).toBe(
      "/subjects/subject-1/keywords",
    );
    expect(screen.getByRole("link", { name: "AI 可见度检测" }).getAttribute("href")).toBe(
      "/geo/detections",
    );
    expect(screen.getByRole("link", { name: "GEO 报告与洞察" }).getAttribute("href")).toBe(
      "/geo/reports",
    );
    expect(screen.getByRole("link", { name: "优化策略" }).getAttribute("href")).toBe(
      "/geo/strategy",
    );
    expect(screen.getByRole("link", { name: "内容执行" }).getAttribute("href")).toBe(
      "/subjects/subject-1/articles/new",
    );
    expect(screen.getByRole("link", { name: "复测验证" }).getAttribute("href")).toBe("/geo/retest");
    expect(screen.queryByRole("link", { name: "显问 AI 助手" })).toBeNull();

    pathname = "/admin";
    rerender(<UserWorkspaceNavigation />);
    await waitFor(() =>
      expect(screen.queryByRole("navigation", { name: "GEO 工作台导航" })).toBeNull(),
    );
  });
});
