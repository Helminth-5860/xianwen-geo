import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

describe("管理员 RBAC 和数据范围页面", () => {
  it("管理员和角色页面真实存在", () => {
    expect(read("../app/admin/admins/page.tsx")).toContain("创建普通管理员");
    expect(read("../app/admin/admins/[id]/page.tsx")).toContain("紧急锁定");
    expect(read("../app/admin/roles/page.tsx")).toContain("客户数据范围");
    expect(read("../app/admin/roles/[id]/page.tsx")).toContain("菜单与动作权限");
  });

  it("后台壳层先读取能力上下文", () => {
    const provider = read("../components/admin/admin-capability.tsx");
    expect(provider).toContain("getAdminContext");
    expect(provider).toContain("无权访问后台");
  });

  it("前端实现版本冲突和客户归属冲突提示", () => {
    const admin = read("../app/admin/admins/[id]/page.tsx");
    const role = read("../app/admin/roles/[id]/page.tsx");
    expect(admin).toContain("ADMIN_HAS_ASSIGNED_CUSTOMERS");
    expect(admin).toContain("expected_version");
    expect(role).toContain("expected_version");
    expect(role).toContain("版本冲突");
  });

  it("前端不保存认证令牌或展示完整手机号", () => {
    const client = read("../lib/admin-rbac-client.ts");
    expect(client).not.toContain("localStorage");
    expect(client).not.toContain("Authorization");
    expect(client).toContain("phone_masked");
    expect(client).not.toMatch(/\bphone:\s*string/);
  });

  it("菜单和写操作由服务端返回的能力键控制", () => {
    const provider = read("../components/admin/admin-capability.tsx");
    const admins = read("../app/admin/admins/page.tsx");
    const adminDetail = read("../app/admin/admins/[id]/page.tsx");
    const roles = read("../app/admin/roles/page.tsx");
    const roleDetail = read("../app/admin/roles/[id]/page.tsx");
    expect(provider).toContain("menu_keys.includes");
    expect(admins).toContain('permission_keys.includes("admins.create")');
    expect(adminDetail).toContain('permission_keys.includes("admins.update")');
    expect(adminDetail).toContain('permission_keys.includes("admins.disable")');
    expect(roles).toContain('permission_keys.includes("roles.create")');
    expect(roleDetail).toContain('permission_keys.includes("roles.update")');
    expect(roleDetail).toContain('permission_keys.includes("roles.disable")');
  });
});
