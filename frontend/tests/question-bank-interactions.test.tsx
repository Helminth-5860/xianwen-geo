// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import QuestionBankPanel from "@/app/subjects/[id]/keywords/question-bank-panel";
import { AuthApiError } from "@/lib/auth-client";

const api = vi.hoisted(() => ({
  getQuestionBankDraft: vi.fn(),
  getQuestionBankVersions: vi.fn(),
  createQuestionGeneration: vi.fn(),
  getQuestionGenerationJob: vi.fn(),
  saveQuestionBankDraft: vi.fn(),
  confirmQuestionBank: vi.fn(),
}));

vi.mock("@/lib/question-bank-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/question-bank-client")>(
    "@/lib/question-bank-client",
  );
  return { ...actual, ...api };
});

const item = {
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
      { id: "category-2", key: "comparison", name: "横向比较", version: 2, guidance: "" },
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
  items: [item],
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
  api.getQuestionBankVersions.mockResolvedValue({ versions: [] });
});

afterEach(cleanup);

describe("QuestionBankPanel", () => {
  it("blocks on upstream edits, then starts and polls a bounded generation job", async () => {
    const { rerender } = render(<QuestionBankPanel subjectId="subject-1" upstreamDirty />);
    expect(await screen.findByText("问题库生成与编辑")).toBeTruthy();
    expect(screen.getByRole("button", { name: "AI 生成问题库" })).toHaveProperty("disabled", true);
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
    await userEvent.click(screen.getByRole("button", { name: "AI 生成问题库" }));
    await waitFor(() => expect(api.createQuestionGeneration).toHaveBeenCalledTimes(1));
    expect(api.createQuestionGeneration.mock.calls[0][1]).toEqual({
      distillationSetId: "distillation-1",
      expectedWorkspaceVersion: 1,
      regenerate: false,
    });
    await waitFor(
      () => expect(api.getQuestionGenerationJob).toHaveBeenCalledWith("question-job-1"),
      { timeout: 2500 },
    );
    expect(await screen.findByText("问题建议已写入草稿，请审核并确认正式版本")).toBeTruthy();
  });

  it("edits and saves a mutable draft before confirming an immutable version", async () => {
    api.saveQuestionBankDraft.mockImplementation(async (_subject, _version, items) => ({
      ...draft,
      version: 2,
      items,
    }));
    api.confirmQuestionBank.mockResolvedValue({
      version: {
        id: "question-bank-version-1",
        version_no: 1,
        subject_version_id: "subject-version-1",
        distillation_set_id: "distillation-1",
        source_result_id: "result-1",
        item_count: 1,
        confirmed_at: "2026-08-16T00:00:02Z",
      },
    });
    render(<QuestionBankPanel subjectId="subject-1" upstreamDirty={false} />);
    const text = await screen.findByLabelText("问题文本-1");
    await userEvent.clear(text);
    await userEvent.type(text, "购买前应比较哪些核心能力？");
    await userEvent.click(screen.getByLabelText("问题优先级-1"));
    await userEvent.click(
      await screen.findByText("低", { selector: ".ant-select-item-option-content" }),
    );
    expect(screen.getByRole("button", { name: "确认问题库" })).toHaveProperty("disabled", true);
    await userEvent.click(screen.getByRole("button", { name: "保存问题草稿" }));
    await waitFor(() => expect(api.saveQuestionBankDraft).toHaveBeenCalledTimes(1));
    expect(api.saveQuestionBankDraft.mock.calls[0][2][0].text).toBe("购买前应比较哪些核心能力？");
    expect(api.saveQuestionBankDraft.mock.calls[0][2][0].priority).toBe("low");
    await userEvent.click(screen.getByRole("button", { name: "确认问题库" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认版本" }));
    await waitFor(() => expect(api.confirmQuestionBank).toHaveBeenCalledWith("subject-1", 2));
  });

  it("requires explicit confirmation before billable regeneration", async () => {
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
    expect(await screen.findByText("问题库生成与编辑")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "AI 生成问题库" }));
    expect(
      await screen.findByText("该主体已有成功问题生成，请确认消耗一次重生成额度"),
    ).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "确认消耗额度并重生成" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认重生成" }));
    await waitFor(() => expect(api.createQuestionGeneration).toHaveBeenCalledTimes(2));
    expect(api.createQuestionGeneration.mock.calls[1][1].regenerate).toBe(true);
  });
});
