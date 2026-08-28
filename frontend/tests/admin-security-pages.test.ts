import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

describe("管理员安全页面源代码边界", () => {
  it("challenge 不进入任何持久化浏览器存储或 URL", () => {
    const login = read("../app/admin/login/page.tsx");
    const stepUp = read("../components/admin/admin-step-up.tsx");
    expect(login).not.toContain("challengeId");
    expect(stepUp).toContain('useState("")');
    for (const source of [login, stepUp]) {
      expect(source).not.toContain("localStorage");
      expect(source).not.toContain("sessionStorage");
      expect(source).not.toContain("URLSearchParams");
      expect(source).not.toContain("document.cookie");
    }
  });

  it("角色和超级管理员页面提供 current_password、版本与锁出确认", () => {
    const role = read("../app/admin/roles/[id]/security/page.tsx");
    const superuser = read("../app/admin/security/page.tsx");
    for (const source of [role, superuser]) {
      expect(source).toContain("current_password");
      expect(source).toContain("confirm_lockout");
      expect(source).toContain("security_version");
      expect(source).toContain("IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED");
    }
  });

  it("普通登录页将管理员引导到独立后台入口", () => {
    const login = read("../app/login/page.tsx");
    expect(login).toContain("ADMIN_LOGIN_REQUIRED");
    expect(login).toContain("/admin/login");
  });

  it("管理员详情强制退出具有二次确认", () => {
    const detail = read("../app/admin/admins/[id]/page.tsx");
    expect(detail).toContain("forceLogoutAdmin");
    expect(detail).toContain("RiskActionButton");
    expect(detail).toContain('mode={modes["admin.force_logout"]');
  });
});
