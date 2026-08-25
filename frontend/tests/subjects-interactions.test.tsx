// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import SubjectDetailPage from "../app/subjects/[id]/page";
import SubjectsPage from "../app/subjects/page";
import {
  SubjectServiceAreaSelector,
  townOptionsForDistrict,
} from "../components/subject-service-area-selector";
import type { SubjectDetail, SubjectList, SubjectType } from "../lib/subjects-client";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "subject-1" }) }));

const getSubjectTypes = vi.fn();
const getSubjectFormSchema = vi.fn();
const getSubjects = vi.fn();
const createSubject = vi.fn();
const getSubject = vi.fn();
const saveSubject = vi.fn();
const archiveSubject = vi.fn();
const activateSubject = vi.fn();
const setCurrentSubject = vi.fn();

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
    saveSubject: (...args: unknown[]) => saveSubject(...args),
    archiveSubject: (...args: unknown[]) => archiveSubject(...args),
    activateSubject: (...args: unknown[]) => activateSubject(...args),
    setCurrentSubject: (...args: unknown[]) => setCurrentSubject(...args),
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
    service_regions: JSON.stringify({ version: 1, nationwide: true, areas: [] }),
    logo: null,
  },
  business_profile: {
    legal_entity_type: "company",
    contact_name: "张三",
    contact_phone: "0755-12345678",
    business_address: "广东省深圳市南山区示例路 1 号",
    primary_business: "企业 GEO 咨询与内容服务",
    brand_name: "显问测试品牌",
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
  saveSubject.mockResolvedValue({
    subject: {
      ...detail,
      version: 6,
      current_version_no: 1,
      draft_values: { ...detail.draft_values, name: "\u66f4\u65b0\u540d\u79f0" },
    },
    version: { version_no: 1 },
    version_created: true,
  });
  archiveSubject.mockResolvedValue({ ...detail, status: "archived" });
  activateSubject.mockResolvedValue({ ...detail, status: "active" });
  setCurrentSubject.mockResolvedValue(list.context);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("subject profile interactions", () => {
  it("renders and edits an existing subject exclusively from its persisted form schema", async () => {
    render(<SubjectDetailPage />);
    const name = await screen.findByLabelText("营业执照主体名称");
    expect(screen.getByRole("heading", { name: "完善企业经营资料" })).toBeTruthy();
    expect(screen.getByText("基础身份信息")).toBeTruthy();
    expect(screen.getByText("经营信息")).toBeTruthy();
    expect(screen.getByText("品牌与公开资料")).toBeTruthy();
    expect(getSubject).toHaveBeenCalledWith("subject-1");
    expect(getSubjectFormSchema).not.toHaveBeenCalled();

    await userEvent.clear(name);
    await userEvent.type(name, "\u66f4\u65b0\u540d\u79f0");
    await userEvent.click(screen.getByRole("button", { name: "保存资料" }));
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
    expect(await screen.findByText("保存成功，资料已生效")).toBeTruthy();
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

    const contact = await screen.findByLabelText("联系人");
    await userEvent.clear(contact);
    await userEvent.type(contact, "李四");
    const xiaohongshu = screen.getByLabelText("小红书");
    await userEvent.type(xiaohongshu, "显问 GEO 主页");
    await userEvent.click(screen.getByRole("button", { name: "保存资料" }));

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
    expect(await screen.findByText("保存成功，资料已生效")).toBeTruthy();
    expect((screen.getByLabelText("联系人") as HTMLInputElement).value).toBe("李四");
    expect((screen.getByLabelText("小红书") as HTMLInputElement).value).toBe("显问 GEO 主页");
  });

  it("enables the private library and verified image-version selector", async () => {
    render(<SubjectDetailPage />);
    await screen.findByText("更多资料来源（选填）");
    await userEvent.click(screen.getByText("更多资料来源（选填）"));
    expect(await screen.findByText("主体资料库")).toBeTruthy();
    expect(screen.getByRole("button", { name: "上传资料" })).toBeTruthy();
    expect(screen.getByLabelText("品牌图片")).toBeTruthy();
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
        name: "保存资料",
      })) as HTMLButtonElement,
    ).toHaveProperty("disabled", true);
    expect(screen.getByLabelText("营业执照主体名称") as HTMLInputElement).toHaveProperty(
      "disabled",
      true,
    );
    expect(screen.queryByRole("button", { name: "提交正式版本" })).toBeNull();
  });

  it("exposes one save action without draft or formal-version product steps", async () => {
    render(<SubjectDetailPage />);
    await screen.findByRole("button", { name: "保存资料" });
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
  it("maps district town data to stable 12-digit street codes", () => {
    expect(
      townOptionsForDistrict(
        [
          { code: "440106", name: "五山街道", town: "001000" },
          { code: "440106", name: "员村街道", town: "002000" },
          { code: "440305", name: "南头街道", town: "001000" },
        ],
        "440106",
      ),
    ).toEqual([
      { value: "440106001000", label: "五山街道" },
      { value: "440106002000", label: "员村街道" },
    ]);
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
