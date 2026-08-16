// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import KeywordEditorPage from "@/app/subjects/[id]/keywords/page";
import { AuthApiError } from "@/lib/auth-client";

const api = vi.hoisted(() => ({
  getKeywordDraft: vi.fn(),
  getKeywordVersions: vi.fn(),
  getKeywordVersion: vi.fn(),
  saveKeywordDraft: vi.fn(),
  commitKeywords: vi.fn(),
  createKeywordGeneration: vi.fn(),
  getKeywordGenerationJob: vi.fn(),
}));

vi.mock("@/lib/keywords-client", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/keywords-client")>("@/lib/keywords-client");
  return { ...actual, ...api };
});
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "subject-1" }) }));
vi.mock("@/app/subjects/[id]/keywords/distillation-panel", () => ({
  default: () => null,
}));

const draft = {
  version: 1,
  subject_version: { id: "sv-1", version_no: 2, official_name: "示例企业" },
  draft_subject_version: { id: "sv-1", version_no: 2, official_name: "示例企业" },
  current_keyword_version_no: 1,
  can_write: true,
  read_only_reason: null,
  items: [
    {
      id: "keyword-1",
      text: "GEO",
      structure_type: "short" as const,
      is_regional: false,
      region_level: null,
      region_text: null,
      base_keyword_text: null,
      business_category: null,
      search_intent: null,
      relevance_score: null,
      priority: null,
      ai_reason: null,
      sort_order: 0,
    },
  ],
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
  vi.clearAllMocks();
  api.getKeywordDraft.mockResolvedValue(draft);
  api.getKeywordVersions.mockResolvedValue({ versions: [] });
  api.createKeywordGeneration.mockReset();
  api.getKeywordGenerationJob.mockReset();
});

afterEach(cleanup);

describe("KeywordEditorPage", () => {
  it("adds and saves a manual keyword draft alongside generation UI", async () => {
    api.saveKeywordDraft.mockResolvedValue({ ...draft, version: 2 });
    render(<KeywordEditorPage />);

    expect(await screen.findByText("关键词编辑器")).toBeTruthy();
    expect(screen.getByRole("button", { name: "AI 生成关键词" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "添加关键词" }));
    await userEvent.type(screen.getByLabelText("关键词-2"), "上海 GEO 服务");
    await userEvent.click(screen.getByRole("checkbox", { name: "地域词-2" }));
    await userEvent.type(screen.getByLabelText("地域文本-2"), "上海");
    await userEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() => expect(api.saveKeywordDraft).toHaveBeenCalledTimes(1));
    expect(api.saveKeywordDraft.mock.calls[0][1].expectedVersion).toBe(1);
    expect(api.saveKeywordDraft.mock.calls[0][1].expectedSubjectVersionId).toBe("sv-1");
  });

  it("commits the saved draft and reloads formal history", async () => {
    api.commitKeywords.mockResolvedValue({
      version: {
        id: "kv-2",
        version_no: 2,
        subject_version: draft.subject_version,
        item_count: 1,
        created_at: "2026-08-14T10:00:00Z",
        items: draft.items,
      },
    });
    render(<KeywordEditorPage />);

    expect(await screen.findByText("关键词编辑器")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "保存并生成新版本" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认提交" }));

    await waitFor(() => expect(api.commitKeywords).toHaveBeenCalledTimes(1));
    expect(api.commitKeywords).toHaveBeenCalledWith("subject-1", 1, "sv-1");
  });

  it("keeps local edits when a save conflict is returned", async () => {
    api.saveKeywordDraft.mockRejectedValue(new Error("关键词草稿已发生变化，请刷新后重试"));
    render(<KeywordEditorPage />);

    expect(await screen.findByText("关键词编辑器")).toBeTruthy();
    const input = screen.getByLabelText("关键词-1");
    await userEvent.clear(input);
    await userEvent.type(input, "本地未保存关键词");
    await userEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    expect(await screen.findByText("关键词草稿已发生变化，请刷新后重试")).toBeTruthy();
    expect((screen.getByLabelText("关键词-1") as HTMLInputElement).value).toBe("本地未保存关键词");
  });

  it("requires an explicit draft rebase when the subject version changed", async () => {
    api.getKeywordDraft.mockResolvedValue({
      ...draft,
      draft_subject_version: {
        id: "sv-old",
        version_no: 1,
        official_name: "示例企业",
      },
    });
    render(<KeywordEditorPage />);

    expect(
      await screen.findByText("主体资料正式版本已更新，请先保存关键词草稿以重新绑定后再提交。"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "保存并生成新版本" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("blocks generation while local draft edits are unsaved", async () => {
    render(<KeywordEditorPage />);
    expect(await screen.findByText("关键词编辑器")).toBeTruthy();

    await userEvent.type(screen.getByLabelText("关键词-1"), " 本地修改");
    expect(screen.getByRole("button", { name: "AI 生成关键词" })).toHaveProperty("disabled", true);
    expect(api.createKeywordGeneration).not.toHaveBeenCalled();
  });

  it("starts general-mode generation, polls success, and loads AI metadata", async () => {
    const queuedJob = {
      id: "job-1",
      subject_id: "subject-1",
      subject_version_id: "sv-1",
      status: "queued" as const,
      version: 1,
      stable_error_code: "",
      billing: { billing_mode: "free_initial" as const, held: false, remaining: 2 },
      configuration: {
        target_count: 10,
        include_short: false,
        include_long_tail: false,
        include_regional: false,
        regions: [],
      },
      provenance: {
        provider_key: "mock",
        model_key: "mock-keyword-generation-v1",
        adapter_version: "1",
        prompt_version: "keyword-generation-v1",
      },
      result: null,
      attempts: 0,
      created_at: "2026-08-15T00:00:00Z",
      updated_at: "2026-08-15T00:00:00Z",
      finished_at: null,
    };
    api.createKeywordGeneration.mockResolvedValue(queuedJob);
    api.getKeywordGenerationJob.mockResolvedValue({
      ...queuedJob,
      status: "succeeded",
      version: 3,
      result: { item_count: 1, applied_keyword_set_version: 2 },
      finished_at: "2026-08-15T00:00:02Z",
    });
    api.getKeywordDraft.mockResolvedValueOnce(draft).mockResolvedValue({
      ...draft,
      version: 2,
      items: [
        {
          ...draft.items[0],
          business_category: "general",
          search_intent: "commercial" as const,
          relevance_score: 98,
          priority: "high" as const,
          ai_reason: "与主体业务高度相关",
        },
      ],
    });

    render(<KeywordEditorPage />);
    expect(await screen.findByText("关键词编辑器")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "AI 生成关键词" }));

    await waitFor(() => expect(api.createKeywordGeneration).toHaveBeenCalledTimes(1));
    expect(api.createKeywordGeneration.mock.calls[0][1]).toMatchObject({
      expectedSubjectVersionId: "sv-1",
      expectedKeywordSetVersion: 1,
      includeShort: false,
      includeLongTail: false,
      includeRegional: false,
      regions: [],
      regenerate: false,
    });
    await waitFor(() => expect(api.getKeywordGenerationJob).toHaveBeenCalledWith("job-1"), {
      timeout: 2500,
    });
    expect(await screen.findByText("相关度 98")).toBeTruthy();
    expect(screen.getByText("与主体业务高度相关")).toBeTruthy();
  });

  it("shows a stable terminal generation failure without replacing the draft", async () => {
    const queued = {
      id: "job-failed",
      subject_id: "subject-1",
      subject_version_id: "sv-1",
      status: "queued" as const,
      version: 1,
      stable_error_code: "",
      billing: { billing_mode: "free_initial" as const, held: false, remaining: 2 },
      configuration: {
        target_count: 10,
        include_short: false,
        include_long_tail: false,
        include_regional: false,
        regions: [],
      },
      provenance: {
        provider_key: "mock",
        model_key: "mock-keyword-generation-v1",
        adapter_version: "1",
        prompt_version: "keyword-generation-v1",
      },
      result: null,
      attempts: 0,
      created_at: "2026-08-15T00:00:00Z",
      updated_at: "2026-08-15T00:00:00Z",
      finished_at: null,
    };
    api.createKeywordGeneration.mockResolvedValue(queued);
    api.getKeywordGenerationJob.mockResolvedValue({
      ...queued,
      status: "failed",
      stable_error_code: "KEYWORD_GENERATION_PROVIDER_REJECTED",
      finished_at: "2026-08-15T00:00:02Z",
    });

    render(<KeywordEditorPage />);
    expect(await screen.findByText("关键词编辑器")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "AI 生成关键词" }));

    expect(
      await screen.findByText("KEYWORD_GENERATION_PROVIDER_REJECTED", {}, { timeout: 2500 }),
    ).toBeTruthy();
    expect((screen.getByLabelText("关键词-1") as HTMLInputElement).value).toBe("GEO");
  });

  it("refreshes the draft immediately when idempotency replays a succeeded job", async () => {
    const succeeded = {
      id: "job-replay",
      subject_id: "subject-1",
      subject_version_id: "sv-1",
      status: "succeeded" as const,
      version: 3,
      stable_error_code: "",
      billing: { billing_mode: "free_initial" as const, held: false, remaining: 2 },
      configuration: {
        target_count: 10,
        include_short: false,
        include_long_tail: false,
        include_regional: false,
        regions: [],
      },
      provenance: {
        provider_key: "mock",
        model_key: "mock-keyword-generation-v1",
        adapter_version: "1",
        prompt_version: "keyword-generation-v1",
      },
      result: { item_count: 1, applied_keyword_set_version: 2 },
      attempts: 1,
      created_at: "2026-08-15T00:00:00Z",
      updated_at: "2026-08-15T00:00:02Z",
      finished_at: "2026-08-15T00:00:02Z",
    };
    api.createKeywordGeneration.mockResolvedValue(succeeded);
    api.getKeywordDraft.mockResolvedValueOnce(draft).mockResolvedValue({
      ...draft,
      version: 2,
      items: [{ ...draft.items[0], text: "恢复的 AI 关键词" }],
    });

    render(<KeywordEditorPage />);
    expect(await screen.findByText("关键词编辑器")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "AI 生成关键词" }));

    expect(await screen.findByText("已恢复此前成功的生成结果，关键词草稿已刷新")).toBeTruthy();
    await waitFor(() => expect(api.getKeywordDraft).toHaveBeenCalledTimes(2));
    expect(api.getKeywordGenerationJob).not.toHaveBeenCalled();
    expect((screen.getByLabelText("关键词-1") as HTMLInputElement).value).toBe("恢复的 AI 关键词");
  });

  it("requires explicit confirmation before a billable regeneration", async () => {
    api.createKeywordGeneration
      .mockRejectedValueOnce(
        new AuthApiError(new Response(null, { status: 409 }), {
          success: false,
          error: {
            code: "KEYWORD_REGENERATION_CONFIRMATION_REQUIRED",
            message: "需要确认消耗再生成额度",
            details: {},
          },
          request_id: "request-1",
        }),
      )
      .mockResolvedValueOnce({
        id: "job-regeneration",
        subject_id: "subject-1",
        subject_version_id: "sv-1",
        status: "queued" as const,
        version: 1,
        stable_error_code: "",
        billing: { billing_mode: "regeneration" as const, held: true, remaining: 1 },
        configuration: {
          target_count: 10,
          include_short: false,
          include_long_tail: false,
          include_regional: false,
          regions: [],
        },
        provenance: {
          provider_key: "mock",
          model_key: "mock-keyword-generation-v1",
          adapter_version: "1",
          prompt_version: "keyword-generation-v1",
        },
        result: null,
        attempts: 0,
        created_at: "2026-08-15T00:00:00Z",
        updated_at: "2026-08-15T00:00:00Z",
        finished_at: null,
      });

    render(<KeywordEditorPage />);
    expect(await screen.findByText("关键词编辑器")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "AI 生成关键词" }));
    expect(await screen.findByText("该主体已使用免费生成，请确认消耗一次再生成额度")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "确认消耗额度并再生成" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认再生成" }));

    await waitFor(() => expect(api.createKeywordGeneration).toHaveBeenCalledTimes(2));
    expect(api.createKeywordGeneration.mock.calls[0][1].regenerate).toBe(false);
    expect(api.createKeywordGeneration.mock.calls[1][1].regenerate).toBe(true);
  });

  it("shows a clear read-only reason when writing is unavailable", async () => {
    api.getKeywordDraft.mockResolvedValue({
      ...draft,
      can_write: false,
      read_only_reason: "subject_archived",
    });
    render(<KeywordEditorPage />);
    expect(await screen.findByText("已归档主体只能查看关键词历史。")).toBeTruthy();
    expect(screen.getByRole("button", { name: "添加关键词" })).toHaveProperty("disabled", true);
  });
});
