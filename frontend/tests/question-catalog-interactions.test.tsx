// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import AdminQuestionCategoriesPage from "../app/admin/question-categories/page";
import { AdminCapabilityContext } from "../components/admin/admin-capability";
import type { AdminContext } from "../lib/admin-rbac-client";
import type { QuestionCategory, QuestionTag } from "../lib/question-catalog-client";

const getAdminQuestionCategories = vi.fn();
const getAdminQuestionTags = vi.fn();
const createQuestionCategory = vi.fn();
const createQuestionTag = vi.fn();
const updateQuestionCategory = vi.fn();
const updateQuestionTag = vi.fn();
const changeQuestionCategoryStatus = vi.fn();
const changeQuestionTagStatus = vi.fn();
const getSubjectTypes = vi.fn();

vi.mock("../lib/question-catalog-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/question-catalog-client")>(
    "../lib/question-catalog-client",
  );
  return {
    ...actual,
    getAdminQuestionCategories: (...args: unknown[]) => getAdminQuestionCategories(...args),
    getAdminQuestionTags: (...args: unknown[]) => getAdminQuestionTags(...args),
    createQuestionCategory: (...args: unknown[]) => createQuestionCategory(...args),
    createQuestionTag: (...args: unknown[]) => createQuestionTag(...args),
    updateQuestionCategory: (...args: unknown[]) => updateQuestionCategory(...args),
    updateQuestionTag: (...args: unknown[]) => updateQuestionTag(...args),
    changeQuestionCategoryStatus: (...args: unknown[]) => changeQuestionCategoryStatus(...args),
    changeQuestionTagStatus: (...args: unknown[]) => changeQuestionTagStatus(...args),
  };
});

vi.mock("../lib/subjects-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/subjects-client")>("../lib/subjects-client");
  return { ...actual, getSubjectTypes: (...args: unknown[]) => getSubjectTypes(...args) };
});

const context: AdminContext = {
  id: "00000000-0000-0000-0000-000000000001",
  user_id: "00000000-0000-0000-0000-000000000002",
  nickname: "问题目录管理员",
  phone_masked: "+86 139****9000",
  is_superuser: false,
  admin_status: "active",
  version: 1,
  logout_version: 1,
  admin_version: 1,
  role: null,
  data_scope: "all",
  permission_keys: [
    "question_categories.list",
    "question_categories.create",
    "question_categories.update",
    "question_categories.disable",
    "question_tags.list",
    "question_tags.create",
    "question_tags.update",
    "question_tags.disable",
  ],
  menu_keys: ["menu.admin.question-categories"],
  commercial_identity: "ADMIN",
  tenant_id: null,
  tenant_name: null,
};

const category: QuestionCategory = {
  id: "category-1",
  key: "brand_awareness",
  name: "品牌认知",
  description: "品牌相关问题",
  generation_guidance: "围绕品牌认知生成",
  status: "active",
  sort_order: 10,
  is_builtin: true,
  version: 3,
  applicable_subject_type_ids: [],
  can_delete: false,
  created_at: "2026-08-16T00:00:00Z",
  updated_at: "2026-08-16T00:00:00Z",
};

const tag: QuestionTag = {
  id: "tag-1",
  key: "decision",
  name: "决策",
  description: "决策辅助标签",
  status: "inactive",
  sort_order: 20,
  is_builtin: false,
  version: 2,
  applicable_subject_type_ids: ["subject-type-1"],
  can_delete: false,
  created_at: "2026-08-16T00:00:00Z",
  updated_at: "2026-08-16T00:00:00Z",
};

const renderPage = (permissions = context.permission_keys) =>
  render(
    <AdminCapabilityContext.Provider value={{ ...context, permission_keys: permissions }}>
      <AdminQuestionCategoriesPage />
    </AdminCapabilityContext.Provider>,
  );

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
  getAdminQuestionCategories.mockResolvedValue([category]);
  getAdminQuestionTags.mockResolvedValue([tag]);
  getSubjectTypes.mockResolvedValue([
    {
      id: "subject-type-1",
      key: "enterprise",
      name: "企业",
      description: "",
      icon_key: "building",
      sort_order: 10,
      schema_version: 1,
    },
  ]);
  createQuestionCategory.mockResolvedValue(category);
  createQuestionTag.mockResolvedValue(tag);
  updateQuestionCategory.mockResolvedValue(category);
  updateQuestionTag.mockResolvedValue(tag);
  changeQuestionCategoryStatus.mockResolvedValue({ ...category, status: "inactive" });
  changeQuestionTagStatus.mockResolvedValue({ ...tag, status: "active" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("问题分类后台真实交互", () => {
  it("展示内置分类、适用主体和不可删除边界", async () => {
    renderPage();
    expect(await screen.findByText("brand_awareness")).toBeTruthy();
    expect(screen.getByText("全部主体")).toBeTruthy();
    expect(screen.getByText(/不提供删除/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "删除" })).toBeNull();

    await userEvent.click(screen.getByRole("tab", { name: "辅助标签" }));
    expect(await screen.findByText("decision")).toBeTruthy();
    expect(screen.getByText("企业")).toBeTruthy();
  });

  it("创建分类时提交稳定 key、生成说明和适用主体", async () => {
    renderPage();
    await screen.findByText("brand_awareness");
    await userEvent.type(screen.getByLabelText("稳定 key"), "service_process");
    await userEvent.type(screen.getByLabelText("名称"), "服务流程");
    await userEvent.type(screen.getByLabelText("生成提示说明"), "生成办理流程相关问题");
    await userEvent.click(screen.getByLabelText("适用主体"));
    await userEvent.click(await screen.findByText("企业"));
    await userEvent.click(screen.getByRole("button", { name: "创建分类" }));

    await waitFor(() =>
      expect(createQuestionCategory).toHaveBeenCalledWith(
        expect.objectContaining({
          key: "service_process",
          name: "服务流程",
          generation_guidance: "生成办理流程相关问题",
          applicable_subject_type_ids: ["subject-type-1"],
        }),
      ),
    );
  });

  it("编辑和启停均携带当前对象版本", async () => {
    renderPage();
    const row = (await screen.findByText("brand_awareness")).closest("tr");
    if (!row) throw new Error("missing category row");
    await userEvent.click(within(row).getByRole("button", { name: /编\s*辑/ }));
    const dialog = screen.getByRole("dialog");
    const name = within(dialog).getByDisplayValue("品牌认知");
    await userEvent.clear(name);
    await userEvent.type(name, "品牌认知度");
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }));
    await waitFor(() =>
      expect(updateQuestionCategory).toHaveBeenCalledWith(
        expect.objectContaining({ id: "category-1", version: 3 }),
        expect.objectContaining({ name: "品牌认知度" }),
      ),
    );

    await userEvent.click(within(row).getByRole("button", { name: /停\s*用/ }));
    await waitFor(() =>
      expect(changeQuestionCategoryStatus).toHaveBeenCalledWith(category, "disable"),
    );
  });

  it("无写能力时创建、编辑、启停控件均禁用", async () => {
    renderPage(["question_categories.list", "question_tags.list"]);
    const row = (await screen.findByText("brand_awareness")).closest("tr");
    if (!row) throw new Error("missing category row");
    expect(screen.getByRole("button", { name: "创建分类" })).toHaveProperty("disabled", true);
    expect(within(row).getByRole("button", { name: /编\s*辑/ })).toHaveProperty("disabled", true);
    expect(within(row).getByRole("button", { name: /停\s*用/ })).toHaveProperty("disabled", true);
  });
});
