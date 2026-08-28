// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import QuestionBankPanel from "@/app/subjects/[id]/keywords/question-bank-panel";
import QuestionManagementPanel from "@/app/subjects/[id]/questions/question-management-panel";
import { AuthApiError } from "@/lib/auth-client";
import { questionGenerationErrorMessage } from "@/lib/question-bank-client";

const navigation = vi.hoisted(() => ({ push: vi.fn() }));
const api = vi.hoisted(() => ({
  getQuestionBankDraft: vi.fn(),
  createQuestionGeneration: vi.fn(),
  getQuestionGenerationJob: vi.fn(),
  confirmQuestionBank: vi.fn(),
  getCurrentQuestionBank: vi.fn(),
  removeCurrentQuestionBankItems: vi.fn(),
}));
const keywordApi = vi.hoisted(() => ({
  getKeywordAssets: vi.fn(),
  updateKeywordAsset: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
vi.mock("@/lib/question-bank-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/question-bank-client")>(
    "@/lib/question-bank-client",
  );
  return { ...actual, ...api };
});
vi.mock("@/lib/keywords-client", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/keywords-client")>("@/lib/keywords-client");
  return { ...actual, ...keywordApi };
});

const questionItem = {
  id: "question-1",
  text: "用户选择品牌服务时最关心哪些因素？",
  primary_category: { id: "category-1", key: "purchase-decision", name: "购买决策" },
  tag_ids: ["tag-1"],
  keyword_ids: ["keyword-1"],
  priority: "high" as const,
  question_type: "natural" as const,
  participates_in_scoring: true,
  ai_reason: "高价值自然探索问题",
  sort_order: 0,
};

const draft = {
  version: 1,
  can_write: true,
  read_only_reason: null,
  question_limit: 20,
  catalog: {
    categories: [
      {
        id: "category-1",
        key: "purchase-decision",
        name: "购买决策",
        version: 1,
        guidance: "关注用户决策",
      },
    ],
    tags: [{ id: "tag-1", key: "commercial", name: "商业意图", version: 1 }],
  },
  current_distillation_set: { id: "distillation-1", version_no: 1, item_count: 5 },
  draft_input: {
    subject_version_id: "subject-version-1",
    distillation_set_id: "distillation-1",
    distillation_version_no: 1,
  },
  source_result_id: "result-1",
  current_question_bank_version_no: null,
  items: [questionItem],
};

const queued = {
  id: "question-job-1",
  subject_id: "subject-1",
  subject_version_id: "subject-version-1",
  distillation_set_id: "distillation-1",
  status: "queued" as const,
  version: 1,
  stable_error_code: "",
  question_limit: 20,
  billing: { billing_mode: "free_initial" as const, held: false, remaining: null },
  provenance: {
    provider_key: "mock",
    model_key: "mock-question-generation-v1",
    adapter_version: "1",
    prompt_version: "question-generation-v1",
  },
  result: null,
  attempts: 0,
  created_at: "2026-08-16T00:00:00Z",
  updated_at: "2026-08-16T00:00:00Z",
  finished_at: null,
};

const asset = {
  id: "keyword-asset-1",
  text: "GEO 品牌咨询",
  source_text: "GEO 品牌咨询",
  related_keywords: [],
  audiences: [],
  scenarios: [],
  category: "entity",
  intents: ["informational" as const],
  regions: [],
  source: "distillation",
  enabled: true,
  usable_for_questions: true,
  deleted: false,
  updated_at: "2026-08-16T00:00:00Z",
};

beforeEach(() => {
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
  Object.defineProperty(globalThis, "ResizeObserver", {
    writable: true,
    value: class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  });
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value: { randomUUID: vi.fn(() => "11111111-1111-4111-8111-111111111111") },
  });
  vi.clearAllMocks();
  api.getQuestionBankDraft.mockResolvedValue(draft);
  api.getCurrentQuestionBank.mockResolvedValue({
    id: "question-bank-version-1",
    version_no: 1,
    subject_version_id: "subject-version-1",
    distillation_set_id: "distillation-1",
    source_result_id: "result-1",
    item_count: 1,
    confirmed_at: "2026-08-16T00:00:02Z",
    items: [questionItem],
  });
  api.removeCurrentQuestionBankItems.mockResolvedValue({
    current: null,
    removed_count: 20,
  });
  keywordApi.getKeywordAssets.mockResolvedValue({ items: [asset] });
  keywordApi.updateKeywordAsset.mockImplementation(
    async (_subjectId: string, assetId: string, patch: { usableForQuestions?: boolean }) => ({
      ...asset,
      id: assetId,
      usable_for_questions: patch.usableForQuestions ?? asset.usable_for_questions,
    }),
  );
});

afterEach(cleanup);

describe("问题生成与问题管理", () => {
  it("将问题生成错误码统一转换为中文用户提示", () => {
    const cases = [
      [
        "QUESTION_GENERATION_PROVIDER_UNAVAILABLE",
        "问题生成服务暂时不可用，请稍后重新尝试或联系管理员。",
      ],
      ["QUESTION_GENERATION_INVALID_RESPONSE", "AI 返回内容暂时无法识别，请重新生成。"],
      ["QUESTION_GENERATION_PROVIDER_ERROR", "问题生成服务暂时不可用，请稍后重新尝试。"],
      ["QUESTION_GENERATION_INTERNAL_ERROR", "问题生成服务暂时不可用，请稍后重新尝试。"],
      ["QUESTION_GENERATION_IN_PROGRESS", "问题正在生成，请稍候。"],
    ] as const;
    for (const [code, message] of cases) expect(questionGenerationErrorMessage(code)).toBe(message);
  });

  it("同步本地关键词资产选择后再创建问题生成任务", async () => {
    const secondAsset = {
      ...asset,
      id: "keyword-asset-2",
      text: "AI 搜索优化",
      usable_for_questions: false,
    };
    keywordApi.getKeywordAssets.mockResolvedValue({ items: [asset, secondAsset] });
    api.createQuestionGeneration.mockResolvedValue(queued);
    render(<QuestionBankPanel subjectId="subject-1" upstreamDirty={false} />);

    expect(await screen.findByText("选择关键词资产")).toBeTruthy();
    await userEvent.click(screen.getByRole("checkbox", { name: "选择关键词：AI 搜索优化" }));
    await userEvent.click(screen.getByRole("button", { name: "AI 生成问题" }));

    await waitFor(() => expect(api.createQuestionGeneration).toHaveBeenCalledTimes(1));
    expect(keywordApi.updateKeywordAsset).toHaveBeenCalledWith("subject-1", "keyword-asset-2", {
      usableForQuestions: true,
    });
    expect(keywordApi.updateKeywordAsset.mock.invocationCallOrder[0]).toBeLessThan(
      api.createQuestionGeneration.mock.invocationCallOrder[0],
    );
  });

  it("阻止上游未保存状态，并在任务成功后显示中文结果", async () => {
    const { rerender } = render(<QuestionBankPanel subjectId="subject-1" upstreamDirty />);
    expect(await screen.findByText("问题生成")).toBeTruthy();
    expect(screen.getByRole("button", { name: "AI 生成问题" })).toHaveProperty("disabled", true);
    api.createQuestionGeneration.mockResolvedValue(queued);
    api.getQuestionGenerationJob.mockResolvedValue({
      ...queued,
      status: "succeeded",
      version: 3,
      attempts: 1,
      result: { item_count: 1, applied_workspace_version: 1 },
      finished_at: "2026-08-16T00:00:01Z",
    });
    rerender(<QuestionBankPanel subjectId="subject-1" upstreamDirty={false} />);
    await userEvent.click(screen.getByRole("button", { name: "AI 生成问题" }));
    expect(
      await screen.findByText("问题已生成，请确认后保存到问题管理", {}, { timeout: 2500 }),
    ).toBeTruthy();
    expect(screen.getByText("生成完成")).toBeTruthy();
  });

  it("保存并确认正式问题库后进入问题管理", async () => {
    api.getCurrentQuestionBank.mockResolvedValue({
      id: "question-bank-version-1",
      version_no: 1,
      subject_version_id: "subject-version-1",
      distillation_set_id: "distillation-1",
      source_result_id: "previous-result",
      item_count: 1,
      confirmed_at: "2026-08-16T00:00:02Z",
      items: [questionItem],
    });
    api.confirmQuestionBank.mockResolvedValue({ version: { version_no: 1 } });
    render(<QuestionBankPanel subjectId="subject-1" upstreamDirty={false} />);

    expect(await screen.findByRole("button", { name: "保存到问题管理" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "保存到问题管理" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认保存" }));
    await waitFor(() => expect(api.confirmQuestionBank).toHaveBeenCalledWith("subject-1", 1));
    expect(navigation.push).toHaveBeenCalledWith("/subjects/subject-1/questions/manage");
  });

  it("已经确认的同一批问题不重复确认", async () => {
    render(<QuestionBankPanel subjectId="subject-1" upstreamDirty={false} />);

    expect(await screen.findByRole("link", { name: "已保存，进入问题管理" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "保存到问题管理" })).toBeNull();
  });

  it("生成结果与关键词资产列表都按每页20条分页", async () => {
    api.getQuestionBankDraft.mockResolvedValue({
      ...draft,
      items: Array.from({ length: 21 }, (_, index) => ({
        ...questionItem,
        id: `question-${index + 1}`,
        text: `分页问题 ${index + 1}`,
        sort_order: index,
      })),
    });
    keywordApi.getKeywordAssets.mockResolvedValue({
      items: Array.from({ length: 21 }, (_, index) => ({
        ...asset,
        id: `asset-${index + 1}`,
        text: `分页关键词 ${index + 1}`,
      })),
    });
    render(<QuestionBankPanel subjectId="subject-1" upstreamDirty={false} />);

    expect(await screen.findByText("分页问题 1")).toBeTruthy();
    expect(screen.queryByText("分页问题 21")).toBeNull();
    expect(screen.getByText("分页关键词 20")).toBeTruthy();
    expect(screen.queryByText("分页关键词 21")).toBeNull();

    await userEvent.click(within(screen.getByLabelText("问题生成结果分页")).getByTitle("2"));
    expect(await screen.findByText("分页问题 21")).toBeTruthy();
    await userEvent.click(within(screen.getByLabelText("问题生成关键词分页")).getByTitle("2"));
    expect(await screen.findByText("分页关键词 21")).toBeTruthy();
  });

  it("问题管理读取正式版本、显示参与检测状态并提供检测入口", async () => {
    render(<QuestionManagementPanel subjectId="subject-1" />);

    expect(await screen.findByText("正式问题库")).toBeTruthy();
    expect(screen.getByText("当前正式问题库")).toBeTruthy();
    expect(screen.queryByText(/正式版本 v/)).toBeNull();
    expect(screen.getByText("用户选择品牌服务时最关心哪些因素？")).toBeTruthy();
    expect(screen.getByText("参与检测")).toBeTruthy();
    expect(screen.getByRole("link", { name: "去主体检测" }).getAttribute("href")).toBe(
      "/geo/detections",
    );
  });

  it("问题管理正式问题每页显示20条", async () => {
    api.getCurrentQuestionBank.mockResolvedValue({
      id: "version-1",
      version_no: 1,
      subject_version_id: "subject-version-1",
      distillation_set_id: "distillation-1",
      source_result_id: "result-1",
      item_count: 21,
      confirmed_at: "2026-08-16T00:00:02Z",
      items: Array.from({ length: 21 }, (_, index) => ({
        ...questionItem,
        id: `formal-question-${index + 1}`,
        text: `正式问题 ${index + 1}`,
        sort_order: index,
      })),
    });
    render(<QuestionManagementPanel subjectId="subject-1" />);

    expect(await screen.findByText("正式问题 1")).toBeTruthy();
    expect(screen.queryByText("正式问题 21")).toBeNull();
    expect(screen.getByText("第 1-20 条，共 21 条")).toBeTruthy();
    await userEvent.click(within(screen.getByLabelText("问题管理分页")).getByTitle("2"));
    expect(await screen.findByText("正式问题 21")).toBeTruthy();
  });

  it("问题管理支持逐项勾选、当页全选和安全批量删除", async () => {
    api.getCurrentQuestionBank.mockResolvedValue({
      id: "version-1",
      version_no: 1,
      subject_version_id: "subject-version-1",
      distillation_set_id: "distillation-1",
      source_result_id: "result-1",
      item_count: 21,
      confirmed_at: "2026-08-16T00:00:02Z",
      items: Array.from({ length: 21 }, (_, index) => ({
        ...questionItem,
        id: `formal-question-${index + 1}`,
        text: `正式问题 ${index + 1}`,
        sort_order: index,
      })),
    });
    render(<QuestionManagementPanel subjectId="subject-1" />);

    expect(await screen.findByText("正式问题 1")).toBeTruthy();
    await userEvent.click(screen.getByRole("checkbox", { name: "全选本页问题" }));
    expect(screen.getByText("已选择 20 条")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "选择问题：正式问题 1" })).toHaveProperty(
      "checked",
      true,
    );
    await userEvent.click(screen.getByRole("button", { name: "批量删除" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认删除" }));

    await waitFor(() =>
      expect(api.removeCurrentQuestionBankItems).toHaveBeenCalledWith("subject-1", {
        expectedVersionId: "version-1",
        questionIds: Array.from({ length: 20 }, (_, index) => `formal-question-${index + 1}`),
      }),
    );
    expect(await screen.findByText("已删除 20 条问题，历史检测记录不受影响")).toBeTruthy();
  });

  it("任务失败时不暴露英文错误码", async () => {
    api.createQuestionGeneration.mockResolvedValue(queued);
    api.getQuestionGenerationJob.mockResolvedValue({
      ...queued,
      status: "failed",
      stable_error_code: "QUESTION_GENERATION_PROVIDER_UNAVAILABLE",
      finished_at: "2026-08-16T00:00:01Z",
    });
    render(<QuestionBankPanel subjectId="subject-1" upstreamDirty={false} />);
    expect(await screen.findByText("问题生成")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "AI 生成问题" }));
    expect(
      await screen.findByText(
        "问题生成服务暂时不可用，请稍后重新尝试或联系管理员。",
        {},
        { timeout: 2500 },
      ),
    ).toBeTruthy();
    expect(screen.queryByText("QUESTION_GENERATION_PROVIDER_UNAVAILABLE")).toBeNull();
  });

  it("付费重生成仍要求明确确认", async () => {
    api.createQuestionGeneration
      .mockRejectedValueOnce(
        new AuthApiError(new Response(null, { status: 409 }), {
          success: false,
          error: {
            code: "QUESTION_GENERATION_REGENERATION_CONFIRMATION_REQUIRED",
            message: "需要确认重生成",
            details: {},
          },
          request_id: "request-1",
        }),
      )
      .mockResolvedValueOnce({
        ...queued,
        billing: { billing_mode: "regeneration" as const, held: true, remaining: 1 },
      });
    render(<QuestionBankPanel subjectId="subject-1" upstreamDirty={false} />);
    expect(await screen.findByText("问题生成")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "AI 生成问题" }));
    expect(
      await screen.findByText("该主体已有成功问题生成，请确认消耗一次重生成额度"),
    ).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "确认消耗额度并重生成" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认重生成" }));
    await waitFor(() => expect(api.createQuestionGeneration).toHaveBeenCalledTimes(2));
  });
});
