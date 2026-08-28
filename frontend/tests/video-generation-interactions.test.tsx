// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import VideoGenerationWorkspace from "../app/subjects/[id]/videos/new/video-generation-workspace";
import { VideoLibraryWorkspace } from "../components/video-library-workspace";

const videoApi = vi.hoisted(() => ({
  createVideoDownloadIntent: vi.fn(),
  createVideoJob: vi.fn(),
  listSubjectVideoJobs: vi.fn(),
  listSubjectVideos: vi.fn(),
  regenerateVideoJob: vi.fn(),
  saveVideoToLibrary: vi.fn(),
}));

const documentApi = vi.hoisted(() => ({
  completeUploadIntent: vi.fn(),
  createUploadIntent: vi.fn(),
  getUploadIntent: vi.fn(),
  uploadDirect: vi.fn(),
}));

vi.mock("../lib/videos-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/videos-client")>("../lib/videos-client");
  return {
    ...actual,
    ...Object.fromEntries(
      Object.entries(videoApi).map(([key, value]) => [key, (...args: unknown[]) => value(...args)]),
    ),
  };
});

vi.mock("../lib/documents-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/documents-client")>("../lib/documents-client");
  return {
    ...actual,
    ...Object.fromEntries(
      Object.entries(documentApi).map(([key, value]) => [
        key,
        (...args: unknown[]) => value(...args),
      ]),
    ),
    newUploadIdempotencyKey: () => "upload-key",
  };
});

const quota = { available: 20, frozen: 0, consumed: 5, unlimited: false };
const pagination = { page: 1, page_size: 20, count: 0, total_pages: 0 };
const video = {
  id: "video-1",
  subject_id: "subject-1",
  job_id: "job-1",
  duration_seconds: 5,
  aspect_ratio: "9:16",
  resolution: "720p",
  mime_type: "video/mp4",
  size_bytes: 1024,
  is_subject_library: false,
  url: "/api/v1/video-jobs/job-1/content",
  url_expires_in: null,
  version: 1,
  created_at: "2026-08-28T08:00:00Z",
} as const;

const queuedJob = {
  id: "job-1",
  subject_id: "subject-1",
  generation_mode: "text",
  prompt: "蓝色科技光线汇聚成企业标志",
  source_document_version_id: null,
  aspect_ratio: "9:16",
  duration_seconds: 5,
  resolution: "720p",
  status: "queued",
  safe_error_code: "",
  quota_status: "held",
  video: null,
  version: 1,
  created_at: "2026-08-28T08:00:00Z",
  started_at: null,
  completed_at: null,
} as const;

const succeededJob = {
  ...queuedJob,
  status: "succeeded",
  quota_status: "consumed",
  video,
  version: 2,
  started_at: "2026-08-28T08:00:01Z",
  completed_at: "2026-08-28T08:00:12Z",
} as const;

function emptyList() {
  return { items: [], pagination, quota };
}

describe("视频生成页面", () => {
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
      value: { randomUUID: vi.fn(() => "video-key") },
      configurable: true,
    });
  });

  beforeEach(() => {
    Object.values(videoApi).forEach((mock) => mock.mockReset());
    Object.values(documentApi).forEach((mock) => mock.mockReset());
    videoApi.listSubjectVideoJobs.mockResolvedValue(emptyList());
    videoApi.listSubjectVideos.mockResolvedValue({ items: [], pagination });
    videoApi.createVideoJob.mockResolvedValue({ job: queuedJob, quota: { ...quota, frozen: 5 } });
    videoApi.regenerateVideoJob.mockResolvedValue({
      job: { ...queuedJob, id: "job-2" },
      quota: { ...quota, frozen: 5 },
    });
    videoApi.createVideoDownloadIntent.mockResolvedValue({
      url: "#video-download",
      expires_in: 60,
    });
    videoApi.saveVideoToLibrary.mockResolvedValue({
      ...video,
      is_subject_library: true,
      version: 2,
    });
    documentApi.createUploadIntent.mockResolvedValue({
      intent: {
        id: "intent-1",
        status: "pending_upload",
        version: 1,
        declared_filename: "reference.png",
        declared_file_kind: "png",
        declared_size: 100,
        expires_at: "2026-08-28T09:00:00Z",
        stable_error_code: "",
        document_id: null,
        document_version_id: null,
      },
      upload: { method: "POST", url: "https://upload.example", fields: {}, expires_in: 60 },
    });
    documentApi.uploadDirect.mockImplementation(
      (_credential: unknown, _file: unknown, onProgress: (percent: number) => void) => {
        onProgress(100);
        return Promise.resolve();
      },
    );
    documentApi.completeUploadIntent.mockResolvedValue({
      id: "intent-1",
      status: "completed",
      version: 2,
      declared_filename: "reference.png",
      declared_file_kind: "png",
      declared_size: 100,
      expires_at: "2026-08-28T09:00:00Z",
      stable_error_code: "",
      document_id: "document-1",
      document_version_id: "document-version-1",
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("只提供两种生成方式、固定比例时长和 720P，并显示预计额度", async () => {
    render(<VideoGenerationWorkspace subjectId="subject-1" />);

    expect(await screen.findByRole("heading", { name: "AI 视频生成" })).toBeTruthy();
    expect(screen.getByText("文字生成视频")).toBeTruthy();
    expect(screen.getByText("图片生成视频")).toBeTruthy();
    expect(screen.getByText("竖屏 9:16")).toBeTruthy();
    expect(screen.getByText("横屏 16:9")).toBeTruthy();
    expect(screen.getByText("5 秒")).toBeTruthy();
    expect(screen.getByText("10 秒")).toBeTruthy();
    expect(screen.getByText("清晰度固定为 720P")).toBeTruthy();
    expect(screen.queryByText(/1080P|2K|4K|供应商|模型选择/)).toBeNull();
    expect(screen.getByText("5 个视频额度")).toBeTruthy();
    expect(screen.queryByText("参考图片")).toBeNull();
  });

  it("按用户设置创建文字视频并用固定幂等键防止重复提交", async () => {
    const user = userEvent.setup();
    render(<VideoGenerationWorkspace subjectId="subject-1" />);
    await screen.findByText("当前可用：20");

    await user.type(screen.getByLabelText("视频内容描述"), "城市夜景中出现企业品牌标志");
    await user.click(screen.getByText("横屏 16:9"));
    await user.click(screen.getByText("10 秒"));
    await user.click(screen.getByRole("button", { name: /生成视频/ }));

    await waitFor(() => expect(videoApi.createVideoJob).toHaveBeenCalledTimes(1));
    expect(videoApi.createVideoJob).toHaveBeenCalledWith(
      "subject-1",
      {
        generation_mode: "text",
        prompt: "城市夜景中出现企业品牌标志",
        source_document_version_id: null,
        aspect_ratio: "16:9",
        duration_seconds: 10,
      },
      "video-key",
    );
    expect(screen.getByText(/暂时预留 10 个视频额度/)).toBeTruthy();
    expect(screen.getByText("排队中")).toBeTruthy();
  });

  it("图片模式必须使用现有私有上传链路，不提供公网链接输入", async () => {
    const user = userEvent.setup();
    const { container } = render(<VideoGenerationWorkspace subjectId="subject-1" />);
    await screen.findByText("当前可用：20");

    await user.click(screen.getByText("图片生成视频"));
    await user.type(screen.getByLabelText("视频内容描述"), "让参考图片中的产品缓慢旋转");
    expect((screen.getByRole("button", { name: /生成视频/ }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(screen.queryByPlaceholderText(/链接|网址|URL/)).toBeNull();

    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).toBeTruthy();
    const file = new File([new Uint8Array([1, 2, 3])], "reference.png", {
      type: "image/png",
    });
    fireEvent.change(input!, { target: { files: [file] } });

    expect(await screen.findByText("已上传：reference.png")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /生成视频/ }));
    await waitFor(() => expect(videoApi.createVideoJob).toHaveBeenCalledTimes(1));
    expect(videoApi.createVideoJob.mock.calls[0][1]).toMatchObject({
      generation_mode: "image",
      source_document_version_id: "document-version-1",
    });
    expect(documentApi.createUploadIntent).toHaveBeenCalledWith(
      "subject-1",
      expect.any(File),
      "upload-key",
    );
  });

  it("刷新后读取后端记录，成功视频可播放、保存、下载和重新生成", async () => {
    videoApi.listSubjectVideoJobs.mockResolvedValue({
      items: [succeededJob],
      pagination: { ...pagination, count: 1, total_pages: 1 },
      quota,
    });
    const user = userEvent.setup();
    render(<VideoGenerationWorkspace subjectId="subject-1" />);

    expect(await screen.findByText("已完成")).toBeTruthy();
    expect(screen.getByLabelText("生成视频预览").getAttribute("src")).toBe(video.url);

    await user.click(screen.getByRole("button", { name: /保存到视频库/ }));
    await waitFor(() => expect(videoApi.saveVideoToLibrary).toHaveBeenCalledWith("job-1", 1));
    expect(
      (screen.getByRole("button", { name: /已保存到视频库/ }) as HTMLButtonElement).disabled,
    ).toBe(true);

    await user.click(screen.getByRole("button", { name: /下\s*载/ }));
    await waitFor(() => expect(videoApi.createVideoDownloadIntent).toHaveBeenCalledWith("job-1"));

    await user.click(screen.getByRole("button", { name: /重新生成/ }));
    await waitFor(() =>
      expect(videoApi.regenerateVideoJob).toHaveBeenCalledWith("job-1", "video-key"),
    );
  });

  it("有进行中记录时自动刷新，并且不会显示内部英文状态", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    videoApi.listSubjectVideoJobs
      .mockResolvedValueOnce({
        items: [queuedJob],
        pagination: { ...pagination, count: 1, total_pages: 1 },
        quota: { ...quota, frozen: 5 },
      })
      .mockResolvedValue({
        items: [succeededJob],
        pagination: { ...pagination, count: 1, total_pages: 1 },
        quota,
      });
    render(<VideoGenerationWorkspace subjectId="subject-1" />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(await screen.findByText("排队中")).toBeTruthy();
    expect(screen.queryByText(/queued|processing|succeeded|provider|job/i)).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });
    expect(await screen.findByText("已完成")).toBeTruthy();
  });

  it("切换主体后不显示上一个主体的记录", async () => {
    videoApi.listSubjectVideoJobs.mockImplementation((subjectId: string) =>
      Promise.resolve({
        items: subjectId === "subject-1" ? [succeededJob] : [],
        pagination: {
          ...pagination,
          count: subjectId === "subject-1" ? 1 : 0,
          total_pages: subjectId === "subject-1" ? 1 : 0,
        },
        quota,
      }),
    );
    const { rerender } = render(<VideoGenerationWorkspace subjectId="subject-1" />);
    expect(await screen.findByText("已完成")).toBeTruthy();

    rerender(<VideoGenerationWorkspace subjectId="subject-2" />);
    expect(screen.queryByLabelText("生成视频预览")).toBeNull();
    expect(await screen.findByText("还没有视频，完成上方设置后即可开始生成。")).toBeTruthy();
  });
});

describe("视频库页面", () => {
  beforeEach(() => {
    videoApi.listSubjectVideos.mockResolvedValue({
      items: [{ ...video, is_subject_library: true }],
      pagination: { ...pagination, count: 21, total_pages: 2 },
    });
    videoApi.createVideoDownloadIntent.mockResolvedValue({
      url: "#library-download",
      expires_in: 60,
    });
  });

  afterEach(() => cleanup());

  it("每页读取 20 条已保存视频并提供播放、下载和分页", async () => {
    const user = userEvent.setup();
    render(<VideoLibraryWorkspace subjectId="subject-1" />);

    expect(await screen.findByLabelText("视频库预览")).toBeTruthy();
    expect(videoApi.listSubjectVideos).toHaveBeenCalledWith(
      "subject-1",
      1,
      20,
      expect.any(AbortSignal),
    );
    expect(screen.getByLabelText("视频库分页")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /下\s*载/ }));
    await waitFor(() => expect(videoApi.createVideoDownloadIntent).toHaveBeenCalledWith("job-1"));
  });
});
