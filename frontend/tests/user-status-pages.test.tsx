import { readFileSync } from "node:fs";

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "user-id" }) }));

import AdminUserDetailPage from "../app/admin/users/[id]/page";
import AdminUsersPage from "../app/admin/users/page";

describe("用户与账号状态页面", () => {
  it("用户列表提供直白的管理筛选和分页入口", () => {
    const html = renderToStaticMarkup(<AdminUsersPage />);
    expect(html).toContain(">用户</h2>");
    expect(html).toContain("按手机号查询");
    expect(html).toContain("所属管理员");
    expect(html).toContain("暂无用户");
  });

  it("用户详情提供账号变更记录和返回入口", () => {
    const html = renderToStaticMarkup(<AdminUserDetailPage />);
    expect(html).toContain("用户详情");
    expect(html).toContain("账号变更记录");
    expect(html).toContain("返回用户列表");
  });

  it("用户侧源代码只展示账号状态和通知入口", () => {
    const source = readFileSync(
      new URL("../components/account/account-overview.tsx", import.meta.url),
      "utf8",
    );
    expect(source).toContain("account_status");
    expect(source).toContain("正常");
    expect(source).toContain("禁用");
    expect(source).not.toContain("approval_status");
    expect(source).toContain("站内通知");
    expect(source).toContain("markNotificationRead");
  });

  it("前端不实现本地令牌存储或敏感调试入口", () => {
    const source = readFileSync(new URL("../lib/auth-client.ts", import.meta.url), "utf8");
    expect(source).not.toContain("localStorage");
    expect(source).not.toContain("sessionStorage");
    expect(source).not.toContain("Authorization");
    expect(source).not.toContain("auth/me");
    expect(source).not.toContain("session_version");
  });
});
