// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
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
import { SUBJECT_CONTEXT_UPDATED_EVENT, subjectSwitchTargetPath } from "../lib/subjects-client";

const getCurrentUser = vi.fn();
const getSubjects = vi.fn();
const setCurrentSubject = vi.fn();
const navigateWorkspaceAfterSubjectChange = vi.fn();
const getReportHistory = vi.fn();
const getReportTrends = vi.fn();
const getDetectionHistory = vi.fn();
const getQuestionBankDraft = vi.fn();
const getStrategies = vi.fn();
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
  return {
    ...actual,
    getReportHistory: (...args: unknown[]) => getReportHistory(...args),
    getReportTrends: (...args: unknown[]) => getReportTrends(...args),
  };
});
vi.mock("../lib/geo-detection-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/geo-detection-client")>(
    "../lib/geo-detection-client",
  );
  return {
    ...actual,
    getDetectionHistory: (...args: unknown[]) => getDetectionHistory(...args),
  };
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
vi.mock("../lib/strategy-assistant-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/strategy-assistant-client")>(
    "../lib/strategy-assistant-client",
  );
  return {
    ...actual,
    getStrategies: (...args: unknown[]) => getStrategies(...args),
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
    models: [
      {
        model_id: "model-1",
        model_key: "deepseek",
        status: "succeeded",
        planned_calls: 3,
        completed_calls: 3,
        successful_calls: 3,
        failed_calls: 0,
        cancelled_calls: 0,
        geo: {
          score: "74.5",
          grade: "B",
          status: "formal" as const,
          formal_model_count: 1,
          planned_count: 3,
          successful_count: 3,
          success_rate: "100",
        },
        brand_reputation: {
          score: "71.0",
          grade: "B",
          status: "formal" as const,
          formal_model_count: 1,
          planned_count: 3,
          successful_count: 3,
          success_rate: "100",
        },
      },
    ],
    dimensions: {},
    competitors: [],
  },
  provenance: { scoring_rule_version: "v1", questions: [], models: [] },
  comparison: null,
  generated_at: "2026-08-22T08:00:00Z",
};

const reportTrends = [
  {
    report_id: "report-0",
    generated_at: "2026-08-15T08:00:00Z",
    subject_version_id: "subject-version-0",
    geo_score: "62.4",
    comparison: null,
  },
  {
    report_id: latestReport.id,
    generated_at: latestReport.generated_at,
    subject_version_id: latestReport.subject_version_id,
    geo_score: latestReport.summary.geo.score,
    comparison: null,
  },
];

const completedDetection = {
  id: "detection-1",
  subject_id: subject.id,
  status: "succeeded" as const,
  version: 1,
  planned_question_count: 3,
  planned_model_count: 1,
  planned_detection_points: 3,
  completed_calls: 3,
  successful_calls: 3,
  failed_calls: 0,
  cancelled_calls: 0,
  progress_percent: 100,
  queue_priority: 0,
  queue_position: null,
  cancel_requested: false,
  quota: { status: "settled" as const, held: 3, consumed: 3, released: 0 },
  queued_at: "2026-08-22T07:55:00Z",
  started_at: "2026-08-22T07:56:00Z",
  finished_at: "2026-08-22T08:00:00Z",
  cancelled_at: null,
  created_at: "2026-08-22T07:55:00Z",
  updated_at: "2026-08-22T08:00:00Z",
};

const latestStrategy = {
  id: "strategy-1",
  report_id: latestReport.id,
  subject_id: subject.id,
  subject_version_id: latestReport.subject_version_id,
  period: "30d" as const,
  period_days: 30,
  status: "succeeded" as const,
  billing: { mode: "free_initial" as const, first_free: true, held: false, remaining: 2 },
  body: {
    overview: "优先补强品牌证据与服务场景内容。",
    priorities: [
      {
        title: "先完善品牌可信证据",
        rationale: "当前推荐表现仍有提升空间。",
        actions: ["补充客户案例", "完善官网服务说明"],
        success_metric: "品牌推荐表现持续提升",
      },
    ],
    schedule: [],
    article_topics: [],
  },
  note: null,
  provenance: {
    provider_key: "configured-provider",
    model_key: "configured-model",
    provider_model_id: "configured-model-id",
    adapter_version: "1",
    prompt_version: "1",
    schema_version: "1",
    report_scoring_rule_version: "v1",
  },
  safe_error_code: "",
  created_at: "2026-08-22T08:10:00Z",
  generated_at: "2026-08-22T08:11:00Z",
  finished_at: "2026-08-22T08:11:00Z",
};

const renderInWorkspace = (component: React.ReactNode) =>
  render(<SubjectWorkspaceProvider>{component}</SubjectWorkspaceProvider>);

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((fulfill) => {
    resolve = fulfill;
  });
  return { promise, resolve };
}

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
  getReportTrends.mockResolvedValue({ items: reportTrends });
  getDetectionHistory.mockResolvedValue({ items: [completedDetection] });
  getQuestionBankDraft.mockResolvedValue({ current_question_bank_version_no: 3 });
  getStrategies.mockResolvedValue({
    items: [latestStrategy],
    first_free_available: false,
    remaining_regenerations: 2,
  });
  setCurrentSubject.mockResolvedValue({ current_subject_id: subject.id, version: 2 });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
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
    expect(screen.getByText("显问科技")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText("68.2").length).toBeGreaterThan(0));
    expect(screen.getByText("显问 GEO 情报中心")).toBeTruthy();
    expect(screen.getByText(/最近完成检测：/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "GEO 表现趋势" })).toBeTruthy();
    expect(screen.getByText("共 2 次检测")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "人工智能曝光指数" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "品牌提及率" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "推荐表现" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "各人工智能平台表现" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "深度求索" })).toBeTruthy();
    expect(screen.getByText("74.5 分")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "GEO 成长进度" })).toBeTruthy();
    expect(screen.getByText("完善主体档案")).toBeTruthy();
    expect(screen.getByText("完成人工智能可见度检测")).toBeTruthy();
    expect(screen.getByText("形成优化方案")).toBeTruthy();
    expect(screen.getByText("复测并验证变化")).toBeTruthy();
    expect(screen.getByText("问题库已就绪")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "智能洞察" })).toBeTruthy();
    expect(screen.getByText("先完善品牌可信证据")).toBeTruthy();
    expect(screen.getByText("当前推荐表现仍有提升空间。")).toBeTruthy();
    expect(screen.getAllByText(/GEO 综合评分/).length).toBeGreaterThan(0);
    expect(
      screen.queryByText(
        /GEO WORKSPACE|问题库 v3|GEO Score|Provider|Runtime|Binding|Batch|Candidate|Distilled|Asset/,
      ),
    ).toBeNull();
    expect(screen.queryByText("欢迎回来")).toBeNull();
    expect(screen.queryByText("当前没有生效套餐，但工作台功能仍然可见")).toBeNull();
    expect(screen.queryByText("显问 AI 助手")).toBeNull();
    expect(screen.queryByText("套餐目录")).toBeNull();
  });

  it("尚无检测报告时展示明确的下一步和产品化空状态", async () => {
    getReportHistory.mockResolvedValue({ items: [] });
    getReportTrends.mockResolvedValue({ items: [] });
    getDetectionHistory.mockResolvedValue({ items: [] });

    renderInWorkspace(<WorkspacePage />);

    expect(await screen.findByRole("heading", { name: "GEO 总览" })).toBeTruthy();
    expect(screen.getByText("尚未完成首次检测")).toBeTruthy();
    expect(screen.getByText("完成首次检测后，这里会显示综合评分。")).toBeTruthy();
    expect(screen.getByText("趋势还在积累")).toBeTruthy();
    expect(screen.getByText("人工智能曝光指数暂无数据")).toBeTruthy();
    expect(screen.getByText("完成检测后，这里会展示本次检测中的平台表现。")).toBeTruthy();
    expect(screen.getByText("完成首次检测后，这里会显示检测报告。")).toBeTruthy();
    expect(screen.getByText("开始可见度检测").closest("a")?.getAttribute("href")).toBe(
      "/geo/detections",
    );
    expect(getStrategies).not.toHaveBeenCalled();
    expect(screen.queryByText("部分内容暂时无法显示")).toBeNull();
  });

  it("单项内容读取失败时保留其余真实内容并使用中文提示", async () => {
    getReportTrends.mockRejectedValue(new Error("upstream unavailable"));

    renderInWorkspace(<WorkspacePage />);

    expect(await screen.findByText("部分内容暂时无法显示")).toBeTruthy();
    expect(screen.getByText("其他功能仍可正常使用，你可以稍后刷新页面。")).toBeTruthy();
    expect(screen.getByText("趋势暂时无法显示")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "各人工智能平台表现" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "深度求索" })).toBeTruthy();
    expect(screen.getByText("先完善品牌可信证据")).toBeTruthy();
    expect(screen.queryByText(/upstream|unavailable|接口|异常码/)).toBeNull();
  });

  it("切换主体后重新读取全部总览数据，并忽略上一主体的迟到结果", async () => {
    const delayedFirstStrategy = deferred<{
      items: (typeof latestStrategy)[];
      first_free_available: boolean;
      remaining_regenerations: number;
    }>();
    const secondReport = {
      ...latestReport,
      id: "report-2",
      detection_id: "detection-2",
      subject_id: otherSubject.id,
      subject_version_id: "subject-version-2",
      summary: {
        ...latestReport.summary,
        geo: { ...latestReport.summary.geo, score: "82.6" },
        exposure: {
          ...latestReport.summary.exposure,
          exposure_index: "79.4",
          mention_rate_score: "76.0",
          recommendation_rate_score: "69.0",
        },
      },
      generated_at: "2026-08-24T08:00:00Z",
    };
    const secondDetection = {
      ...completedDetection,
      id: "detection-2",
      subject_id: otherSubject.id,
      finished_at: "2026-08-24T08:00:00Z",
      updated_at: "2026-08-24T08:00:00Z",
    };
    const secondStrategy = {
      ...latestStrategy,
      id: "strategy-2",
      report_id: secondReport.id,
      subject_id: otherSubject.id,
      subject_version_id: secondReport.subject_version_id,
      body: {
        ...latestStrategy.body,
        overview: "华南主体应优先完善本地服务案例。",
        priorities: [
          {
            title: "补强华南本地服务证据",
            rationale: "当前主体需要增加本地案例。",
            actions: ["补充华南客户案例"],
            success_metric: "本地推荐表现提升",
          },
        ],
      },
    };

    getSubjects.mockResolvedValue({
      subjects: [subject, otherSubject],
      context: { current_subject_id: subject.id, version: 7 },
    });
    getReportHistory.mockImplementation((subjectId: string) =>
      Promise.resolve({ items: [subjectId === otherSubject.id ? secondReport : latestReport] }),
    );
    getReportTrends.mockImplementation((subjectId: string) =>
      Promise.resolve({
        items:
          subjectId === otherSubject.id
            ? [
                {
                  report_id: secondReport.id,
                  generated_at: secondReport.generated_at,
                  subject_version_id: secondReport.subject_version_id,
                  geo_score: secondReport.summary.geo.score,
                  comparison: null,
                },
              ]
            : reportTrends,
      }),
    );
    getDetectionHistory.mockImplementation((subjectId: string) =>
      Promise.resolve({
        items: [subjectId === otherSubject.id ? secondDetection : completedDetection],
      }),
    );
    getQuestionBankDraft.mockImplementation((subjectId: string) =>
      Promise.resolve({ current_question_bank_version_no: subjectId === otherSubject.id ? 5 : 3 }),
    );
    getStrategies.mockImplementation((reportId: string) =>
      reportId === latestReport.id
        ? delayedFirstStrategy.promise
        : Promise.resolve({
            items: [secondStrategy],
            first_free_available: false,
            remaining_regenerations: 2,
          }),
    );

    render(
      <SubjectWorkspaceProvider>
        <SubjectWorkspaceTopbar />
        <WorkspacePage />
      </SubjectWorkspaceProvider>,
    );

    expect(await screen.findByText("68.2")).toBeTruthy();
    expect(getReportHistory).toHaveBeenCalledWith(subject.id);
    expect(getReportTrends).toHaveBeenCalledWith(subject.id);
    expect(getDetectionHistory).toHaveBeenCalledWith(subject.id);
    expect(getQuestionBankDraft).toHaveBeenCalledWith(subject.id);
    expect(getStrategies).toHaveBeenCalledWith(latestReport.id);

    await userEvent.click(screen.getByLabelText("切换当前主体"));
    await userEvent.click(await screen.findByText("显问华南"));
    await waitFor(() => expect(setCurrentSubject).toHaveBeenCalledWith(otherSubject.id, 7));

    getSubjects.mockResolvedValue({
      subjects: [subject, { ...otherSubject, is_current: true }],
      context: { current_subject_id: otherSubject.id, version: 8 },
    });
    await act(async () => {
      window.dispatchEvent(new Event(SUBJECT_CONTEXT_UPDATED_EVENT));
    });

    await waitFor(() => expect(getReportHistory).toHaveBeenCalledWith(otherSubject.id));
    expect(screen.queryByText("68.2")).toBeNull();
    await waitFor(() => expect(screen.getByText("82.6")).toBeTruthy());
    expect(getReportTrends).toHaveBeenCalledWith(otherSubject.id);
    expect(getDetectionHistory).toHaveBeenCalledWith(otherSubject.id);
    expect(getQuestionBankDraft).toHaveBeenCalledWith(otherSubject.id);
    await waitFor(() => expect(getStrategies).toHaveBeenCalledWith(secondReport.id));
    expect(await screen.findByText("补强华南本地服务证据")).toBeTruthy();

    await act(async () => {
      delayedFirstStrategy.resolve({
        items: [latestStrategy],
        first_free_available: false,
        remaining_regenerations: 2,
      });
      await Promise.resolve();
    });

    expect(screen.getByText("补强华南本地服务证据")).toBeTruthy();
    expect(screen.queryByText("先完善品牌可信证据")).toBeNull();
    expect(screen.queryByText("68.2")).toBeNull();
  });

  it("总览请求一直无响应时十秒后结束加载并显示中文局部失败状态", async () => {
    vi.useFakeTimers();
    getReportTrends.mockImplementation(() => new Promise(() => undefined));

    renderInWorkspace(<WorkspacePage />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByLabelText("正在加载 GEO 总览")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9_999);
    });
    expect(screen.getByLabelText("正在加载 GEO 总览")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
      await Promise.resolve();
    });

    expect(screen.queryByLabelText("正在加载 GEO 总览")).toBeNull();
    expect(screen.getByText("部分内容暂时无法显示")).toBeTruthy();
    expect(screen.getByText("趋势暂时无法显示")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "各人工智能平台表现" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "深度求索" })).toBeTruthy();
    expect(screen.queryByText(/overview request ended|接口|异常码/)).toBeNull();
  });

  it("没有当前主体时只引导进入 GEO 主流程，不展示官网式功能介绍", async () => {
    getSubjects.mockResolvedValue({
      subjects: [],
      context: { current_subject_id: null, version: 0 },
    });
    renderInWorkspace(<WorkspacePage />);
    expect(
      await screen.findByText("创建并选择主体后，即可查看检测、趋势和优化进度。"),
    ).toBeTruthy();
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
    expect(screen.getByLabelText("切换当前主体")).toBeTruthy();
    expect(screen.getByRole("link", { name: "GEO 总览" }).getAttribute("href")).toBe("/workspace");
    for (const label of [
      "主体档案",
      "关键词中心",
      "问题库",
      "检测中心",
      "GEO 洞察",
      "数据中心",
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
    expect(screen.getByRole("link", { name: "问题生成" }).getAttribute("href")).toBe(
      "/subjects/subject-1/questions",
    );
    expect(screen.getByRole("link", { name: "问题管理" }).getAttribute("href")).toBe(
      "/subjects/subject-1/questions/manage",
    );
    expect(screen.getByRole("menuitem", { name: /关键词中心/ }).getAttribute("aria-expanded")).toBe(
      "false",
    );
    expect(screen.queryByRole("link", { name: "显问 AI 助手" })).toBeNull();

    await userEvent.click(screen.getByText("检测中心"));
    expect(screen.getByRole("link", { name: "主体检测" }).getAttribute("href")).toBe(
      "/geo/detections",
    );
    expect(screen.getByRole("link", { name: "官网检测" }).getAttribute("href")).toBe(
      "/geo/website-audits",
    );
    expect(screen.getByRole("link", { name: "发布检测" }).getAttribute("href")).toBe(
      "/subjects/subject-1/publication-checks",
    );

    await userEvent.click(screen.getByText("GEO 洞察"));
    expect(screen.getByRole("link", { name: "检测报告" }).getAttribute("href")).toBe(
      "/geo/reports",
    );
    expect(screen.getByRole("link", { name: "历史报告对比" }).getAttribute("href")).toBe(
      "/geo/reports/history",
    );

    await userEvent.click(screen.getByText("数据中心"));
    expect(screen.getByRole("link", { name: "曝光指数" }).getAttribute("href")).toBe(
      "/geo/exposure",
    );
    expect(screen.getByRole("link", { name: "竞品对比" }).getAttribute("href")).toBe(
      "/geo/data-center/competitors",
    );
    expect(screen.getByRole("link", { name: "信源指数" }).getAttribute("href")).toBe(
      "/geo/data-center/source-index",
    );
    expect(screen.getByRole("link", { name: "负面信息指数" }).getAttribute("href")).toBe(
      "/geo/data-center/negative-index",
    );

    await userEvent.click(screen.getByText("知识图谱建设"));
    expect(screen.getByRole("link", { name: "媒体信号建设" }).getAttribute("href")).toBe(
      "/geo/knowledge-graph/media-signals",
    );

    await userEvent.click(screen.getByText("优化中心"));
    expect(screen.getByRole("link", { name: "优化方案" }).getAttribute("href")).toBe(
      "/geo/strategy",
    );
    expect(screen.getByText("执行计划")).toBeTruthy();
    expect(screen.getByRole("link", { name: "文章生成" }).getAttribute("href")).toBe(
      "/subjects/subject-1/articles/new",
    );
    expect(screen.getByRole("link", { name: "图片生成" }).getAttribute("href")).toBe(
      "/subjects/subject-1/images",
    );
    expect(screen.getByRole("link", { name: "视频脚本生成" }).getAttribute("href")).toBe(
      "/subjects/subject-1/video-scripts/new",
    );
    expect(screen.getByRole("link", { name: "视频生成" }).getAttribute("href")).toBe(
      "/subjects/subject-1/videos/new",
    );

    await userEvent.click(screen.getByText("内容资产中心"));
    expect(screen.getByRole("link", { name: "内容库" }).getAttribute("href")).toBe(
      "/subjects/subject-1/articles",
    );
    expect(screen.getByRole("link", { name: "图片库" }).getAttribute("href")).toBe(
      "/subjects/subject-1/image-library",
    );
    expect(screen.getByRole("link", { name: "视频库" }).getAttribute("href")).toBe(
      "/subjects/subject-1/video-library",
    );
    expect(screen.getByRole("link", { name: "自定义库" }).getAttribute("href")).toBe(
      "/subjects/subject-1/custom-library",
    );
    pathname = "/subjects/subject-1/images";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: /优化中心/ }).getAttribute("aria-expanded")).toBe(
        "true",
      ),
    );
    expect(screen.getByRole("menuitem", { name: "图片生成" }).className).toContain(
      "ant-menu-item-selected",
    );

    pathname = "/subjects/subject-1/videos/new";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: "视频生成" }).className).toContain(
        "ant-menu-item-selected",
      ),
    );

    pathname = "/subjects/subject-1/articles";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: "内容库" }).className).toContain(
        "ant-menu-item-selected",
      ),
    );

    pathname = "/subjects/subject-1/image-library";
    rerender(shell());
    await waitFor(() =>
      expect(
        screen.getByRole("menuitem", { name: /内容资产中心/ }).getAttribute("aria-expanded"),
      ).toBe("true"),
    );
    expect(screen.getByRole("menuitem", { name: "图片库" }).className).toContain(
      "ant-menu-item-selected",
    );

    pathname = "/subjects/subject-1/publication-checks";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: /检测中心/ }).getAttribute("aria-expanded")).toBe(
        "true",
      ),
    );
    expect(screen.getByRole("menuitem", { name: "发布检测" }).className).toContain(
      "ant-menu-item-selected",
    );

    pathname = "/geo/knowledge-graph/media-signals";
    rerender(shell());
    await waitFor(() =>
      expect(
        screen.getByRole("menuitem", { name: /知识图谱建设/ }).getAttribute("aria-expanded"),
      ).toBe("true"),
    );
    expect(screen.getByRole("menuitem", { name: "媒体信号建设" }).className).toContain(
      "ant-menu-item-selected",
    );

    pathname = "/geo/reports/report-1";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: /GEO 洞察/ }).getAttribute("aria-expanded")).toBe(
        "true",
      ),
    );
    expect(screen.getByRole("menuitem", { name: "检测报告" }).className).toContain(
      "ant-menu-item-selected",
    );

    pathname = "/geo/reports/history";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: "历史报告对比" }).className).toContain(
        "ant-menu-item-selected",
      ),
    );

    pathname = "/geo/exposure";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: /数据中心/ }).getAttribute("aria-expanded")).toBe(
        "true",
      ),
    );
    expect(screen.getByRole("menuitem", { name: "曝光指数" }).className).toContain(
      "ant-menu-item-selected",
    );

    pathname = "/geo/data-center/competitors";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: "竞品对比" }).className).toContain(
        "ant-menu-item-selected",
      ),
    );

    pathname = "/geo/data-center/source-index";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: "信源指数" }).className).toContain(
        "ant-menu-item-selected",
      ),
    );

    pathname = "/geo/data-center/negative-index";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: "负面信息指数" }).className).toContain(
        "ant-menu-item-selected",
      ),
    );

    pathname = "/geo/strategy";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: /优化中心/ }).getAttribute("aria-expanded")).toBe(
        "true",
      ),
    );
    expect(screen.getByRole("menuitem", { name: "优化方案" }).className).toContain(
      "ant-menu-item-selected",
    );

    pathname = "/geo/strategy/report-1";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: "优化方案" }).className).toContain(
        "ant-menu-item-selected",
      ),
    );

    pathname = "/geo/reports/report-1/strategy";
    rerender(shell());
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: "优化方案" }).className).toContain(
        "ant-menu-item-selected",
      ),
    );

    pathname = "/admin";
    rerender(shell());
    await waitFor(() =>
      expect(screen.queryByRole("navigation", { name: "GEO 工作台导航" })).toBeNull(),
    );
  }, 15_000);

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
    const selector = await screen.findByLabelText("切换当前主体");
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
    expect(subjectSwitchTargetPath("/subjects/subject-1/images", "subject-2")).toBe(
      "/subjects/subject-2/images",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/videos/new", "subject-2")).toBe(
      "/subjects/subject-2/videos/new",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/articles/new", "subject-2")).toBe(
      "/subjects/subject-2/articles/new",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/articles", "subject-2")).toBe(
      "/subjects/subject-2/articles",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/image-library", "subject-2")).toBe(
      "/subjects/subject-2/image-library",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/video-library", "subject-2")).toBe(
      "/subjects/subject-2/video-library",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/custom-library", "subject-2")).toBe(
      "/subjects/subject-2/custom-library",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/publication-checks", "subject-2")).toBe(
      "/subjects/subject-2/publication-checks",
    );
    expect(subjectSwitchTargetPath("/subjects/subject-1/versions/version-1", "subject-2")).toBe(
      "/subjects/subject-2",
    );
    expect(subjectSwitchTargetPath("/geo/reports/report-1", "subject-2")).toBe("/geo/reports");
    expect(subjectSwitchTargetPath("/geo/reports/history", "subject-2")).toBe(
      "/geo/reports/history",
    );
    expect(subjectSwitchTargetPath("/geo/exposure", "subject-2")).toBe("/geo/exposure");
    expect(subjectSwitchTargetPath("/geo/strategy", "subject-2")).toBe("/geo/strategy");
    expect(subjectSwitchTargetPath("/geo/reports/report-1/strategy", "subject-2")).toBe(
      "/geo/strategy",
    );
    expect(subjectSwitchTargetPath("/geo/strategy/report-1", "subject-2")).toBe("/geo/strategy");
    expect(subjectSwitchTargetPath("/geo/execution", "subject-2")).toBe("/geo/execution");
    expect(subjectSwitchTargetPath("/geo/execution/plan-1", "subject-2")).toBe("/geo/execution");
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
    const selector = await screen.findByLabelText("切换当前主体");
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
