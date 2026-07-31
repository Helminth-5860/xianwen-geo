import { readFileSync } from "node:fs";

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "user-id" }) }));

import AdminUserDetailPage from "../app/admin/users/[id]/page";
import AdminUsersPage from "../app/admin/users/page";

describe("用户审核与账号状态页面", () => {
  it("管理员列表提供冻结范围内的筛选和分页入口", () => {
    const html = renderToStaticMarkup(<AdminUsersPage />);
    expect(html).toContain("用户审核");
    expect(html).toContain("待审核");
    expect(html).toContain("完整手机号");
    expect(html).toContain("仅精确匹配");
  });

  it("管理员详情提供审核历史容器和安全操作文案", () => {
    const html = renderToStaticMarkup(<AdminUserDetailPage />);
    expect(html).toContain("用户审核详情");
    expect(html).toContain("审核与账号状态历史");
    expect(html).toContain("返回审核列表");
  });

  it("用户侧源代码包含拒绝原因、昵称重提和通知入口", () => {
    const source = readFileSync(
      new URL("../components/account/account-overview.tsx", import.meta.url),
      "utf8",
    );
    expect(source).toContain("approval_reason");
    expect(source).toContain("重新提交审核");
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
