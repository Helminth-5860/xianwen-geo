// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { PublicationCheckWorkspace } from "../components/publication-check-workspace";

const articleApi = vi.hoisted(() => ({
  checkPublication: vi.fn(),
  getPublicationChecks: vi.fn(),
  getPublishingChannels: vi.fn(),
  getSubjectArticles: vi.fn(),
}));

vi.mock("../lib/articles-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/articles-client")>("../lib/articles-client");
  return {
    ...actual,
    checkPublication: (...args: unknown[]) => articleApi.checkPublication(...args),
    getPublicationChecks: (...args: unknown[]) => articleApi.getPublicationChecks(...args),
    getPublishingChannels: (...args: unknown[]) => articleApi.getPublishingChannels(...args),
    getSubjectArticles: (...args: unknown[]) => articleApi.getSubjectArticles(...args),
  };
});

const article = {
  id: "article-1",
  subject_id: "subject-1",
  subject_version_id: "version-1",
  article_type: null,
  custom_type: "",
  template_version_id: null,
  source_pack_id: null,
  title: "已经发布的 GEO 文章",
  content: "这是一篇用于发布检测的完整文章正文。",
  status: "ready" as const,
  content_depth: "standard" as const,
  moderation_status: "passed" as const,
  current_quality_score: 85,
  quality: null,
  citations: [],
  outline: null,
  version: 1,
  autosaved_at: null,
};

const channels = [
  {
    id: "website-channel",
    key: "website",
    name: "企业官网",
    official_url: "https://www.google.com/",
    channel_type: "owned_media",
    description: "",
    image_ratios: [],
    template_version_id: "website-template",
    rules: {},
    actual_publishing_supported: false as const,
  },
  {
    id: "zhihu-channel",
    key: "zhihu",
    name: "知乎",
    official_url: "https://www.zhihu.com/",
    channel_type: "knowledge_community",
    description: "",
    image_ratios: [],
    template_version_id: "zhihu-template",
    rules: {},
    actual_publishing_supported: false as const,
  },
];

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
  articleApi.getSubjectArticles.mockResolvedValue({
    items: [article],
    pagination: { page: 1, page_size: 100, count: 1, total_pages: 1 },
  });
  articleApi.getPublishingChannels.mockResolvedValue({ items: channels });
  articleApi.getPublicationChecks.mockResolvedValue({
    items: [],
    pagination: { page: 1, page_size: 20, count: 0, total_pages: 0 },
  });
  articleApi.checkPublication.mockResolvedValue({
    id: "check-1",
    subject_id: "subject-1",
    article_id: "article-1",
    adaptation_id: null,
    channel_id: "zhihu-channel",
    url: "https://www.zhihu.com/p/123",
    result: "success",
    detected_title: article.title,
    match_summary: "检测到对应标题或正文。",
    safe_failure_code: "",
    checked_at: "2026-08-27T12:00:00Z",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("发布检测页面", () => {
  it("只核验公开链接，并按域名复用现有发布检测接口", async () => {
    render(<PublicationCheckWorkspace subjectId="subject-1" />);

    expect(await screen.findByRole("heading", { name: "发布检测" })).toBeTruthy();
    await userEvent.type(
      screen.getByRole("textbox", { name: "公开文章链接" }),
      "https://www.zhihu.com/p/123",
    );
    await userEvent.click(screen.getByRole("button", { name: "检测是否发布成功" }));

    await waitFor(() =>
      expect(articleApi.checkPublication).toHaveBeenCalledWith(
        "subject-1",
        "article-1",
        "zhihu-channel",
        "https://www.zhihu.com/p/123",
      ),
    );
    expect(await screen.findAllByText("发布成功")).toHaveLength(2);
    expect(screen.getByText("检测到对应标题或正文。")).toBeTruthy();
  });

  it("没有可检测文章时给出生成文章入口", async () => {
    articleApi.getSubjectArticles.mockResolvedValue({
      items: [],
      pagination: { page: 1, page_size: 100, count: 0, total_pages: 0 },
    });

    render(<PublicationCheckWorkspace subjectId="subject-1" />);

    expect(await screen.findByText("当前主体还没有可用于比对的已生成文章")).toBeTruthy();
    expect(screen.getByRole("link", { name: "去生成文章" }).getAttribute("href")).toBe(
      "/subjects/subject-1/articles/new",
    );
  });
});
