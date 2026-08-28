import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

describe("企业级管理员后台", () => {
  it("管理员页面保留真实管理能力，旧技术页面不再进入核心导航", () => {
    expect(read("../app/admin/admins/page.tsx")).toContain("创建管理员");
    const adminDetail = read("../app/admin/admins/[id]/page.tsx");
    expect(adminDetail).toContain("紧急锁定");
    expect(adminDetail).toContain("管理员专属注册链接");
    expect(adminDetail).toContain('commercial_identity === "SUPER_ADMIN"');
    expect(adminDetail).toContain("getAdminRegistrationLink");
    const shell = read("../components/admin/admin-console-shell.tsx");
    expect(shell).toContain("平台总览");
    expect(shell).toContain("模型与接口");
    expect(shell).toContain("操作记录");
    expect(shell).not.toMatch(/租户|角色模板|高风险审批|统一审计/);
  });

  it("后台壳层先读取能力上下文", () => {
    const provider = read("../components/admin/admin-capability.tsx");
    expect(provider).toContain("getAdminContext");
    expect(provider).toContain("无权访问后台");
    expect(provider).toContain("前往登录");
  });

  it("平台总览和九个运营模块路由真实存在", () => {
    expect(read("../app/admin/page.tsx")).toContain("平台总览");
    expect(read("../app/admin/admins/page.tsx")).toContain('title="管理员"');
    expect(read("../app/admin/users/page.tsx")).toContain('title="用户"');
    expect(read("../app/admin/plans/page.tsx")).toContain('title="套餐管理"');
    expect(read("../app/admin/quotas/page.tsx")).toContain('title="额度管理"');
    expect(read("../app/admin/models/page.tsx")).toContain('title="模型与接口"');
    expect(read("../app/admin/business-data/page.tsx")).toContain('title="业务数据"');
    expect(read("../app/admin/system-status/page.tsx")).toContain('title="系统状态"');
    expect(read("../app/admin/operation-records/page.tsx")).toContain('title="操作记录"');
    expect(read("../app/admin/settings/page.tsx")).toContain('title="系统设置"');
  });

  it("前端实现版本冲突和客户归属冲突提示", () => {
    const admin = read("../app/admin/admins/[id]/page.tsx");
    const role = read("../app/admin/roles/[id]/page.tsx");
    expect(admin).toContain('modes["admin.disable"]');
    expect(admin).not.toContain("isApprovalCreated");
    expect(admin).not.toContain("approval_id");
    expect(admin).toContain("expected_version");
    expect(role).toContain('redirect("/admin/admins")');
    expect(role).not.toMatch(/审批|two_person/);
  });

  it("前端不保存认证令牌或展示完整手机号", () => {
    const client = read("../lib/admin-rbac-client.ts");
    expect(client).not.toContain("localStorage");
    expect(client).not.toContain("Authorization");
    expect(client).toContain("phone_masked");
    expect(client).not.toMatch(/\bphone:\s*string/);
  });

  it("菜单和写操作由服务端返回的能力键控制", () => {
    const shell = read("../components/admin/admin-console-shell.tsx");
    const admins = read("../app/admin/admins/page.tsx");
    const adminDetail = read("../app/admin/admins/[id]/page.tsx");
    const roles = read("../app/admin/roles/page.tsx");
    const roleDetail = read("../app/admin/roles/[id]/page.tsx");
    expect(shell).toContain("context.menu_keys.includes");
    expect(admins).toContain('permission_keys.includes("admins.create")');
    expect(adminDetail).toContain('permission_keys.includes("admins.update")');
    expect(adminDetail).toContain('permission_keys.includes("admins.disable")');
    expect(roles).toContain('redirect("/admin/admins")');
    expect(roleDetail).toContain('redirect("/admin/admins")');
    expect(roleDetail).not.toContain('permission_keys.includes("roles.update")');
  });
});
