// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import ArticleWorkspace from "../app/subjects/[id]/articles/new/article-workspace";
import { ReportSharing } from "../components/report-sharing";
import type {
  Article,
  ArticleJob,
  ArticleType,
  PublishingChannel,
  SourcePack,
} from "../lib/articles-client";

const articleApi = vi.hoisted(() => ({
  checkPublication: vi.fn(),
  chooseComparison: vi.fn(),
  confirmSourcePack: vi.fn(),
  createArticle: vi.fn(),
  createArticleExport: vi.fn(),
  createChannelAdaptations: vi.fn(),
  createSourcePack: vi.fn(),
  generateArticle: vi.fn(),
  generateOutline: vi.fn(),
  getArticle: vi.fn(),
  getArticleJob: vi.fn(),
  getArticleTypes: vi.fn(),
  getChannelAdaptations: vi.fn(),
  getComparison: vi.fn(),
  getPublishingChannels: vi.fn(),
  optimizeArticle: vi.fn(),
  recheckQuality: vi.fn(),
  saveArticleDraft: vi.fn(),
  saveOutline: vi.fn(),
}));

vi.mock("../lib/articles-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/articles-client")>("../lib/articles-client");
  return Object.fromEntries(
    Object.entries({ ...actual, ...articleApi }).map(([key, value]) => [
      key,
      typeof value === "function" && key in articleApi
        ? (...args: unknown[]) => articleApi[key as keyof typeof articleApi](...args)
        : value,
    ]),
  );
});

const documentApi = vi.hoisted(() => ({
  getSubjectDocuments: vi.fn(),
  getDocumentParseResult: vi.fn(),
}));
vi.mock("../lib/documents-client", () => ({
  getSubjectDocuments: (...args: unknown[]) => documentApi.getSubjectDocuments(...args),
  getDocumentParseResult: (...args: unknown[]) => documentApi.getDocumentParseResult(...args),
}));

const webApi = vi.hoisted(() => ({ listWebSources: vi.fn() }));
vi.mock("../lib/web-sources-client", () => ({
  listWebSources: (...args: unknown[]) => webApi.listWebSources(...args),
}));

const shareApi = vi.hoisted(() => ({
  closeReportShare: vi.fn(),
  createReportShare: vi.fn(),
  getReportShares: vi.fn(),
  getWhiteLabel: vi.fn(),
  saveWhiteLabel: vi.fn(),
}));
vi.mock("../lib/report-sharing-client", () =>
  Object.fromEntries(
    Object.entries(shareApi).map(([key, value]) => [key, (...args: unknown[]) => value(...args)]),
  ),
);

const articleType: ArticleType = {
  id: "type-1",
  key: "brand_story",
  name: "品牌故事",
  description: "基于已确认事实生成品牌内容",
  template_version: {
    id: "template-1",
    version_no: 1,
    structure: {},
    network_policy: "optional",
    citation_required: true,
    allowed_source_types: ["subject", "document", "web"],
    recommended_channel_keys: ["website"],
  },
};

const channel: PublishingChannel = {
  id: "channel-1",
  key: "website",
  name: "企业官网",
  official_url: "https://example.com/official",
  channel_type: "owned_media",
  description: "仅提供导航和适配，不代替发布。",
  image_ratios: ["16:9"],
  template_version_id: "channel-template-1",
  rules: {},
  actual_publishing_supported: false,
};

const basePack: SourcePack = {
  id: "pack-1",
  subject_id: "subject-1",
  subject_version_id: "subject-version-1",
  article_type_id: articleType.id,
  template_version_id: articleType.template_version.id,
  status: "draft",
  conflict_status: "clear",
  conflicts: [],
  items: [
    {
      id: "source-1",
      source_type: "subject",
      title: "主体事实",
      url: "",
      trust_level: 100,
      verification_status: "verified",
      excerpt: "已确认主体事实",
      user_confirmed: true,
    },
  ],
  snapshot_digest: null,
};

const readyArticle: Article = {
  id: "article-1",
  subject_id: "subject-1",
  subject_version_id: "subject-version-1",
  article_type: { id: articleType.id, key: articleType.key, name: articleType.name },
  custom_type: "",
  template_version_id: articleType.template_version.id,
  source_pack_id: basePack.id,
  title: "品牌事实指南",
  content: "基于冻结资料包的正文。",
  status: "ready",
  content_depth: "standard",
  moderation_status: "passed",
  current_quality_score: 84,
  quality: {
    total_score: 84,
    grade: "good",
    dimensions: {
      subject_consistency: 84,
      factual_reliability: 84,
      topic_relevance: 84,
      structural_completeness: 84,
      readability: 84,
      keyword_naturalness: 84,
    },
    weights: {
      subject_consistency: 25,
      factual_reliability: 25,
      topic_relevance: 15,
      structural_completeness: 15,
      readability: 10,
      keyword_naturalness: 10,
    },
    suggestions: ["保持事实可核验"],
    first_free: true,
    advisory_only: true,
  },
  citations: [{ source_item_id: "source-1", paragraph_index: 0 }],
  outline: { text: "", status: "empty", generation_count: 0, version: 1 },
  version: 2,
  autosaved_at: null,
};

const failedJob: ArticleJob = {
  id: "job-1",
  article_id: readyArticle.id,
  operation: "body",
  status: "failed",
  billing: { quota_type: "article_credits", held: false, consumed: false },
  comparison_id: null,
  adaptation_id: null,
  safe_error_code: "ARTICLE_PROVIDER_UNAVAILABLE",
};

describe("Stage 2 content production, distribution, and sharing", () => {
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
    Object.defineProperty(globalThis, "crypto", {
      value: { randomUUID: () => "stage2-idempotency-key" },
      configurable: true,
    });
  });

  beforeEach(() => {
    for (const mock of [
      ...Object.values(articleApi),
      ...Object.values(shareApi),
      ...Object.values(documentApi),
      ...Object.values(webApi),
    ]) {
      mock.mockReset();
    }
    articleApi.getArticleTypes.mockResolvedValue({ items: [articleType] });
    articleApi.getPublishingChannels.mockResolvedValue({ items: [channel] });
    documentApi.getSubjectDocuments.mockResolvedValue({ documents: [] });
    webApi.listWebSources.mockResolvedValue({ results: [] });
    articleApi.createSourcePack.mockResolvedValue(basePack);
    articleApi.confirmSourcePack.mockResolvedValue({
      ...basePack,
      status: "confirmed",
      snapshot_digest: "a".repeat(64),
    });
    articleApi.createArticle.mockResolvedValue(readyArticle);
    articleApi.generateArticle.mockResolvedValue(failedJob);
  });

  afterEach(() => cleanup());

  it("freezes approved sources, preserves topic intent, and states provider/image boundaries", async () => {
    render(<ArticleWorkspace subjectId="subject-1" initialTopic="品牌事实指南" />);
    expect(await screen.findByDisplayValue("品牌事实指南")).toBeTruthy();
    expect(screen.getByText(/不会把未核验互联网内容伪装成引用/)).toBeTruthy();
    expect(screen.getByText("图片生成暂不在本波开放")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "核验并冻结资料包" }));
    await waitFor(() =>
      expect(articleApi.confirmSourcePack).toHaveBeenCalledWith(basePack, ["source-1"], []),
    );
    expect(articleApi.createArticle).toHaveBeenCalledWith("subject-1", {
      article_type_id: "type-1",
      content_depth: "standard",
      title: "品牌事实指南",
      source_pack_id: "pack-1",
    });
    expect(await screen.findByText("3. 当前唯一稿与质量建议")).toBeTruthy();
    expect(screen.getByText(/当前唯一稿与质量建议/)).toBeTruthy();
  });

  it("requires conflict choice, submits direct generation, and keeps failure non-consuming", async () => {
    const conflictPack: SourcePack = {
      ...basePack,
      conflict_status: "pending",
      conflicts: [
        {
          key: "founded_year",
          options: [
            { value: "2020", source_item_ids: ["source-1"] },
            { value: "2021", source_item_ids: ["source-2"] },
          ],
        },
      ],
    };
    articleApi.createSourcePack.mockResolvedValueOnce(conflictPack);
    articleApi.confirmSourcePack.mockResolvedValueOnce({
      ...conflictPack,
      status: "confirmed",
      conflict_status: "resolved",
      snapshot_digest: "b".repeat(64),
    });
    render(<ArticleWorkspace subjectId="subject-1" initialTopic="冲突事实文章" />);
    await screen.findByText("品牌故事");
    await userEvent.click(screen.getByRole("button", { name: "核验并冻结资料包" }));
    expect(await screen.findByText("冲突事实：founded_year")).toBeTruthy();
    await userEvent.click(screen.getByText("2020"));
    await userEvent.click(screen.getByRole("button", { name: "确认冲突选择并创建草稿" }));
    await waitFor(() =>
      expect(articleApi.confirmSourcePack).toHaveBeenCalledWith(
        conflictPack,
        ["source-1"],
        [{ key: "founded_year", value: "2020" }],
      ),
    );
    await userEvent.click(screen.getByText("直接生成正文"));
    await userEvent.click(screen.getByRole("button", { name: "生成正文（成功扣 1 文章额度）" }));
    expect(articleApi.generateArticle).toHaveBeenCalledWith("article-1");
    expect(await screen.findByText(/provider\/网络\/结构失败自动释放/)).toBeTruthy();
    expect(screen.getByText(/body · failed · article_credits/)).toBeTruthy();
  });

  it("charges channel adaptations independently and never claims third-party publication", async () => {
    articleApi.createChannelAdaptations.mockResolvedValue({
      estimated_article_credits: 1,
      items: [
        {
          id: "adaptation-1",
          article_id: readyArticle.id,
          channel,
          template_version_id: channel.template_version_id,
          job_id: "channel-job-1",
          title: "官网适配稿",
          content: "官网正文",
          status: "ready",
          quality_score: 88,
          safe_error_code: "",
          version: 2,
          job: { ...failedJob, id: "channel-job-1", operation: "channel_adapt" },
        },
      ],
    });
    render(<ArticleWorkspace subjectId="subject-1" initialTopic="渠道文章" />);
    await screen.findByText("品牌故事");
    await userEvent.click(screen.getByRole("button", { name: "核验并冻结资料包" }));
    const checkbox = await screen.findByRole("checkbox");
    await userEvent.click(checkbox);
    await userEvent.click(screen.getByRole("button", { name: "批量生成 1 个独立渠道稿" }));
    expect(articleApi.createChannelAdaptations).toHaveBeenCalledWith("article-1", ["channel-1"]);
    expect(await screen.findByText(/已提交 1 个独立渠道稿/)).toBeTruthy();
    expect(screen.getByText(/系统不代替登录或发布/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "打开官方平台" }).getAttribute("href")).toBe(
      channel.official_url,
    );
  });

  it("creates one-time-token report links, validates passwords, and closes shares", async () => {
    const activeShare = {
      id: "share-1",
      report_id: "report-1",
      subject_id: "subject-1",
      password_required: true,
      expires_at: "2026-09-20T00:00:00Z",
      closed_at: null,
      status: "active" as const,
      access_count: 2,
      last_accessed_at: null,
      created_at: "2026-08-21T00:00:00Z",
    };
    shareApi.getWhiteLabel.mockResolvedValue({
      enabled: true,
      uses_default_brand: false,
      config: {
        brand_name: "示例品牌",
        logo_document_version_id: null,
        cover_document_version_id: null,
        primary_color: "#1677ff",
        header_text: "",
        footer_text: "",
        contact: "",
        statement: "",
        version: 1,
      },
      effective_brand: {
        brand_name: "示例品牌",
        white_label: true,
        primary_color: "#1677ff",
      },
    });
    shareApi.getReportShares.mockResolvedValue({ items: [activeShare] });
    shareApi.createReportShare.mockResolvedValue({
      ...activeShare,
      id: "share-2",
      url: "/public/report-shares/high-entropy-token",
    });
    shareApi.closeReportShare.mockResolvedValue({
      ...activeShare,
      status: "closed",
      closed_at: "2026-08-21T01:00:00Z",
    });
    render(<ReportSharing reportId="report-1" subjectId="subject-1" />);
    expect(await screen.findByDisplayValue("示例品牌")).toBeTruthy();
    const createButton = screen.getByRole("button", { name: "创建完整报告分享" });
    await userEvent.type(screen.getByLabelText("分享密码"), "short");
    expect(createButton.hasAttribute("disabled")).toBe(true);
    await userEvent.clear(screen.getByLabelText("分享密码"));
    await userEvent.type(screen.getByLabelText("分享密码"), "Strong-Share-Password!");
    await userEvent.click(createButton);
    expect(shareApi.createReportShare).toHaveBeenCalledWith(
      "report-1",
      "Strong-Share-Password!",
      30,
    );
    expect(await screen.findByText(/原始高熵令牌只在此 URL 中返回一次/)).toBeTruthy();
    expect(screen.getByText(/high-entropy-token/)).toBeTruthy();
    await userEvent.click(screen.getAllByRole("button", { name: /关\s*闭/ })[1]);
    expect(shareApi.closeReportShare).toHaveBeenCalledWith("share-1");
  });
});
