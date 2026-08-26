// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import PublicHome from "../app/page";
import WorkspacePage from "../app/workspace/page";
import {
  SubjectWorkspaceProvider,
  SubjectWorkspaceTopbar,
  useSubjectSwitchGuard,
} from "../components/subject-workspace-context";
import { UserWorkspaceNavigation } from "../components/user-workspace-navigation";
import { subjectSwitchTargetPath } from "../lib/subjects-client";

const getCurrentUser = vi.fn();
const getSubjects = vi.fn();
const setCurrentSubject = vi.fn();
const navigateWorkspaceAfterSubjectChange = vi.fn();
const getReportHistory = vi.fn();
const getQuestionBankDraft = vi.fn();
let pathname = "/workspace";
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  redirect: (href: string) => replace(href),
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
  return {
    ...actual,
    getSubjects: (...args: unknown[]) => getSubjects(...args),
    setCurrentSubject: (...args: unknown[]) => setCurrentSubject(...args),
    navigateWorkspaceAfterSubjectChange: (...args: unknown[]) =>
      navigateWorkspaceAfterSubjectChange(...args),
  };
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
  account_status: "active" as const,
  commercial_identity: "USER" as const,
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
  service_regions: JSON.stringify({ version: 1, nationwide: true, areas: [] }),
  retest_required: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};

const otherSubject = {
  ...subject,
  id: "subject-2",
  is_current: false,
  official_name: "显问华南",
  updated_at: "2026-08-21T00:00:00Z",
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

const renderInWorkspace = (component: React.ReactNode) =>
  render(<SubjectWorkspaceProvider>{component}</SubjectWorkspaceProvider>);

function DirtyWorkspace({ save }: Readonly<{ save: () => Promise<boolean> }>) {
  useSubjectSwitchGuard("test-dirty-page", true, save);
  return <div>存在未保存修改</div>;
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
  pathname = "/workspace";
  getCurrentUser.mockResolvedValue(user);
  getSubjects.mockResolvedValue({
    subjects: [subject],
    context: { current_subject_id: subject.id, version: 1 },
  });
  getReportHistory.mockResolvedValue({ items: [latestReport] });
  getQuestionBankDraft.mockResolvedValue({ current_question_bank_version_no: 3 });
  setCurrentSubject.mockResolvedValue({ current_subject_id: subject.id, version: 2 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("GEO 产品工作台", () => {
  it("公开首页统一进入登录入口", () => {
    PublicHome();
    expect(replace).toHaveBeenCalledWith("/login");
  });

  it("工作台直接展示当前主体、真实 GEO 指标和完整优化主线", async () => {
    renderInWorkspace(<WorkspacePage />);
    expect(await screen.findByRole("heading", { name: "GEO 总览" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "显问科技" })).toBeTruthy();
    expect(screen.getAllByText("68.2").length).toBeGreaterThan(0);
    expect(screen.getByText("1. 主体档案")).toBeTruthy();
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
    renderInWorkspace(<WorkspacePage />);
    expect(await screen.findByText("还没有当前 GEO 主体")).toBeTruthy();
    expect(screen.getByRole("link", { name: "创建并选择主体" }).getAttribute("href")).toBe(
      "/subjects",
    );
    expect(screen.queryByText("显问 AI 助手")).toBeNull();
  });

  it("未登录访问工作台时回登录页，而不是显示产品宣传页", async () => {
    getCurrentUser.mockRejectedValue(Object.assign(new Error("unauthenticated"), { status: 401 }));
    renderInWorkspace(<WorkspacePage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("创建账号")).toBeNull();
  });

  it("左侧导航按最终结构使用单开 accordion，并高亮当前二级菜单", async () => {
    const shell = () => (
      <SubjectWorkspaceProvider>
        <SubjectWorkspaceTopbar />
        <UserWorkspaceNavigation />
      </SubjectWorkspaceProvider>
    );
    const { rerender } = render(shell());
    expect(await screen.findByRole("navigation", { name: "GEO 工作台导航" })).toBeTruthy();
    expect(screen.getByLabelText("Workspace 当前主体")).toBeTruthy();
    expect(screen.getByRole("link", { name: "GEO 总览" }).getAttribute("href")).toBe("/workspace");
    for (const label of [
      "主体档案",
      "关键词中心",
      "问题库",
      "检测中心",
      "GEO 洞察",
      "知识图谱建设",
      "优化中心",
      "内容资产中心",
    ]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    expect(screen.getByRole("link", { name: "套餐与额度" })).toBeTruthy();
    expect(screen.queryByText("验证优化效果")).toBeNull();

    const subjectMenu = screen.getByRole("menuitem", { name: /主体档案/ });
    expect(subjectMenu.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(screen.getByText("主体档案"));
    expect(subjectMenu.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("link", { name: "编辑主体" }).getAttribute("href")).toBe(
      "/subjects/subject-1",
    );
    expect(screen.getByRole("link", { name: "主体管理" }).getAttribute("href")).toBe("/subjects");
    await userEvent.click(screen.getByText("主体档案"));
    expect(subjectMenu.getAttribute("aria-expanded")).toBe("false");

    await userEvent.click(screen.getByText("关键词中心"));
    expect(screen.getByRole("link", { name: "智能关键词" }).getAttribute("href")).toBe(
      "/subjects/subject-1/keywords",
    );
    expect(screen.getByRole("link", { name: "自定义关键词" }).getAttribute("href")).toBe(
      "/subjects/subject-1/keywords/custom",
    );
    expect(screen.getByRole("link", { name: "关键词蒸馏" }).getAttribute("href")).toBe(
      "/subjects/subject-1/keywords/distill",
    );
    expect(screen.getByRole("link", { name: "关键词资产" }).getAttribute("href")).toBe(
      "/subjects/subject-1/keywords/assets",
    );

    await userEvent.click(screen.getByText("问题库"));
    expect(screen.getByRole("link", { name: "问题生成" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "问题管理" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /关键词中心/ }).getAttribute("aria-expanded")).toBe(
      "false",
    );
    expect(screen.queryByRole("link", { name: "显问 AI 助手" })).toBeNull();

    pathname = "/admin";
    rerender(shell());
    await waitFor(() =>
      expect(screen.queryByRole("navigation", { name: "GEO 工作台导航" })).toBeNull(),
    );
  });

  it("切换当前主体后刷新整个工作区，避免保留上一个主体的页面状态", async () => {
    getSubjects.mockResolvedValue({
      subjects: [subject, otherSubject],
      context: { current_subject_id: subject.id, version: 7 },
    });
    render(
      <SubjectWorkspaceProvider>
        <SubjectWorkspaceTopbar />
      </SubjectWorkspaceProvider>,
    );
    const selector = await screen.findByLabelText("Workspace 当前主体");
    await userEvent.click(selector);
    await userEvent.click(await screen.findByText("显问华南"));

    await waitFor(() => expect(setCurrentSubject).toHaveBeenCalledWith("subject-2", 7));
    expect(navigateWorkspaceAfterSubjectChange).toHaveBeenCalledWith("/workspace", "subject-2");
  });

  it("动态主体路由切换到同一功能的新主体，历史对象详情回到所属模块列表", () => {
    expect(subjectSwitchTargetPath("/subjects/subject-1/keywords", "subject-2")).toBe(
      "/subjects/subject-2/keywords",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/keywords/distill", "subject-2")).toBe(
      "/subjects/subject-2/keywords/distill",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/keywords/custom", "subject-2")).toBe(
      "/subjects/subject-2/keywords/custom",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/keywords/assets", "subject-2")).toBe(
      "/subjects/subject-2/keywords/assets",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/versions/version-1", "subject-2")).toBe(
      "/subjects/subject-2",
    );
    expect(subjectSwitchTargetPath("/geo/reports/report-1", "subject-2")).toBe("/geo/reports");
    expect(subjectSwitchTargetPath("/geo/detections/detection-1", "subject-2")).toBe(
      "/geo/detections",
    );
  });

  it("有未保存修改时先确认，保存成功后才切换主体", async () => {
    pathname = "/subjects/subject-1/keywords";
    getSubjects.mockResolvedValue({
      subjects: [subject, otherSubject],
      context: { current_subject_id: subject.id, version: 7 },
    });
    const save = vi.fn().mockResolvedValue(true);
    render(
      <SubjectWorkspaceProvider>
        <SubjectWorkspaceTopbar />
        <DirtyWorkspace save={save} />
      </SubjectWorkspaceProvider>,
    );
    const selector = await screen.findByLabelText("Workspace 当前主体");
    await userEvent.click(selector);
    await userEvent.click(await screen.findByText("显问华南"));
    expect(await screen.findByText("当前页面有未保存修改")).toBeTruthy();
    expect(setCurrentSubject).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "保存后切换" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(setCurrentSubject).toHaveBeenCalledWith("subject-2", 7));
    expect(navigateWorkspaceAfterSubjectChange).toHaveBeenCalledWith(
      "/subjects/subject-1/keywords",
      "subject-2",
    );
  });
});
