// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DistillationPanel from "@/app/subjects/[id]/keywords/distillation-panel";
import { AuthApiError } from "@/lib/auth-client";

const api = vi.hoisted(() => ({
  getDistillationDraft: vi.fn(),
  createDistillation: vi.fn(),
  getDistillationJob: vi.fn(),
  saveDistillationDraft: vi.fn(),
  confirmDistillation: vi.fn(),
}));

vi.mock("@/lib/keywords-client", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/keywords-client")>("@/lib/keywords-client");
  return { ...actual, ...api };
});

const source = (id: string, text: string, sortOrder: number) => ({
  id,
  text,
  structure_type: "general" as const,
  is_regional: false,
  region_level: null,
  region_text: null,
  sort_order: sortOrder,
});

const item = (
  id: string,
  text: string,
  action: "keep" | "merge" | "delete" | "low_value",
  sortOrder: number,
) => ({
  source_keyword: source(id, text, sortOrder),
  action,
  canonical_keyword_id: action === "merge" ? "keyword-2" : null,
  merge_group_key: action === "merge" ? "11111111-1111-4111-8111-111111111111" : null,
  ai_action: action,
  ai_canonical_keyword_id: action === "merge" ? "keyword-2" : null,
  ai_merge_group_key: action === "merge" ? "11111111-1111-4111-8111-111111111111" : null,
  ai_reason: `AI reason ${sortOrder + 1}`,
  user_reason: "",
  user_overridden: false,
  sort_order: sortOrder,
});

const draft = {
  version: 1,
  can_write: true,
  read_only_reason: null,
  current_keyword_set_version: { id: "keyword-version-1", version_no: 1, item_count: 5 },
  draft_input_version: { id: "keyword-version-1", version_no: 1, item_count: 5 },
  source_result_id: "result-1",
  current_distillation_version_no: null,
  items: [
    item("keyword-1", "品牌咨询", "keep", 0),
    item("keyword-2", "企业品牌服务", "merge", 1),
    item("keyword-3", "品牌企业服务", "merge", 2),
    item("keyword-4", "无关旧词", "delete", 3),
    item("keyword-5", "低价值宽泛词", "low_value", 4),
  ],
};

const queued = {
  id: "distillation-job-1",
  subject_id: "subject-1",
  subject_version_id: "subject-version-1",
  keyword_set_version_id: "keyword-version-1",
  status: "queued" as const,
  version: 1,
  stable_error_code: "",
  billing: { billing_mode: "free_initial" as const, held: false, remaining: null },
  provenance: {
    provider_key: "mock",
    model_key: "mock-keyword-distillation-v1",
    adapter_version: "1",
    prompt_version: "keyword-distillation-v1",
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
  vi.clearAllMocks();
  api.getDistillationDraft.mockResolvedValue(draft);
});

afterEach(cleanup);

describe("DistillationPanel", () => {
  it("starts, polls success, and protects unsaved keyword changes", async () => {
    const { rerender } = render(<DistillationPanel subjectId="subject-1" keywordDirty />);
    expect(await screen.findByText("关键词蒸馏")).toBeTruthy();
    expect(screen.getByRole("button", { name: "AI 蒸馏关键词" })).toHaveProperty("disabled", true);
    expect(api.createDistillation).not.toHaveBeenCalled();

    api.createDistillation.mockResolvedValue(queued);
    api.getDistillationJob.mockResolvedValue({
      ...queued,
      status: "succeeded",
      version: 3,
      attempts: 1,
      result: { item_count: 5, applied_workspace_version: 1 },
      finished_at: "2026-08-16T00:00:01Z",
    });
    rerender(<DistillationPanel subjectId="subject-1" keywordDirty={false} />);
    await userEvent.click(screen.getByRole("button", { name: "AI 蒸馏关键词" }));
    await waitFor(() => expect(api.createDistillation).toHaveBeenCalledTimes(1));
    expect(api.createDistillation.mock.calls[0][1]).toEqual({
      keywordSetVersionId: "keyword-version-1",
      expectedWorkspaceVersion: 1,
      regenerate: false,
    });
    await waitFor(() => expect(api.getDistillationJob).toHaveBeenCalledWith("distillation-job-1"), {
      timeout: 2500,
    });
    expect(await screen.findByText("蒸馏建议已生成，请调整并明确确认")).toBeTruthy();
  });

  it("saves user adjustment separately and confirms an immutable version", async () => {
    api.saveDistillationDraft.mockImplementation(async (_subjectId, _version, items) => ({
      ...draft,
      version: 2,
      items,
    }));
    api.confirmDistillation.mockResolvedValue({
      version: {
        id: "distillation-version-1",
        version_no: 1,
        subject_version_id: "subject-version-1",
        keyword_set_version_id: "keyword-version-1",
        source_result_id: "result-1",
        item_count: 5,
        confirmed_at: "2026-08-16T00:00:02Z",
        items: draft.items,
      },
    });
    render(<DistillationPanel subjectId="subject-1" keywordDirty={false} />);
    expect(await screen.findByText("无关旧词")).toBeTruthy();

    await userEvent.click(screen.getByLabelText("蒸馏动作-4"));
    await userEvent.click(
      await screen.findByText("保留", { selector: ".ant-select-item-option-content" }),
    );
    await userEvent.type(screen.getByLabelText("人工说明-4"), "业务确认后保留");
    expect(screen.getByRole("button", { name: "确认蒸馏结果" })).toHaveProperty("disabled", true);
    await userEvent.click(screen.getByRole("button", { name: "保存蒸馏调整" }));

    await waitFor(() => expect(api.saveDistillationDraft).toHaveBeenCalledTimes(1));
    const submitted = api.saveDistillationDraft.mock.calls[0][2][3];
    expect(submitted.action).toBe("keep");
    expect(submitted.user_reason).toBe("业务确认后保留");
    expect(submitted.ai_action).toBe("delete");

    await userEvent.click(screen.getByRole("button", { name: "确认蒸馏结果" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认结果" }));
    await waitFor(() => expect(api.confirmDistillation).toHaveBeenCalledWith("subject-1", 2));
  });

  it("拆分合并组时原子恢复组内全部关键词", async () => {
    api.saveDistillationDraft.mockImplementation(async (_subjectId, _version, items) => ({
      ...draft,
      version: 2,
      items,
    }));
    render(<DistillationPanel subjectId="subject-1" keywordDirty={false} />);
    expect(await screen.findByRole("button", { name: "拆分合并组 1" })).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "拆分合并组 1" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认拆分" }));
    await userEvent.click(screen.getByRole("button", { name: "保存蒸馏调整" }));

    await waitFor(() => expect(api.saveDistillationDraft).toHaveBeenCalledTimes(1));
    const submitted = api.saveDistillationDraft.mock.calls[0][2];
    for (const index of [1, 2]) {
      expect(submitted[index]).toMatchObject({
        action: "keep",
        canonical_keyword_id: null,
        merge_group_key: null,
      });
    }
  });

  it("requires explicit confirmation before billable re-distillation", async () => {
    api.createDistillation
      .mockRejectedValueOnce(
        new AuthApiError(new Response(null, { status: 409 }), {
          success: false,
          error: {
            code: "DISTILLATION_REGENERATION_CONFIRMATION_REQUIRED",
            message: "需要确认再蒸馏",
            details: {},
          },
          request_id: "request-1",
        }),
      )
      .mockResolvedValueOnce({
        ...queued,
        billing: { billing_mode: "regeneration" as const, held: true, remaining: 1 },
      });
    render(<DistillationPanel subjectId="subject-1" keywordDirty={false} />);
    expect(await screen.findByText("关键词蒸馏")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "AI 蒸馏关键词" }));
    expect(await screen.findByText("该主体已有成功蒸馏，请确认消耗一次再蒸馏额度")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "确认消耗额度并再蒸馏" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认再蒸馏" }));
    await waitFor(() => expect(api.createDistillation).toHaveBeenCalledTimes(2));
    expect(api.createDistillation.mock.calls[1][1].regenerate).toBe(true);
  });
});
