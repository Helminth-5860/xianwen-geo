// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import SubjectDetailPage from "../app/subjects/[id]/page";
import SubjectsPage from "../app/subjects/page";
import type { SubjectDetail, SubjectList, SubjectType } from "../lib/subjects-client";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "subject-1" }) }));

const getSubjectTypes = vi.fn();
const getSubjectFormSchema = vi.fn();
const getSubjects = vi.fn();
const createSubject = vi.fn();
const getSubject = vi.fn();
const updateSubjectDraft = vi.fn();
const archiveSubject = vi.fn();
const activateSubject = vi.fn();
const setCurrentSubject = vi.fn();
const commitSubject = vi.fn();

vi.mock("../lib/subjects-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/subjects-client")>("../lib/subjects-client");
  return {
    ...actual,
    getSubjectTypes: (...args: unknown[]) => getSubjectTypes(...args),
    getSubjectFormSchema: (...args: unknown[]) => getSubjectFormSchema(...args),
    getSubjects: (...args: unknown[]) => getSubjects(...args),
    createSubject: (...args: unknown[]) => createSubject(...args),
    getSubject: (...args: unknown[]) => getSubject(...args),
    updateSubjectDraft: (...args: unknown[]) => updateSubjectDraft(...args),
    archiveSubject: (...args: unknown[]) => archiveSubject(...args),
    activateSubject: (...args: unknown[]) => activateSubject(...args),
    setCurrentSubject: (...args: unknown[]) => setCurrentSubject(...args),
    commitSubject: (...args: unknown[]) => commitSubject(...args),
  };
});

const subjectType: SubjectType = {
  id: "type-1",
  key: "enterprise",
  name: "\u4f01\u4e1a",
  description: "\u5f53\u524d\u76ee\u5f55\u63cf\u8ff0",
  icon_key: "building",
  status: "active",
  sort_order: 10,
  schema_version: 9,
  version: 3,
};

const detail: SubjectDetail = {
  id: "subject-1",
  subject_type: {
    id: "type-1",
    key: "enterprise",
    name: "\u521b\u5efa\u65f6\u4f01\u4e1a",
    icon_key: "building",
  },
  status: "draft",
  version: 4,
  is_current: true,
  current_version_no: null,
  official_name: null,
  retest_required: false,
  created_at: "2026-08-10T10:00:00+08:00",
  updated_at: "2026-08-10T10:00:00+08:00",
  schema_version: 2,
  draft_values: {
    name: "\u5386\u53f2\u540d\u79f0",
    stage: "startup",
    regions: ["east"],
    logo: null,
  },
  form_schema: {
    id: "type-1",
    key: "enterprise",
    name: "\u521b\u5efa\u65f6\u4f01\u4e1a",
    description: "\u6301\u4e45\u5316\u5feb\u7167\u63cf\u8ff0",
    icon_key: "building",
    schema_version: 2,
    fields: [
      {
        field_key: "name",
        field_type: "text",
        scope: "common",
        label: "\u5386\u53f2\u4e3b\u4f53\u540d\u79f0",
        description: "",
        required: true,
        default_value: null,
        sort_order: 10,
        used_for_ai: true,
        name_role: "official_name",
        options: [],
      },
      {
        field_key: "stage",
        field_type: "select",
        scope: "custom",
        label: "\u5386\u53f2\u53d1\u5c55\u9636\u6bb5",
        description: "",
        required: false,
        default_value: null,
        sort_order: 20,
        used_for_ai: false,
        name_role: "none",
        options: [{ option_key: "startup", label: "\u521d\u521b", sort_order: 10 }],
      },
      {
        field_key: "regions",
        field_type: "multi",
        scope: "custom",
        label: "\u670d\u52a1\u5730\u533a",
        description: "",
        required: false,
        default_value: [],
        sort_order: 30,
        used_for_ai: false,
        name_role: "product",
        options: [{ option_key: "east", label: "\u534e\u4e1c", sort_order: 10 }],
      },
      {
        field_key: "logo",
        field_type: "image",
        scope: "custom",
        label: "\u54c1\u724c\u56fe\u7247",
        description: "",
        required: false,
        default_value: null,
        sort_order: 40,
        used_for_ai: false,
        name_role: "none",
        options: [],
      },
    ],
  },
  product_candidates: [
    { candidate_key: "a".repeat(64), display_value: "\u534e\u4e1c", source_field_key: "regions" },
  ],
  has_uncommitted_changes: true,
  risk: { status: "not_assessed", review_id: null },
};

const list: SubjectList = {
  subjects: [
    {
      id: detail.id,
      subject_type: detail.subject_type,
      status: detail.status,
      version: detail.version,
      is_current: detail.is_current,
      created_at: detail.created_at,
      current_version_no: detail.current_version_no,
      official_name: detail.official_name,
      retest_required: detail.retest_required,
      updated_at: detail.updated_at,
    },
  ],
  context: { current_subject_id: detail.id, version: 2 },
};

beforeAll(() => {
  const nativeGetComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
    nativeGetComputedStyle(element),
  );
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
  getSubjectTypes.mockResolvedValue([subjectType]);
  getSubjects.mockResolvedValue(list);
  getSubject.mockResolvedValue(detail);
  createSubject.mockResolvedValue(detail);
  updateSubjectDraft.mockResolvedValue({
    ...detail,
    version: 5,
    draft_values: { ...detail.draft_values, name: "\u66f4\u65b0\u540d\u79f0" },
  });
  archiveSubject.mockResolvedValue({ ...detail, status: "archived" });
  activateSubject.mockResolvedValue({ ...detail, status: "active" });
  setCurrentSubject.mockResolvedValue(list.context);
  commitSubject.mockResolvedValue({
    subject: {
      ...detail,
      version: 5,
      current_version_no: 1,
      official_name: "\u5386\u53f2\u540d\u79f0",
      has_uncommitted_changes: false,
    },
    version: {
      id: "version-1",
      version_no: 1,
      official_name: "\u5386\u53f2\u540d\u79f0",
      created_at: "2026-08-11T10:00:00+08:00",
      schema_version: 2,
      field_values: detail.draft_values,
      form_schema: detail.form_schema,
      names: [],
      products: [],
    },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("subject draft interactions", () => {
  it("renders and edits an existing subject exclusively from its persisted form schema", async () => {
    render(<SubjectDetailPage />);
    const name = await screen.findByLabelText("\u5386\u53f2\u4e3b\u4f53\u540d\u79f0");
    expect(screen.getByText("\u6301\u4e45\u5316\u5feb\u7167\u63cf\u8ff0")).toBeTruthy();
    expect(screen.getByText(/Schema v2/)).toBeTruthy();
    expect(getSubject).toHaveBeenCalledWith("subject-1");
    expect(getSubjectFormSchema).not.toHaveBeenCalled();

    await userEvent.clear(name);
    await userEvent.type(name, "\u66f4\u65b0\u540d\u79f0");
    await userEvent.click(screen.getByRole("button", { name: "\u4fdd\u5b58\u8349\u7a3f" }));
    await waitFor(() =>
      expect(updateSubjectDraft).toHaveBeenCalledWith(
        detail,
        expect.objectContaining({
          name: "\u66f4\u65b0\u540d\u79f0",
          stage: "startup",
          regions: ["east"],
        }),
      ),
    );
  });

  it("shows image fields as schema-only and never renders an upload control", async () => {
    render(<SubjectDetailPage />);
    expect(
      await screen.findByText("\u4e0a\u4f20\u80fd\u529b\u5c1a\u672a\u542f\u7528"),
    ).toBeTruthy();
    expect(screen.queryByText(/\u9009\u62e9\u6587\u4ef6|\u4e0a\u4f20\u6587\u4ef6/)).toBeNull();
  });

  it("creates a draft with the selected type and current schema version", async () => {
    render(<SubjectsPage />);
    await screen.findByText("\u521b\u5efa\u65f6\u4f01\u4e1a");
    await userEvent.click(screen.getByLabelText("\u4e3b\u4f53\u7c7b\u578b"));
    await userEvent.click(await screen.findByText("\u4f01\u4e1a"));
    await userEvent.click(screen.getByRole("button", { name: "\u521b\u5efa\u8349\u7a3f" }));
    await waitFor(() => expect(createSubject).toHaveBeenCalledWith("type-1", 9));
  });

  it("keeps archived subject values read-only and surfaces stable API errors", async () => {
    getSubject.mockResolvedValueOnce({ ...detail, status: "archived" });
    render(<SubjectDetailPage />);
    expect(
      (await screen.findByRole("button", {
        name: "\u4fdd\u5b58\u8349\u7a3f",
      })) as HTMLButtonElement,
    ).toHaveProperty("disabled", true);
    expect(
      screen.getByLabelText("\u5386\u53f2\u4e3b\u4f53\u540d\u79f0") as HTMLInputElement,
    ).toHaveProperty("disabled", true);
    expect(
      screen.getByRole("button", {
        name: "\u63d0\u4ea4\u6b63\u5f0f\u7248\u672c",
      }) as HTMLButtonElement,
    ).toHaveProperty("disabled", true);
  });

  it("submits only server candidates and explicit product confirmations", async () => {
    render(<SubjectDetailPage />);
    await screen.findByText("\u4ea7\u54c1\u5019\u9009\u786e\u8ba4");
    const mention = screen.getByLabelText(
      "\u534e\u4e1c\u52a0\u5165\u63d0\u53ca\u8bcd",
    ) as HTMLInputElement;
    expect(mention.disabled).toBe(true);
    await userEvent.click(
      screen.getByLabelText("\u534e\u4e1c\u552f\u4e00\u6027\u5df2\u786e\u8ba4"),
    );
    expect(mention.disabled).toBe(false);
    await userEvent.click(mention);
    await userEvent.click(
      screen.getByRole("button", { name: "\u63d0\u4ea4\u6b63\u5f0f\u7248\u672c" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "\u786e\u8ba4\u63d0\u4ea4" }));
    await waitFor(() =>
      expect(commitSubject).toHaveBeenCalledWith(detail, [
        {
          candidate_key: "a".repeat(64),
          uniqueness_confirmed: true,
          include_in_mention: true,
        },
      ]),
    );
    expect(await screen.findByText("\u6b63\u5f0f\u7248\u672c v1 \u5df2\u63d0\u4ea4")).toBeTruthy();
  });

  it("requires local draft edits to be saved before formal commit", async () => {
    render(<SubjectDetailPage />);
    const name = await screen.findByLabelText("\u5386\u53f2\u4e3b\u4f53\u540d\u79f0");
    await userEvent.clear(name);
    await userEvent.type(name, "\u672a\u4fdd\u5b58\u540d\u79f0");
    await userEvent.click(
      screen.getByRole("button", { name: "\u63d0\u4ea4\u6b63\u5f0f\u7248\u672c" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "\u786e\u8ba4\u63d0\u4ea4" }));
    expect(
      await screen.findByText(
        "\u8bf7\u5148\u4fdd\u5b58\u8349\u7a3f\uff0c\u518d\u63d0\u4ea4\u6b63\u5f0f\u7248\u672c",
      ),
    ).toBeTruthy();
    expect(commitSubject).not.toHaveBeenCalled();
  });
});
