// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { CustomLibraryWorkspace } from "../components/custom-library-workspace";
import { VideoLibraryWorkspace } from "../components/video-library-workspace";

const getSubjectDocuments = vi.hoisted(() => vi.fn());

vi.mock("../lib/documents-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/documents-client")>("../lib/documents-client");
  return {
    ...actual,
    getSubjectDocuments: (...args: unknown[]) => getSubjectDocuments(...args),
  };
});

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
  getSubjectDocuments.mockResolvedValue({ documents: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("主体资产库页面", () => {
  it("视频库提供清晰空状态和下一步操作", () => {
    render(<VideoLibraryWorkspace subjectId="subject-1" />);

    expect(screen.getByRole("heading", { name: "视频库" })).toBeTruthy();
    expect(screen.getByText("如何开始")).toBeTruthy();
    expect(screen.getByText("当前主体还没有视频内容，可先生成视频脚本开始创作。")).toBeTruthy();
    expect(screen.getByRole("link", { name: "生成视频脚本" }).getAttribute("href")).toBe(
      "/subjects/subject-1/video-scripts/new",
    );
    expect(screen.queryByText(/数据接口|后端/)).toBeNull();
    expect(screen.queryByRole("listitem")).toBeNull();
  });

  it("自定义库复用当前主体的私有文件上传和资料列表", async () => {
    render(<CustomLibraryWorkspace subjectId="subject-1" />);

    expect(screen.getByRole("heading", { name: "自定义库" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "上传资料" })).toBeTruthy();
    expect(getSubjectDocuments).toHaveBeenCalledWith("subject-1");
    expect(screen.getByText("还没有已确认的文件，上传并确认内容后会显示在这里。")).toBeTruthy();
  });
});
