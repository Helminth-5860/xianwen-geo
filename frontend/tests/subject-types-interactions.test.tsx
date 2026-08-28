// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import AdminSubjectTypeDetailPage from "../app/admin/subject-types/[id]/page";
import AdminSubjectTypesPage from "../app/admin/subject-types/page";
import { AdminCapabilityContext } from "../components/admin/admin-capability";
import type { AdminContext } from "../lib/admin-rbac-client";
import type { SubjectFieldConfig, SubjectType } from "../lib/subjects-client";

const routeParams = { id: "type-1" };
vi.mock("next/navigation", () => ({ useParams: () => routeParams }));

const getAdminSubjectTypes = vi.fn();
const createSubjectType = vi.fn();
const getAdminSubjectType = vi.fn();
const updateSubjectType = vi.fn();
const changeSubjectTypeStatus = vi.fn();
const createSubjectField = vi.fn();
const updateSubjectField = vi.fn();
const createSubjectFieldOption = vi.fn();
const updateSubjectFieldOption = vi.fn();
const reorderSubjectFields = vi.fn();

vi.mock("../lib/subjects-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/subjects-client")>("../lib/subjects-client");
  return {
    ...actual,
    getAdminSubjectTypes: (...args: unknown[]) => getAdminSubjectTypes(...args),
    createSubjectType: (...args: unknown[]) => createSubjectType(...args),
    getAdminSubjectType: (...args: unknown[]) => getAdminSubjectType(...args),
    updateSubjectType: (...args: unknown[]) => updateSubjectType(...args),
    changeSubjectTypeStatus: (...args: unknown[]) => changeSubjectTypeStatus(...args),
    createSubjectField: (...args: unknown[]) => createSubjectField(...args),
    updateSubjectField: (...args: unknown[]) => updateSubjectField(...args),
    createSubjectFieldOption: (...args: unknown[]) => createSubjectFieldOption(...args),
    updateSubjectFieldOption: (...args: unknown[]) => updateSubjectFieldOption(...args),
    reorderSubjectFields: (...args: unknown[]) => reorderSubjectFields(...args),
  };
});

const context: AdminContext = {
  id: "00000000-0000-0000-0000-000000000001",
  user_id: "00000000-0000-0000-0000-000000000002",
  nickname: "主体目录管理员",
  phone_masked: "+86 139****9000",
  is_superuser: false,
  admin_status: "active",
  version: 1,
  logout_version: 1,
  admin_version: 1,
  role: null,
  data_scope: "all",
  permission_keys: [
    "subject_types.list",
    "subject_types.view",
    "subject_types.create",
    "subject_types.update",
    "subject_types.disable",
    "subject_fields.list",
    "subject_fields.create",
    "subject_fields.update",
  ],
  menu_keys: ["menu.admin.subject-types"],
  commercial_identity: "ADMIN",
  tenant_id: null,
  tenant_name: null,
};

const fields: SubjectFieldConfig[] = [
  {
    id: "field-name",
    field_key: "name",
    field_type: "text",
    scope: "common",
    is_builtin: true,
    label: "主体名称",
    description: "正式名称",
    required: true,
    default_value: null,
    sort_order: 10,
    enabled: true,
    used_for_ai: true,
    name_role: "official_name",
    version: 2,
    options: [],
  },
  {
    id: "field-stage",
    field_key: "business_stage",
    field_type: "select",
    scope: "custom",
    is_builtin: false,
    label: "发展阶段",
    description: "",
    required: false,
    default_value: null,
    sort_order: 20,
    enabled: true,
    used_for_ai: false,
    name_role: "none",
    version: 3,
    options: [
      {
        id: "option-startup",
        option_key: "startup",
        label: "初创",
        enabled: true,
        sort_order: 10,
        version: 1,
      },
    ],
  },
  {
    id: "field-logo",
    field_key: "logo",
    field_type: "image",
    scope: "custom",
    is_builtin: false,
    label: "品牌图片",
    description: "",
    required: false,
    default_value: null,
    sort_order: 30,
    enabled: false,
    used_for_ai: false,
    name_role: "none",
    version: 1,
    options: [],
  },
];

const subjectType: SubjectType & { fields: SubjectFieldConfig[] } = {
  id: "type-1",
  key: "enterprise",
  name: "企业",
  description: "企业主体",
  icon_key: "building",
  status: "active",
  sort_order: 10,
  is_builtin: true,
  schema_version: 7,
  version: 4,
  fields,
};

const renderWithCapabilities = (node: React.ReactNode, permissions = context.permission_keys) =>
  render(
    <AdminCapabilityContext.Provider value={{ ...context, permission_keys: permissions }}>
      {node}
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
  getAdminSubjectTypes.mockResolvedValue([subjectType]);
  getAdminSubjectType.mockResolvedValue(subjectType);
  createSubjectType.mockResolvedValue(subjectType);
  createSubjectField.mockResolvedValue(fields[1]);
  updateSubjectType.mockResolvedValue(subjectType);
  changeSubjectTypeStatus.mockResolvedValue(subjectType);
  updateSubjectField.mockResolvedValue(fields[1]);
  createSubjectFieldOption.mockResolvedValue(fields[1].options[0]);
  updateSubjectFieldOption.mockResolvedValue(fields[1].options[0]);
  reorderSubjectFields.mockResolvedValue(subjectType);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("主体类型与动态字段真实交互", () => {
  it("创建类型时提交纯文本目录信息，并由服务端自动配置公共字段", async () => {
    renderWithCapabilities(<AdminSubjectTypesPage />);
    expect(await screen.findByText("enterprise")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("稳定类型 key"), "exhibition");
    await userEvent.type(screen.getByLabelText("类型名称"), "展会");
    await userEvent.type(screen.getByLabelText("纯文本说明"), "展览活动主体");
    await userEvent.click(screen.getByRole("button", { name: "创建并配置公共字段" }));
    await waitFor(() =>
      expect(createSubjectType).toHaveBeenCalledWith(
        expect.objectContaining({
          key: "exhibition",
          name: "展会",
          description: "展览活动主体",
          icon_key: "subject",
        }),
      ),
    );
    expect(screen.queryByText(/HTML/)).toBeNull();
  });

  it("自定义字段类型仅在创建时选择，编辑区不存在字段类型切换", async () => {
    renderWithCapabilities(<AdminSubjectTypeDetailPage />);
    expect(await screen.findByText("字段类型（仅创建时选择）")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("字段 key"), "founded_date");
    await userEvent.click(screen.getByLabelText("字段类型（仅创建时选择）"));
    await userEvent.click(await screen.findByText("日期"));
    await userEvent.type(screen.getByLabelText("字段名称"), "成立日期");
    await userEvent.click(screen.getByRole("button", { name: "创建字段" }));
    await waitFor(() =>
      expect(createSubjectField).toHaveBeenCalledWith(
        "type-1",
        7,
        expect.objectContaining({
          field_key: "founded_date",
          field_type: "date",
          label: "成立日期",
          enabled: false,
        }),
      ),
    );
    expect(screen.queryByRole("button", { name: "切换字段类型" })).toBeNull();
    expect(screen.queryByRole("button", { name: "删除字段" })).toBeNull();
  });

  it("字段配置提交 schema/object 双版本，排序提交完整排列", async () => {
    renderWithCapabilities(<AdminSubjectTypeDetailPage />);
    const ai = await screen.findAllByRole("checkbox", { name: "用于 AI" });
    await userEvent.click(ai[1]);
    await waitFor(() =>
      expect(updateSubjectField).toHaveBeenCalledWith(fields[1], 7, { used_for_ai: true }),
    );

    await userEvent.click(screen.getByLabelText("上移 business_stage"));
    await userEvent.click(screen.getByRole("button", { name: "保存完整字段顺序" }));
    await waitFor(() =>
      expect(reorderSubjectFields).toHaveBeenCalledWith(
        "type-1",
        7,
        expect.arrayContaining([
          expect.objectContaining({ id: "field-name", version: 2 }),
          expect.objectContaining({ id: "field-stage", version: 3 }),
          expect.objectContaining({ id: "field-logo", version: 1 }),
        ]),
      ),
    );
  });

  it("选项使用稳定 option_key，图片字段明确不提供上传能力", async () => {
    renderWithCapabilities(<AdminSubjectTypeDetailPage />);
    expect(await screen.findByText("仅声明 Schema，上传能力尚未启用")).toBeTruthy();
    expect(screen.queryByText(/上传文件|选择文件/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "添加稳定选项" }));
    await userEvent.type(screen.getByLabelText("稳定 option key"), "growth");
    await userEvent.type(screen.getByLabelText("选项纯文本名称"), "成长");
    await userEvent.click(screen.getByRole("button", { name: "添加选项" }));
    await waitFor(() =>
      expect(createSubjectFieldOption).toHaveBeenCalledWith(fields[1], 7, {
        option_key: "growth",
        label: "成长",
      }),
    );
  });

  it("没有 capability 时全部写控件不可用，前端不替代后端授权", async () => {
    renderWithCapabilities(<AdminSubjectTypeDetailPage />, ["subject_types.view"]);
    expect(
      (await screen.findByRole("button", { name: "保存展示信息" })) as HTMLButtonElement,
    ).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "创建字段" }) as HTMLButtonElement).toHaveProperty(
      "disabled",
      true,
    );
    expect(
      screen.getByRole("button", { name: "保存完整字段顺序" }) as HTMLButtonElement,
    ).toHaveProperty("disabled", true);
    expect(
      screen.getByRole("button", { name: "停用主体类型" }) as HTMLButtonElement,
    ).toHaveProperty("disabled", true);
  });

  it("403 或版本冲突显示中文错误且不写入浏览器存储", async () => {
    updateSubjectField.mockRejectedValueOnce(new Error("Schema 已更新，请刷新后重试"));
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    renderWithCapabilities(<AdminSubjectTypeDetailPage />);
    const required = await screen.findAllByRole("checkbox", { name: "必填" });
    await userEvent.click(required[1]);
    expect(await screen.findByText("当前操作未能完成，请稍后重新尝试。")).toBeTruthy();
    expect(screen.queryByText("Schema 已更新，请刷新后重试")).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(consoleSpy.mock.calls.flat().join(" ")).not.toContain("13900139000");
    consoleSpy.mockRestore();
  });
});
