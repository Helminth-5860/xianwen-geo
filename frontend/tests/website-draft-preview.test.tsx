// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import { WebsiteDraftPreview } from "../components/website-draft-preview";
import type { WebsiteProject } from "../lib/websites-client";

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

afterEach(() => cleanup());

const section = (type: "hero" | "text" | "cards" | "faq" | "contact", title: string) => ({
  type,
  title,
  body: `${title}正文`,
  items: type === "cards" ? [{ title: "服务一", body: "服务说明" }] : [],
});

const project: WebsiteProject = {
  id: "website-1",
  subject_id: "subject-1",
  subject_version_id: "version-1",
  style_key: "technology",
  style_name: "科技未来",
  theme_key: "amethyst",
  theme_name: "紫晶",
  density_key: "standard",
  density_name: "标准",
  status: "ready",
  selected_asset_ids: [],
  selected_document_ids: ["document-1"],
  site_schema_version: 1,
  site: {
    schema_version: 1,
    tagline: "让企业信息更容易被理解",
    pages: [
      {
        key: "home",
        slug: "",
        title: "首页",
        seo_title: "首页标题",
        seo_description: "首页说明",
        sections: [
          section("hero", "专注企业增长"),
          section("cards", "核心服务"),
          section("text", "企业能力"),
          section("faq", "常见问题"),
          section("contact", "联系我们"),
        ],
      },
      ...(["about", "services", "solutions", "faq", "contact"] as const).map((key) => ({
        key,
        slug: key,
        title: {
          about: "关于我们",
          services: "产品服务",
          solutions: "解决方案",
          faq: "常见问题",
          contact: "联系我们",
        }[key],
        seo_title: `${key}标题`,
        seo_description: `${key}说明`,
        sections: [
          section(key === "faq" ? "faq" : key === "contact" ? "contact" : "text", "页面内容"),
        ],
      })),
    ],
  },
  contact: { primary_business: "企业服务" },
  generation_count: 1,
  error_message: "",
  version: 2,
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z",
};

describe("官网草稿预览", () => {
  it("使用当前主体内容和客户真实图片渲染官网草稿", () => {
    render(
      <WebsiteDraftPreview
        project={project}
        subjectName="显问科技"
        materials={[
          {
            id: "document-1",
            url: "https://example.test/company.webp",
            name: "企业实景",
            source: "客户上传",
          },
        ]}
      />,
    );

    expect(screen.getByText("显问科技")).toBeTruthy();
    expect(screen.getByText("专注企业增长")).toBeTruthy();
    expect(screen.getByText("不会自动公开，确认后再进入发布流程")).toBeTruthy();
    expect(screen.getByAltText("首页主视觉").getAttribute("src")).toBe(
      "https://example.test/company.webp",
    );
  });

  it("简洁模式减少展示区域但保留联系信息", () => {
    render(
      <WebsiteDraftPreview
        project={project}
        subjectName="显问科技"
        materials={[]}
        design={{ styleKey: "industrial", themeKey: "obsidian", densityKey: "compact" }}
      />,
    );

    expect(screen.getByText("核心服务")).toBeTruthy();
    expect(screen.queryByText("企业能力")).toBeNull();
    expect(screen.getAllByText("联系我们").length).toBeGreaterThan(0);
  });
});
