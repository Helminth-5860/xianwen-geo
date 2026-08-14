// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SubjectWebSources } from "./subject-web-sources";

const api = vi.hoisted(() => ({
  listWebSources: vi.fn(),
  importWebSource: vi.fn(),
  getWebSource: vi.fn(),
  confirmWebSource: vi.fn(),
}));

vi.mock("@/lib/web-sources-client", () => api);

const source = {
  id: "source-1",
  subject_id: "subject-1",
  display_url: "https://example.com/public",
  has_query: true,
  status: "succeeded",
  stable_error_code: "",
  version: 2,
  latest_version: { id: "parsed-1", version_no: 1, canonical_text: "Safe text" },
  current_confirmed_version: null,
  created_at: "2026-08-13T00:00:00Z",
  updated_at: "2026-08-13T00:00:00Z",
} as const;

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
  api.listWebSources.mockResolvedValue({ results: [] });
});

afterEach(cleanup);

describe("SubjectWebSources", () => {
  it("imports a URL without rendering raw HTML or query secrets", async () => {
    api.importWebSource.mockResolvedValue(source);
    api.listWebSources
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValue({ results: [source] });
    render(<SubjectWebSources subjectId="subject-1" />);
    await userEvent.type(
      screen.getByLabelText("公开网页地址"),
      "https://example.com/?token=secret",
    );
    await userEvent.click(screen.getByRole("button", { name: "导入网页" }));
    await screen.findByText("https://example.com/public");
    expect(screen.queryByText(/token=secret/)).toBeNull();
    expect(api.importWebSource).toHaveBeenCalledWith(
      "subject-1",
      "https://example.com/?token=secret",
    );
  });

  it("requires an explicit confirmation and never uses raw HTML rendering", async () => {
    api.listWebSources.mockResolvedValue({ results: [source] });
    api.confirmWebSource.mockResolvedValue({
      version: 3,
      confirmed_version: { id: "confirmed-1", version_no: 2 },
      created: true,
    });
    api.getWebSource.mockResolvedValue({
      ...source,
      version: 3,
      current_confirmed_version: { id: "confirmed-1", version_no: 2 },
    });
    render(<SubjectWebSources subjectId="subject-1" />);
    await userEvent.click(await screen.findByRole("button", { name: "查看并确认" }));
    fireEvent.change(screen.getByLabelText("确认网页文本"), {
      target: { value: "Reviewed text" },
    });
    await userEvent.click(screen.getByRole("button", { name: "确认网页文本" }));
    await waitFor(() =>
      expect(api.confirmWebSource).toHaveBeenCalledWith(source, "parsed-1", "Reviewed text"),
    );
    expect(document.querySelector("script")).toBeNull();
  });

  it("disables importing and confirming for archived subjects", async () => {
    api.listWebSources.mockResolvedValue({ results: [source] });
    render(<SubjectWebSources subjectId="subject-1" disabled />);
    expect(
      (await screen.findByRole("button", { name: "导入网页" })) as HTMLButtonElement,
    ).toHaveProperty("disabled", true);
    await userEvent.click(screen.getByRole("button", { name: "查看并确认" }));
    expect(
      screen.getByRole("button", { name: "确认网页文本" }) as HTMLButtonElement,
    ).toHaveProperty("disabled", true);
  });
});
