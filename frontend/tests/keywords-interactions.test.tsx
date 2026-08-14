// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import KeywordEditorPage from "@/app/subjects/[id]/keywords/page";

const api = vi.hoisted(() => ({
  getKeywordDraft: vi.fn(),
  getKeywordVersions: vi.fn(),
  getKeywordVersion: vi.fn(),
  saveKeywordDraft: vi.fn(),
  commitKeywords: vi.fn(),
}));

vi.mock("@/lib/keywords-client", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/keywords-client")>("@/lib/keywords-client");
  return { ...actual, ...api };
});
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "subject-1" }) }));

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
});

afterEach(cleanup);

describe("KeywordEditorPage", () => {
  it("adds and saves a manual keyword draft without generation UI", async () => {
    api.saveKeywordDraft.mockResolvedValue({ ...draft, version: 2 });
    render(<KeywordEditorPage />);

    expect(await screen.findByText("关键词编辑器")).toBeTruthy();
    expect(screen.queryByText(/AI 生成/)).toBeNull();
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
