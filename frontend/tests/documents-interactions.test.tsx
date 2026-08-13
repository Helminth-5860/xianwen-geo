// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SubjectDocuments } from "../components/subject-documents";

const createUploadIntent = vi.fn();
const uploadDirect = vi.fn();
const completeUploadIntent = vi.fn();
const getUploadIntent = vi.fn();
const getSubjectDocuments = vi.fn();
const openDocumentDownload = vi.fn();
const requestDocumentParse = vi.fn();
const getDocumentParseResult = vi.fn();
const confirmDocumentParse = vi.fn();

vi.mock("../lib/documents-client", () => ({
  createUploadIntent: (...args: unknown[]) => createUploadIntent(...args),
  uploadDirect: (...args: unknown[]) => uploadDirect(...args),
  completeUploadIntent: (...args: unknown[]) => completeUploadIntent(...args),
  getUploadIntent: (...args: unknown[]) => getUploadIntent(...args),
  getSubjectDocuments: (...args: unknown[]) => getSubjectDocuments(...args),
  openDocumentDownload: (...args: unknown[]) => openDocumentDownload(...args),
  newUploadIdempotencyKey: () => "browser-random-key",
  requestDocumentParse: (...args: unknown[]) => requestDocumentParse(...args),
  getDocumentParseResult: (...args: unknown[]) => getDocumentParseResult(...args),
  confirmDocumentParse: (...args: unknown[]) => confirmDocumentParse(...args),
  newParseIdempotencyKey: () => "browser-parse-random-key",
}));

const document = {
  id: "document-1",
  document_version_id: "version-1",
  display_name: "安全资料.pdf",
  detected_file_kind: "pdf",
  size_bytes: 12,
  safe_status: "clean" as const,
  download_available: true,
  created_at: "2026-08-11T10:00:00+08:00",
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
  getSubjectDocuments.mockResolvedValue({ documents: [] });
  openDocumentDownload.mockResolvedValue(undefined);
  getDocumentParseResult.mockReset();
  confirmDocumentParse.mockResolvedValue(undefined);
});

afterEach(cleanup);

describe("private Subject document interactions", () => {
  it("uploads directly, accepts 202 verifying, polls, and refreshes without persisting credentials", async () => {
    createUploadIntent.mockResolvedValue({
      intent: { id: "intent-1", version: 1, status: "pending_upload" },
      upload: { method: "POST", url: "https://opaque.invalid", fields: { key: "opaque" } },
    });
    uploadDirect.mockImplementation(async (_credential, _file, progress) => progress(100));
    completeUploadIntent.mockResolvedValue({ id: "intent-1", version: 2, status: "verifying" });
    getUploadIntent.mockResolvedValue({ id: "intent-1", version: 3, status: "completed" });
    getSubjectDocuments
      .mockResolvedValueOnce({ documents: [] })
      .mockResolvedValueOnce({ documents: [document] });
    render(<SubjectDocuments subjectId="subject-1" />);
    const input = documentRoot().querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["safe-content"], "资料.pdf", { type: "application/pdf" })] },
    });
    expect(await screen.findByText("文件正在进行安全验证")).toBeTruthy();
    expect(await screen.findByText("安全资料.pdf")).toBeTruthy();
    expect(createUploadIntent).toHaveBeenCalledWith(
      "subject-1",
      expect.any(File),
      "browser-random-key",
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("creates a private download intent only after a user interaction", async () => {
    getSubjectDocuments.mockResolvedValue({ documents: [document] });
    render(<SubjectDocuments subjectId="subject-1" />);
    await userEvent.click(await screen.findByRole("button", { name: "私密下载" }));
    expect(openDocumentDownload).toHaveBeenCalledWith("document-1");
  });

  it("parses, shows machine-only warnings, and confirms only canonical text", async () => {
    const result = {
      status: "succeeded",
      stable_error_code: "",
      state_version: 2,
      latest_version: { id: "parsed-1", version_no: 1 },
      current_confirmed_version: null,
      canonical_text: "machine text",
      tables: [[["cell"]]],
      warning_codes: ["NO_TEXT_EXTRACTED"],
      confirmed: false,
      parser: { key: "pdf", version: "1", ocr_engine_version: "" },
    };
    getSubjectDocuments.mockResolvedValue({ documents: [document] });
    requestDocumentParse.mockResolvedValue({ id: "job-1", status: "queued" });
    getDocumentParseResult.mockResolvedValue(result);
    confirmDocumentParse.mockResolvedValue({
      parse_state_version: 3,
      confirmed_version: { id: "parsed-2", version_no: 2 },
      created: true,
    });
    render(<SubjectDocuments subjectId="subject-1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: "\u89e3\u6790\u4e0e\u786e\u8ba4" }),
    );
    const editor = await screen.findByRole("textbox", {
      name: "\u786e\u8ba4\u89e3\u6790\u6587\u672c",
    });
    expect(screen.getByText(/NO_TEXT_EXTRACTED/)).toBeTruthy();
    await userEvent.clear(editor);
    await userEvent.type(editor, "confirmed text");
    await userEvent.click(
      screen.getByRole("button", { name: "\u786e\u8ba4\u89e3\u6790\u6587\u672c" }),
    );
    expect(requestDocumentParse).toHaveBeenCalledWith(document, "browser-parse-random-key");
    expect(confirmDocumentParse).toHaveBeenCalledWith("document-1", result, "confirmed text");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});

function documentRoot() {
  return globalThis.document;
}
