import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

describe("后台业务数据查询中心", () => {
  it("六类业务数据接入真实只读查询并固定服务端分页", () => {
    const page = read("../app/admin/business-data/page.tsx");
    const client = read("../lib/admin-business-data-client.ts");

    for (const resource of [
      "subjects",
      "questions",
      "detections",
      "reports",
      "articles",
      "images",
    ]) {
      expect(page).toContain(`key: "${resource}"`);
    }
    expect(page).toContain("getAdminBusinessData");
    expect(page).toContain("只读排障查询");
    expect(page).toContain("pageSize={data?.page_size ?? 20}");
    expect(client).toContain("/admin/business-data?");
    expect(client).toContain('cache: "no-store"');
  });

  it("业务数据入口与页面都限制超级管理员", () => {
    const page = read("../app/admin/business-data/page.tsx");
    const shell = read("../components/admin/admin-console-shell.tsx");

    expect(page).toContain('commercial_identity === "SUPER_ADMIN"');
    expect(page).toContain("仅超级管理员可查看");
    expect(shell).toMatch(/href: "\/admin\/business-data"[\s\S]*?superOnly: true/);
  });

  it("页面不展示正文、原始模型响应、存储路径或密钥", () => {
    const page = read("../app/admin/business-data/page.tsx");
    const client = read("../lib/admin-business-data-client.ts");

    expect(page).toContain("不会展示文章正文、模型原始响应、存储路径或密钥");
    expect(client).not.toMatch(/object_key|content:\s*string|prompt|credential|provider_response/);
  });
});
