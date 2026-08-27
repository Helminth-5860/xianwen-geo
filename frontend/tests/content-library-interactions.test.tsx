// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import ContentLibrary from "../app/subjects/[id]/articles/content-library";
import type { Article } from "../lib/articles-client";

const articleApi = vi.hoisted(() => ({ getContentLibrary: vi.fn() }));

vi.mock("../lib/articles-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/articles-client")>("../lib/articles-client");
  return {
    ...actual,
    getContentLibrary: (...args: unknown[]) => articleApi.getContentLibrary(...args),
  };
});

const savedArticle: Article = {
  id: "article-1",
  subject_id: "subject-1",
  subject_version_id: "subject-version-1",
  article_type: { id: "type-1", key: "brand_story", name: "品牌故事" },
  custom_type: "",
  template_version_id: "template-1",
  source_pack_id: "pack-1",
  title: "已经保存的 GEO 文章",
  content: "这是刷新页面后仍能从内容库读取的完整正文。",
  status: "ready",
  content_depth: "standard",
  moderation_status: "passed",
  current_quality_score: 88,
  quality: null,
  citations: [],
  outline: null,
  version: 3,
  autosaved_at: "2026-08-27T02:00:00Z",
};

describe("内容库", () => {
  beforeAll(() => {
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
    articleApi.getContentLibrary.mockResolvedValue({
      items: [savedArticle],
      pagination: { page: 1, page_size: 20, count: 21, total_pages: 2 },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("按主体读取明确保存的文章，支持全文查看和每页20条分页", async () => {
    render(<ContentLibrary subjectId="subject-1" />);

    expect(await screen.findByText("已经保存的 GEO 文章")).toBeTruthy();
    expect(articleApi.getContentLibrary).toHaveBeenCalledWith("subject-1", 1);
    expect(screen.getByText("已保存文章 21 篇")).toBeTruthy();
    expect(screen.getByRole("link", { name: "生成新文章" }).getAttribute("href")).toBe(
      "/subjects/subject-1/articles/new",
    );

    await userEvent.click(screen.getByRole("button", { name: "查看全文" }));
    expect(screen.getAllByText("这是刷新页面后仍能从内容库读取的完整正文。").length).toBe(2);

    await userEvent.click(screen.getByTitle("Next Page"));
    await waitFor(() => expect(articleApi.getContentLibrary).toHaveBeenCalledWith("subject-1", 2));
  });
});
