// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ArticleImagesWorkspace } from "../components/article-images-workspace";

const imageApi = vi.hoisted(() => ({
  appealImageModeration: vi.fn(),
  attachImage: vi.fn(),
  createImageBatchDownload: vi.fn(),
  deriveImage: vi.fn(),
  deriveImageAI: vi.fn(),
  generateImage: vi.fn(),
  getImageJob: vi.fn(),
  getImageRecommendations: vi.fn(),
  getImageSizes: vi.fn(),
  getImageStyles: vi.fn(),
  getSubjectImages: vi.fn(),
  saveImageToLibrary: vi.fn(),
}));

vi.mock("../lib/images-client", () =>
  Object.fromEntries(
    Object.entries(imageApi).map(([key, value]) => [key, (...args: unknown[]) => value(...args)]),
  ),
);

const quota = { available: 3, frozen: 0, consumed: 1 };
const asset = {
  id: "image-1",
  subject_id: "subject-1",
  article_id: null,
  job_id: "job-1",
  role: "cover",
  source_type: "generated",
  width: 1200,
  height: 630,
  mime_type: "image/png",
  size_bytes: 1000,
  sha256: "a".repeat(64),
  provider: "doubao",
  provider_model: "doubao-seedream-5-0-260128",
  generation_capability: "image_generation",
  adapter_version: "doubao-image-generations-v1",
  moderation_status: "approved",
  is_subject_library: false,
  lifecycle_status: "active",
  url: "https://assets.example/private-signed.png",
  url_expires_in: 300,
  generated_at: "2026-08-21T00:00:00Z",
  available_at: "2026-08-21T00:00:00Z",
  created_at: "2026-08-21T00:00:00Z",
  version: 1,
} as const;

const queued = {
  id: "job-1",
  subject_id: "subject-1",
  article_id: "article-1",
  generation_type: "generate",
  role: "cover",
  status: "queued",
  attempt_count: 0,
  max_retries: 1,
  safe_error_code: "",
  provider: "doubao",
  provider_model: "doubao-seedream-5-0-260128",
  runtime_version: 2,
  adapter_version: "doubao-image-generations-v1",
  prompt_version: "geo-image-generation-v1",
  quota_status: "open",
  image: null,
  created_at: "2026-08-21T00:00:00Z",
  started_at: null,
  finished_at: null,
} as const;

describe("Stage 2 image generation workspace", () => {
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
      value: { randomUUID: () => "image-idempotency-key" },
      configurable: true,
    });
  });

  beforeEach(() => {
    Object.values(imageApi).forEach((mock) => mock.mockReset());
    imageApi.getImageSizes.mockResolvedValue([
      {
        id: "size-1",
        key: "landscape",
        name: "横图",
        aspect_ratio: "16:9",
        width: 1200,
        height: 630,
        applicable_channels: [],
        applicable_roles: [],
        version: 1,
      },
    ]);
    imageApi.getImageStyles.mockResolvedValue([
      {
        id: "style-1",
        key: "natural",
        name: "自然专业",
        description: "真实",
        applicable_roles: [],
        version: 1,
      },
    ]);
    imageApi.getImageRecommendations.mockResolvedValue({
      recommendations: [
        {
          position: "cover",
          role: "cover",
          purpose: "文章封面",
          prompt: "推荐封面提示词",
          size_preset_id: "size-1",
          style_preset_id: "style-1",
          requires_confirmation: true,
        },
      ],
    });
    imageApi.getSubjectImages.mockResolvedValue({ results: [], quota });
  });

  afterEach(() => cleanup());

  it("confirms recommendation, generates, polls, previews, and attaches private asset", async () => {
    imageApi.generateImage.mockResolvedValue({
      job: queued,
      jobs: [queued],
      quota: { ...quota, available: 2, frozen: 1 },
    });
    imageApi.getImageJob.mockResolvedValue({
      ...queued,
      status: "succeeded",
      attempt_count: 1,
      quota_status: "settled",
      image: asset,
      finished_at: "2026-08-21T00:00:01Z",
    });
    imageApi.getSubjectImages
      .mockResolvedValueOnce({ results: [], quota })
      .mockResolvedValue({ results: [asset], quota: { available: 2, frozen: 0, consumed: 2 } });
    imageApi.attachImage.mockResolvedValue({ ...asset, article_id: "article-1", version: 2 });
    render(
      <ArticleImagesWorkspace
        subjectId="subject-1"
        articleId="article-1"
        articleTitle="品牌指南"
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "采用并编辑" }));
    expect((screen.getByLabelText("图片提示词") as HTMLTextAreaElement).value).toBe(
      "推荐封面提示词",
    );
    await userEvent.click(screen.getByRole("button", { name: /生成图片/ }));
    expect(imageApi.generateImage).toHaveBeenCalledWith(
      "subject-1",
      expect.objectContaining({ article_id: "article-1", prompt: "推荐封面提示词" }),
    );
    expect(await screen.findByText("图片任务：succeeded", {}, { timeout: 3000 })).toBeTruthy();
    expect(screen.getByAltText("生成图片预览")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "选入当前文章" }));
    expect(imageApi.attachImage).toHaveBeenCalledWith("image-1", "article-1", 1);
  });

  it("shows moderation failure, releases quota feedback, and offers retry", async () => {
    imageApi.generateImage.mockResolvedValue({
      job: queued,
      jobs: [queued],
      quota: { ...quota, frozen: 1 },
    });
    imageApi.getImageJob.mockResolvedValue({
      ...queued,
      status: "failed",
      attempt_count: 1,
      safe_error_code: "IMAGE_OUTPUT_SENSITIVE",
      quota_status: "settled",
      finished_at: "2026-08-21T00:00:01Z",
    });
    render(
      <ArticleImagesWorkspace
        subjectId="subject-1"
        articleId="article-1"
        articleTitle="品牌指南"
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /生成图片/ }));
    expect(
      await screen.findByText("生成结果未通过内容安全检查，额度已释放。", {}, { timeout: 3000 }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "修改后重试" })).toBeTruthy();
  });

  it("supports an approved subject-library reference image", async () => {
    imageApi.getSubjectImages.mockResolvedValue({ results: [asset], quota });
    imageApi.generateImage.mockResolvedValue({ job: queued, jobs: [queued], quota });
    render(
      <ArticleImagesWorkspace
        subjectId="subject-1"
        articleId="article-1"
        articleTitle="品牌指南"
      />,
    );
    await screen.findByText("主体图片库");
    await userEvent.click(screen.getByLabelText("主体图库参考图"));
    await userEvent.click(await screen.findByText("cover · 1200×630"));
    await userEvent.click(screen.getByRole("button", { name: /生成图片/ }));
    expect(imageApi.generateImage).toHaveBeenCalledWith(
      "subject-1",
      expect.objectContaining({ reference_asset_id: "image-1", reference_url: "" }),
    );
  });

  it("supports a temporary uploaded image document as the exclusive reference", async () => {
    imageApi.generateImage.mockResolvedValue({ job: queued, jobs: [queued], quota });
    render(
      <ArticleImagesWorkspace
        subjectId="subject-1"
        articleId="article-1"
        articleTitle="品牌指南"
        referenceDocuments={[{ id: "document-version-1", label: "临时产品图 · PNG" }]}
      />,
    );
    await screen.findByText("主体图片库");
    await userEvent.click(screen.getByLabelText("临时上传参考图"));
    await userEvent.click(await screen.findByText("临时产品图 · PNG"));
    await userEvent.click(screen.getByRole("button", { name: /生成图片/ }));
    expect(imageApi.generateImage).toHaveBeenCalledWith(
      "subject-1",
      expect.objectContaining({
        reference_asset_id: null,
        reference_document_version_id: "document-version-1",
        reference_url: "",
      }),
    );
  });

  it("submits AI reference editing through a billed image job", async () => {
    imageApi.generateImage.mockResolvedValue({ job: queued, jobs: [queued], quota });
    imageApi.getImageJob.mockResolvedValue({
      ...queued,
      status: "succeeded",
      attempt_count: 1,
      quota_status: "settled",
      image: asset,
      finished_at: "2026-08-21T00:00:01Z",
    });
    imageApi.deriveImageAI.mockResolvedValue({
      job: { ...queued, id: "ai-edit-job", generation_type: "edit", role: "channel" },
      quota: { ...quota, available: 2, frozen: 1 },
    });
    render(
      <ArticleImagesWorkspace
        subjectId="subject-1"
        articleId="article-1"
        articleTitle="品牌指南"
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /生成图片/ }));
    await screen.findByAltText("生成图片预览", {}, { timeout: 3000 });
    await userEvent.click(screen.getByRole("button", { name: /AI 智能扩图\/重构/ }));
    expect(imageApi.deriveImageAI).toHaveBeenCalledWith(
      "image-1",
      expect.objectContaining({ size_preset_id: "size-1", style_preset_id: "style-1" }),
    );
  });

  it("surfaces permission/runtime errors without claiming success", async () => {
    imageApi.getImageSizes.mockRejectedValue(new Error("没有图片生成权限"));
    render(
      <ArticleImagesWorkspace
        subjectId="subject-1"
        articleId="article-1"
        articleTitle="品牌指南"
      />,
    );
    expect(await screen.findByText("没有图片生成权限")).toBeTruthy();
    expect(screen.queryByAltText("生成图片预览")).toBeNull();
  });
});
