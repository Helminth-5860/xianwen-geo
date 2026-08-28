// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import SubjectVersionDetailPage from "../app/subjects/[id]/versions/[versionId]/page";
import SubjectVersionsPage from "../app/subjects/[id]/versions/page";
import type { SubjectVersionDetail } from "../lib/subjects-client";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "subject-1", versionId: "version-1" }),
}));

const getSubjectVersions = vi.fn();
const getSubjectVersion = vi.fn();

vi.mock("../lib/subjects-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/subjects-client")>("../lib/subjects-client");
  return {
    ...actual,
    getSubjectVersions: (...args: unknown[]) => getSubjectVersions(...args),
    getSubjectVersion: (...args: unknown[]) => getSubjectVersion(...args),
  };
});

const frozenVersion: SubjectVersionDetail = {
  id: "version-1",
  version_no: 1,
  official_name: "\u51bb\u7ed3\u4e3b\u4f53\u540d",
  created_at: "2026-08-11T10:00:00+08:00",
  schema_version: 2,
  field_values: { name: "\u51bb\u7ed3\u4e3b\u4f53\u540d", category: "old" },
  form_schema: {
    id: "type-1",
    key: "enterprise",
    name: "\u5386\u53f2\u7c7b\u578b\u540d",
    description: "\u5386\u53f2\u63cf\u8ff0",
    icon_key: "building",
    schema_version: 2,
    fields: [
      {
        field_key: "name",
        field_type: "text",
        scope: "common",
        label: "\u5386\u53f2\u6b63\u5f0f\u540d\u79f0",
        description: "",
        required: true,
        default_value: null,
        sort_order: 10,
        used_for_ai: true,
        name_role: "official_name",
        options: [],
      },
      {
        field_key: "category",
        field_type: "select",
        scope: "custom",
        label: "\u5386\u53f2\u7c7b\u522b",
        description: "",
        required: false,
        default_value: null,
        sort_order: 20,
        used_for_ai: false,
        name_role: "none",
        options: [
          { option_key: "old", label: "\u5386\u53f2\u9009\u9879\u6807\u7b7e", sort_order: 10 },
        ],
      },
    ],
  },
  names: [
    {
      role: "official_name",
      display_value: "\u51bb\u7ed3\u4e3b\u4f53\u540d",
      source_field_key: "name",
    },
  ],
  products: [],
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
  getSubjectVersions.mockResolvedValue({
    versions: [
      {
        id: frozenVersion.id,
        version_no: frozenVersion.version_no,
        official_name: frozenVersion.official_name,
        created_at: frozenVersion.created_at,
      },
    ],
  });
  getSubjectVersion.mockResolvedValue(frozenVersion);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("subject formal version history", () => {
  it("lists immutable formal versions", async () => {
    render(<SubjectVersionsPage />);
    expect(await screen.findByText("第 1 次保存 · 冻结主体名")).toBeTruthy();
    expect(screen.queryByText(/v1/i)).toBeNull();
    expect(getSubjectVersions).toHaveBeenCalledWith("subject-1");
  });

  it("renders values and option labels from the version frozen schema", async () => {
    render(<SubjectVersionDetailPage />);
    expect(await screen.findByText("\u5386\u53f2\u6b63\u5f0f\u540d\u79f0")).toBeTruthy();
    expect(screen.getByText("\u5386\u53f2\u9009\u9879\u6807\u7b7e")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "冻结主体名 · 第 1 次保存" })).toBeTruthy();
    expect(screen.getAllByText("主体名称").length).toBeGreaterThan(0);
    expect(
      screen.getByText("这里展示该次保存时的主体资料，之后的修改不会影响这份记录。"),
    ).toBeTruthy();
    expect(screen.queryByText(/digest|schema_snapshot|matching_value/i)).toBeNull();
    expect(screen.queryByText(/Schema|official_name|v1/i)).toBeNull();
    expect(getSubjectVersion).toHaveBeenCalledWith("subject-1", "version-1");
  });
});
