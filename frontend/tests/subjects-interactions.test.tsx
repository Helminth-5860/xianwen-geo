// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import SubjectDetailPage from "../app/subjects/[id]/page";
import SubjectsPage from "../app/subjects/page";
import {
  isDistrictSelection,
  SubjectServiceAreaSelector,
} from "../components/subject-service-area-selector";
import type { SubjectDetail, SubjectList } from "../lib/subjects-client";

let viewMode = false;
const routerPush = vi.fn();
const routerReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "subject-1" }),
  useRouter: () => ({ push: routerPush, replace: routerReplace }),
  useSearchParams: () => new URLSearchParams(viewMode ? "mode=view" : ""),
}));

const getSubjectFormSchema = vi.fn();
const getSubjects = vi.fn();
const getSubject = vi.fn();
const getSubjectTypes = vi.fn();
const createSubject = vi.fn();
const saveSubject = vi.fn();
const deleteSubject = vi.fn();
const setCurrentSubject = vi.fn();

vi.mock("../lib/subjects-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/subjects-client")>("../lib/subjects-client");
  return {
    ...actual,
    getSubjectFormSchema: (...args: unknown[]) => getSubjectFormSchema(...args),
    getSubjects: (...args: unknown[]) => getSubjects(...args),
    getSubject: (...args: unknown[]) => getSubject(...args),
    getSubjectTypes: (...args: unknown[]) => getSubjectTypes(...args),
    createSubject: (...args: unknown[]) => createSubject(...args),
    saveSubject: (...args: unknown[]) => saveSubject(...args),
    deleteSubject: (...args: unknown[]) => deleteSubject(...args),
    setCurrentSubject: (...args: unknown[]) => setCurrentSubject(...args),
  };
});

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
  identity_bound: false,
  official_name: null,
  service_regions: JSON.stringify({ version: 1, nationwide: true, areas: [] }),
  retest_required: false,
  created_at: "2026-08-10T10:00:00+08:00",
  updated_at: "2026-08-10T10:00:00+08:00",
  schema_version: 2,
  draft_values: {
    name: "\u5386\u53f2\u540d\u79f0",
    stage: "startup",
    regions: ["east"],
    service_regions: JSON.stringify({ version: 1, nationwide: true, areas: [] }),
    logo: null,
  },
  business_profile: {
    legal_entity_type: "company",
    contact_name: "张三",
    contact_phone: "0755-12345678",
    business_address: JSON.stringify({
      version: 1,
      path: [
        { code: "440000", name: "广东省" },
        { code: "440300", name: "深圳市" },
        { code: "440305", name: "南山区" },
      ],
      detail: "示例路 1 号",
    }),
    industry: "企业服务",
    primary_business: "企业 GEO 咨询与内容服务",
    brand_name: "显问测试品牌",
    subject_aliases: "显问",
    unified_social_credit_code: "",
    social_channels: {
      douyin: "显问测试品牌",
      wechat_channels: "",
      wechat_official_account: "显问AI",
      xiaohongshu: "",
      kuaishou: "",
      ecommerce_urls: "",
      other_public_urls: "",
    },
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
        field_key: "service_regions",
        field_type: "textarea",
        scope: "common",
        label: "服务地区",
        description: "主体提供服务的地区",
        required: false,
        default_value: null,
        sort_order: 35,
        used_for_ai: true,
        name_role: "none",
        options: [],
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
  profile_completeness: {
    percentage: 78,
    core_completed: 7,
    core_total: 7,
    missing_core: [],
    suggestion: "建议补充官方网站，有助于提升主体识别与 GEO 分析质量。",
  },
  risk: { status: "not_assessed", review_id: null, public_reason: "" },
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
      service_regions: detail.service_regions,
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
  viewMode = false;
  getSubjects.mockResolvedValue(list);
  getSubject.mockResolvedValue(detail);
  getSubjectTypes.mockResolvedValue([
    {
      id: "type-1",
      key: "enterprise",
      name: "企业 / 公司",
      description: "依法设立的企业或公司主体",
      icon_key: "building",
      sort_order: 10,
      schema_version: 2,
    },
  ]);
  createSubject.mockResolvedValue(detail);
  saveSubject.mockResolvedValue({
    subject: {
      ...detail,
      version: 6,
      current_version_no: 1,
      identity_bound: true,
      draft_values: { ...detail.draft_values, name: "\u66f4\u65b0\u540d\u79f0" },
    },
    version: { version_no: 1 },
    version_created: true,
  });
  deleteSubject.mockResolvedValue({ ...detail, status: "archived" });
  setCurrentSubject.mockResolvedValue(list.context);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("subject profile interactions", () => {
  it("renders and edits an existing subject exclusively from its persisted form schema", async () => {
    render(<SubjectDetailPage />);
    const name = await screen.findByLabelText("主体名称");
    expect(screen.getByRole("heading", { name: "绑定主体" })).toBeTruthy();
    expect(screen.getByText("主体身份")).toBeTruthy();
    expect(screen.getByText("经营资料")).toBeTruthy();
    expect(screen.getByText("品牌与公开资料")).toBeTruthy();
    expect(getSubject).toHaveBeenCalledWith("subject-1");
    expect(getSubjectFormSchema).not.toHaveBeenCalled();

    await userEvent.clear(name);
    await userEvent.type(name, "\u66f4\u65b0\u540d\u79f0");
    await userEvent.click(screen.getByRole("button", { name: /绑\s*定\s*主\s*体/ }));
    expect(
      await screen.findByText(
        "主体身份绑定后不可自行修改，请确认信息准确。身份信息如需更正，请联系客服。",
      ),
    ).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /确\s*认\s*绑\s*定/ }));
    await waitFor(() =>
      expect(saveSubject).toHaveBeenCalledWith(
        detail,
        expect.objectContaining({
          name: "\u66f4\u65b0\u540d\u79f0",
          stage: "startup",
          regions: ["east"],
          service_regions: JSON.stringify({ version: 1, nationwide: true, areas: [] }),
        }),
        detail.business_profile,
      ),
    );
    expect(await screen.findByText("主体已成功绑定，资料已生效")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "提交正式版本" })).toBeNull();
  });

  it("saves the operating profile fields and re-renders the returned values", async () => {
    saveSubject.mockImplementationOnce(
      async (_subject, draftValues, profileValues: SubjectDetail["business_profile"]) => ({
        subject: {
          ...detail,
          version: 6,
          current_version_no: 1,
          draft_values: draftValues,
          business_profile: profileValues,
        },
        version: { version_no: 1 },
        version_created: true,
      }),
    );
    render(<SubjectDetailPage />);

    await userEvent.click(await screen.findByText("品牌与公开资料"));
    const contact = await screen.findByLabelText("联系人");
    await userEvent.clear(contact);
    await userEvent.type(contact, "李四");
    const xiaohongshu = screen.getByLabelText("小红书");
    await userEvent.type(xiaohongshu, "显问 GEO 主页");
    await userEvent.click(screen.getByRole("button", { name: /绑\s*定\s*主\s*体/ }));
    await userEvent.click(screen.getByRole("button", { name: /确\s*认\s*绑\s*定/ }));

    await waitFor(() =>
      expect(saveSubject).toHaveBeenCalledWith(
        detail,
        detail.draft_values,
        expect.objectContaining({
          contact_name: "李四",
          social_channels: expect.objectContaining({ xiaohongshu: "显问 GEO 主页" }),
        }),
      ),
    );
    expect(await screen.findByText("主体已成功绑定，资料已生效")).toBeTruthy();
    expect((screen.getByLabelText("联系人") as HTMLInputElement).value).toBe("李四");
    expect((screen.getByLabelText("小红书") as HTMLInputElement).value).toBe("显问 GEO 主页");
  });

  it("enables the private library and verified image-version selector", async () => {
    render(<SubjectDetailPage />);
    await screen.findByText("更多资料来源");
    await userEvent.click(screen.getByText("更多资料来源"));
    expect(await screen.findByText("主体资料库")).toBeTruthy();
    expect(screen.getByRole("button", { name: "上传资料" })).toBeTruthy();
  });
  it("does not expose list, delete, switch, or second-subject actions", async () => {
    render(<SubjectsPage />);
    await screen.findByRole("heading", { name: "主体管理" });
    expect(screen.getByRole("button", { name: "继续绑定主体" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /删除|切换|新增/ })).toBeNull();
    expect(deleteSubject).not.toHaveBeenCalled();
  });

  it("starts the one-time subject binding from the subject-management modal", async () => {
    getSubjects.mockResolvedValueOnce({ subjects: [], context: list.context });
    render(<SubjectsPage />);
    await screen.findByRole("heading", { name: "主体管理" });
    await userEvent.click(screen.getByRole("button", { name: "绑定主体" }));
    expect(await screen.findByRole("dialog", { name: "绑定主体" })).toBeTruthy();
    await userEvent.type(screen.getByLabelText("主体正式名称"), "广州显问网络科技有限公司");
    await userEvent.click(screen.getByRole("button", { name: /继续完善资料/ }));
    await waitFor(() =>
      expect(createSubject).toHaveBeenCalledWith("type-1", 2, {
        name: "广州显问网络科技有限公司",
      }),
    );
    expect(routerPush).toHaveBeenCalledWith("/subjects/subject-1");
  });

  it("keeps deleted subject values read-only", async () => {
    getSubject.mockResolvedValueOnce({ ...detail, status: "archived" });
    render(<SubjectDetailPage />);
    expect(await screen.findByText("历史记录")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /绑定主体|保存修改/ })).toBeNull();
    expect(screen.getByLabelText("主体名称") as HTMLInputElement).toHaveProperty("disabled", true);
    expect(screen.queryByRole("button", { name: "提交正式版本" })).toBeNull();
  });

  it("renders a complete read-only subject view without modification actions", async () => {
    viewMode = true;
    render(<SubjectDetailPage />);

    expect(await screen.findByRole("heading", { name: "查看主体档案" })).toBeTruthy();
    expect(screen.getByLabelText("主体名称") as HTMLInputElement).toHaveProperty("disabled", true);
    expect(screen.queryByRole("button", { name: /绑定主体|保存修改/ })).toBeNull();
    expect(screen.queryByText("AI 帮我补充资料")).toBeNull();
    expect(screen.getByRole("link", { name: "编辑主体" }).getAttribute("href")).toBe(
      "/subjects/subject-1",
    );
  });

  it("shows the field that caused a nested validation error", async () => {
    saveSubject.mockRejectedValueOnce(
      new (await import("../lib/auth-client")).AuthApiError(new Response(null, { status: 422 }), {
        success: false,
        error: {
          code: "VALIDATION_ERROR",
          message: "请求参数不正确",
          details: {
            fields: {
              profile_values: {
                contact_phone: [{ message: "该字符串格式不正确。", code: "invalid" }],
              },
            },
          },
        },
        request_id: "request-1",
      }),
    );
    render(<SubjectDetailPage />);
    await screen.findByLabelText("主体名称");
    await userEvent.click(screen.getByText("品牌与公开资料"));
    await userEvent.click(screen.getByRole("button", { name: /绑\s*定\s*主\s*体/ }));
    await userEvent.click(screen.getByRole("button", { name: /确\s*认\s*绑\s*定/ }));

    expect(
      await screen.findByText("联系电话格式不正确，请填写 5 至 32 位的手机号或座机号码"),
    ).toBeTruthy();
    expect(screen.queryByText("请求参数不正确")).toBeNull();
  });

  it("exposes one save action without draft or formal-version product steps", async () => {
    render(<SubjectDetailPage />);
    await screen.findByRole("button", { name: /绑\s*定\s*主\s*体/ });
    expect(screen.queryByText("草稿")).toBeNull();
    expect(screen.queryByText(/提交正式版本/)).toBeNull();
    expect(screen.queryByText("产品候选确认")).toBeNull();
  });
});
describe("subject risk public boundary", () => {
  it("shows the safe public rejection reason without administrator evidence", async () => {
    getSubject.mockResolvedValueOnce({
      ...detail,
      risk: {
        status: "rejected",
        review_id: "review-1",
        public_reason: "\u8bf7\u6838\u5bf9\u516c\u5f00\u4e3b\u4f53\u8d44\u6599",
      },
    });
    render(<SubjectDetailPage />);

    expect(
      await screen.findByText("\u8bf7\u6838\u5bf9\u516c\u5f00\u4e3b\u4f53\u8d44\u6599"),
    ).toBeTruthy();
    expect(screen.queryByText(/internal_note|review_evidence|test\.rule/)).toBeNull();
  });
});

describe("subject service area selector", () => {
  it("recognizes both ordinary and direct-municipality district paths", () => {
    expect(isDistrictSelection(["440000", "440100", "440106"])).toBe(true);
    expect(isDistrictSelection(["110000", "110101"])).toBe(true);
    expect(isDistrictSelection(["440000", "440100"])).toBe(false);
  });

  it("keeps code and name for multiple mainland area levels and supports nationwide", async () => {
    const onChange = vi.fn();
    render(
      <SubjectServiceAreaSelector
        disabled={false}
        value={JSON.stringify({
          version: 1,
          nationwide: false,
          areas: [
            {
              code: "440305",
              name: "南山区",
              level: "district",
              path: [
                { code: "440000", name: "广东省" },
                { code: "440300", name: "深圳市" },
                { code: "440305", name: "南山区" },
              ],
            },
          ],
        })}
        onChange={onChange}
      />,
    );

    expect(screen.getByText("广东省 / 深圳市 / 南山区")).toBeTruthy();
    await userEvent.click(screen.getByRole("checkbox", { name: "支持全国" }));
    expect(JSON.parse(onChange.mock.calls[0][0])).toEqual({
      version: 1,
      nationwide: true,
      areas: [],
    });
  });
});
