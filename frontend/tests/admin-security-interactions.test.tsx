// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  loginWithPassword: vi.fn(),
  loginWithSms: vi.fn(),
  adminLoginWithPassword: vi.fn(),
  getRoleSecurity: vi.fn(),
  updateRoleSecurity: vi.fn(),
  getRoleIpAllowlist: vi.fn(),
  createRoleIpAllowlistEntry: vi.fn(),
  updateRoleIpAllowlistEntry: vi.fn(),
  getSuperuserSecurity: vi.fn(),
  updateSuperuserSecurity: vi.fn(),
  getSuperuserIpAllowlist: vi.fn(),
  createSuperuserIpAllowlistEntry: vi.fn(),
  updateSuperuserIpAllowlistEntry: vi.fn(),
  getAdmin: vi.fn(),
  getRoles: vi.fn(),
  forceLogoutAdmin: vi.fn(),
  changeAdminStatus: vi.fn(),
  updateAdmin: vi.fn(),
  changeAdminRole: vi.fn(),
  getRiskActions: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
  useParams: () => ({ id: "target-id" }),
}));
vi.mock("@/lib/auth-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/auth-client")>();
  return {
    ...actual,
    loginWithPassword: mocks.loginWithPassword,
    loginWithSms: mocks.loginWithSms,
  };
});
vi.mock("@/lib/admin-rbac-client", () => ({
  adminLoginWithPassword: mocks.adminLoginWithPassword,
  getRoleSecurity: mocks.getRoleSecurity,
  updateRoleSecurity: mocks.updateRoleSecurity,
  getRoleIpAllowlist: mocks.getRoleIpAllowlist,
  createRoleIpAllowlistEntry: mocks.createRoleIpAllowlistEntry,
  updateRoleIpAllowlistEntry: mocks.updateRoleIpAllowlistEntry,
  getSuperuserSecurity: mocks.getSuperuserSecurity,
  updateSuperuserSecurity: mocks.updateSuperuserSecurity,
  getSuperuserIpAllowlist: mocks.getSuperuserIpAllowlist,
  createSuperuserIpAllowlistEntry: mocks.createSuperuserIpAllowlistEntry,
  updateSuperuserIpAllowlistEntry: mocks.updateSuperuserIpAllowlistEntry,
  getAdmin: mocks.getAdmin,
  getRoles: mocks.getRoles,
  forceLogoutAdmin: mocks.forceLogoutAdmin,
  changeAdminStatus: mocks.changeAdminStatus,
  updateAdmin: mocks.updateAdmin,
  changeAdminRole: mocks.changeAdminRole,
}));
vi.mock("@/lib/risk-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/risk-client")>();
  return { ...actual, getRiskActions: mocks.getRiskActions };
});
vi.mock("@/components/admin/admin-capability", () => ({
  useAdminCapabilities: () => ({
    id: "target-id",
    user_id: "target-user-id",
    permission_keys: ["admins.update", "admins.disable"],
    menu_keys: [],
  }),
}));

import AdminDetailPage from "../app/admin/admins/[id]/page";
import AdminLoginPage from "../app/admin/login/page";
import RoleSecurityPage from "../app/admin/roles/[id]/security/page";
import SuperuserSecurityPage from "../app/admin/security/page";
import LoginPage from "../app/login/page";
import { AuthApiError } from "../lib/auth-client";

const roleSecurity = { require_sms_2fa: false, ip_allowlist_enabled: false, security_version: 1 };
const superSecurity = {
  id: "policy",
  require_sms_2fa: true as const,
  ip_allowlist_enabled: false,
  security_version: 1,
};
const entry = {
  id: "entry",
  network_cidr: "203.0.113.8/32",
  ip_version: 4 as const,
  label: "办公室",
  status: "active" as const,
};
const profile = {
  id: "target-id",
  user_id: "target-user-id",
  nickname: "超级管理员",
  phone_masked: "139****9000",
  is_superuser: true,
  admin_status: "active" as const,
  version: 1,
  logout_version: 1,
  role: null,
};

mocks.getRiskActions.mockResolvedValue([
  {
    key: "admin.force_logout",
    current_mode: "confirm",
  },
]);

function error(code: string, message: string, status: number) {
  return new AuthApiError(new Response(null, { status }), {
    success: false,
    error: { code, message, details: {} },
    request_id: "00000000-0000-4000-8000-000000000010",
  });
}

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  const nativeGetComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
    nativeGetComputedStyle(element),
  );
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("普通登录与 challenge 内存边界", () => {
  it("管理员错误只显示中文安全入口，不泄露策略", async () => {
    mocks.loginWithPassword.mockRejectedValueOnce(
      error("ADMIN_LOGIN_REQUIRED", "请使用管理员登录入口", 403),
    );
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText("手机号或账号"), "13900139000");
    await user.type(screen.getByLabelText("密码"), "Safe-password");
    await user.click(screen.getByRole("button", { name: /登\s*录/ }));
    expect(await screen.findByText("管理员账号请从管理员登录入口登录。")).toBeTruthy();
    expect(screen.queryByText("请使用管理员登录入口")).toBeNull();
    expect(screen.getByRole("link", { name: "前往管理员安全登录" }).getAttribute("href")).toBe(
      "/admin/login",
    );
    expect(screen.queryByText(/管理员角色|白名单配置|是否开启 2FA/)).toBeNull();
  });

  it("管理员密码登录不创建 challenge 且不写浏览器存储", async () => {
    mocks.adminLoginWithPassword.mockResolvedValueOnce({
      requires_2fa: false,
      user: { home_route: "/admin" },
    });
    const user = userEvent.setup();
    render(<AdminLoginPage />);
    await user.type(screen.getByLabelText("手机号"), "13900139000");
    await user.type(screen.getByLabelText("密码"), "Safe-password");
    await user.click(screen.getByRole("button", { name: /登录后台/ }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/admin"));
    expect(screen.queryByLabelText("短信验证码")).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});

describe("角色安全策略", () => {
  it("真实提交 2FA/IP、锁出确认、CIDR 新增和状态切换", async () => {
    mocks.getRoleSecurity.mockResolvedValue(roleSecurity);
    mocks.getRoleIpAllowlist.mockResolvedValue([entry]);
    mocks.updateRoleSecurity
      .mockRejectedValueOnce(
        error("IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED", "新白名单将排除当前网络", 409),
      )
      .mockResolvedValueOnce({
        ...roleSecurity,
        require_sms_2fa: true,
        ip_allowlist_enabled: true,
        security_version: 2,
      });
    mocks.createRoleIpAllowlistEntry.mockResolvedValue({ entry, security_version: 2 });
    mocks.updateRoleIpAllowlistEntry.mockResolvedValue({ entry, security_version: 3 });
    const user = userEvent.setup();
    render(<RoleSecurityPage />);
    await screen.findByText("角色安全与 Step-Up 策略");
    await user.click(screen.getByRole("button", { name: /保存\s*安全\s*策略/ }));
    expect(mocks.updateRoleSecurity).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("switch", { name: "历史短信策略标记（兼容保留，不再作为登录门禁）" }),
    );
    await user.click(screen.getByRole("switch", { name: "启用 IP 白名单" }));
    await user.click(screen.getByRole("button", { name: /保存\s*安全\s*策略/ }));
    expect(screen.getByLabelText("当前超级管理员密码").getAttribute("aria-invalid")).toBe("true");
    expect(mocks.updateRoleSecurity).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("当前超级管理员密码"), "Safe-password");
    await user.click(screen.getByRole("button", { name: /保存\s*安全\s*策略/ }));
    expect(await screen.findByText(/确认风险后可勾选允许锁出/)).toBeTruthy();
    await user.click(screen.getByRole("switch", { name: "确认允许当前网络被锁出" }));
    await user.click(screen.getByRole("button", { name: /保存\s*安全\s*策略/ }));
    await waitFor(() =>
      expect(mocks.updateRoleSecurity).toHaveBeenLastCalledWith(
        "target-id",
        expect.objectContaining({
          require_sms_2fa: true,
          ip_allowlist_enabled: true,
          confirm_lockout: true,
          current_password: "Safe-password",
        }),
      ),
    );
    await user.type(screen.getByPlaceholderText("203.0.113.8 或 2001:db8::/48"), "2001:db8::8");
    await user.type(screen.getAllByPlaceholderText("当前密码")[0], "Safe-password");
    await user.click(screen.getByRole("button", { name: /添加\s*或\s*恢复/ }));
    await waitFor(() => expect(mocks.createRoleIpAllowlistEntry).toHaveBeenCalled());
    const row = screen.getByText("203.0.113.8/32").closest("tr")!;
    await user.type(within(row).getByPlaceholderText("当前密码"), "Safe-password");
    await user.click(within(row).getByRole("button", { name: /停\s*用/ }));
    await waitFor(() => expect(mocks.updateRoleIpAllowlistEntry).toHaveBeenCalled());
  });

  it.each([
    ["PERMISSION_DENIED", "没有权限执行此操作", 403, "你没有权限查看或操作这项内容。"],
    [
      "SECURITY_POLICY_VERSION_CONFLICT",
      "安全策略已发生变化，请刷新后重试",
      409,
      "内容刚刚发生变化，请刷新后再操作。",
    ],
    ["RATE_LIMITED", "操作过于频繁，请稍后再试", 429, "当前访问人数较多，请稍后再试。"],
    [
      "SERVICE_TEMPORARILY_UNAVAILABLE",
      "服务暂时不可用，请稍后再试",
      503,
      "当前服务暂不可用，请稍后重新尝试。",
    ],
  ])("显示 %s 中文错误", async (code, backendMessage, status, expectedMessage) => {
    mocks.getRoleSecurity.mockResolvedValue(roleSecurity);
    mocks.getRoleIpAllowlist.mockResolvedValue([]);
    mocks.updateRoleSecurity.mockRejectedValueOnce(
      error(code as string, backendMessage as string, status as number),
    );
    const user = userEvent.setup();
    render(<RoleSecurityPage />);
    await screen.findByText("角色安全与 Step-Up 策略");
    await user.type(screen.getByLabelText("当前超级管理员密码"), "Safe-password");
    await user.click(screen.getByRole("button", { name: /保存\s*安全\s*策略/ }));
    expect(await screen.findByText(expectedMessage as string)).toBeTruthy();
    expect(screen.queryByText(backendMessage as string)).toBeNull();
  });
});

describe("superuser 安全策略", () => {
  it("真实提交 IP、锁出确认、CIDR 和 active/inactive", async () => {
    mocks.getSuperuserSecurity.mockResolvedValue(superSecurity);
    mocks.getSuperuserIpAllowlist.mockResolvedValue([entry]);
    mocks.updateSuperuserSecurity
      .mockRejectedValueOnce(error("IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED", "需要确认", 409))
      .mockResolvedValueOnce({ ...superSecurity, ip_allowlist_enabled: true, security_version: 2 });
    mocks.createSuperuserIpAllowlistEntry.mockResolvedValue({ entry, security_version: 2 });
    mocks.updateSuperuserIpAllowlistEntry.mockResolvedValue({ entry, security_version: 3 });
    const user = userEvent.setup();
    render(<SuperuserSecurityPage />);
    await screen.findByText("超级管理员安全策略");
    await user.click(screen.getByRole("switch", { name: "启用自己的 IP 白名单" }));
    await user.click(screen.getByRole("button", { name: /保存\s*策略/ }));
    expect(screen.getByLabelText("当前密码").getAttribute("aria-invalid")).toBe("true");
    expect(mocks.updateSuperuserSecurity).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("当前密码"), "Safe-password");
    await user.click(screen.getByRole("button", { name: /保存\s*策略/ }));
    expect(await screen.findByText(/明确勾选锁出确认/)).toBeTruthy();
    await user.click(screen.getByRole("switch", { name: "确认允许当前网络被锁出" }));
    await user.click(screen.getByRole("button", { name: /保存\s*策略/ }));
    await waitFor(() =>
      expect(mocks.updateSuperuserSecurity).toHaveBeenLastCalledWith(
        expect.objectContaining({ confirm_lockout: true }),
      ),
    );
    await user.type(screen.getByPlaceholderText("IPv4 / IPv6 CIDR"), "2001:db8::8");
    await user.type(screen.getAllByPlaceholderText("当前密码")[0], "Safe-password");
    await user.click(screen.getByRole("button", { name: /添加\s*或\s*恢复/ }));
    await waitFor(() => expect(mocks.createSuperuserIpAllowlistEntry).toHaveBeenCalled());
    const row = screen.getByText("203.0.113.8/32").closest("tr")!;
    await user.type(within(row).getByPlaceholderText("当前密码"), "Safe-password");
    await user.click(within(row).getByRole("button", { name: /停\s*用/ }));
    await waitFor(() => expect(mocks.updateSuperuserIpAllowlistEntry).toHaveBeenCalled());
  });

  it.each([
    [
      "PERMISSION_DENIED",
      "普通管理员无权访问超级管理员安全策略",
      403,
      "你没有权限查看或操作这项内容。",
    ],
    [
      "SECURITY_POLICY_VERSION_CONFLICT",
      "安全策略版本冲突",
      409,
      "内容刚刚发生变化，请刷新后再操作。",
    ],
    ["RATE_LIMITED", "操作过于频繁，请稍后再试", 429, "当前访问人数较多，请稍后再试。"],
    [
      "SERVICE_TEMPORARILY_UNAVAILABLE",
      "服务暂时不可用，请稍后再试",
      503,
      "当前服务暂不可用，请稍后重新尝试。",
    ],
  ])("显示 %s 中文错误", async (code, backendMessage, status, expectedMessage) => {
    mocks.getSuperuserSecurity.mockRejectedValueOnce(
      error(code as string, backendMessage as string, status as number),
    );
    mocks.getSuperuserIpAllowlist.mockResolvedValue([]);
    render(<SuperuserSecurityPage />);
    expect(await screen.findByText(expectedMessage as string)).toBeTruthy();
    expect(screen.queryByText(backendMessage as string)).toBeNull();
  });
});

describe("force logout", () => {
  it("二次确认后显示自我会话失效提示", async () => {
    mocks.getAdmin.mockResolvedValue(profile);
    mocks.getRoles.mockResolvedValue({ results: [], count: 0, next: null, previous: null });
    mocks.forceLogoutAdmin.mockResolvedValue({ logged_out: true, admin_id: "target-id" });
    const user = userEvent.setup();
    render(<AdminDetailPage />);
    await screen.findByText(/超级管理员/);
    await user.click(screen.getByRole("button", { name: "强制退出全部设备" }));
    expect(await screen.findByText("确认后立即执行")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "确认执行" }));
    expect(await screen.findByText("已撤销当前会话；下一次请求将要求重新登录。")).toBeTruthy();
  });

  it.each([
    ["PERMISSION_DENIED", "没有权限强制退出", 403, "你没有权限查看或操作这项内容。"],
    [
      "SECURITY_POLICY_VERSION_CONFLICT",
      "管理员状态已变化",
      409,
      "内容刚刚发生变化，请刷新后再操作。",
    ],
    ["RATE_LIMITED", "操作过于频繁，请稍后再试", 429, "当前访问人数较多，请稍后再试。"],
    [
      "SERVICE_TEMPORARILY_UNAVAILABLE",
      "服务暂时不可用，请稍后再试",
      503,
      "当前服务暂不可用，请稍后重新尝试。",
    ],
  ])("显示 %s 中文错误", async (code, backendMessage, status, expectedMessage) => {
    mocks.getAdmin.mockResolvedValue(profile);
    mocks.getRoles.mockResolvedValue({ results: [], count: 0, next: null, previous: null });
    mocks.forceLogoutAdmin.mockRejectedValueOnce(
      error(code as string, backendMessage as string, status as number),
    );
    const user = userEvent.setup();
    render(<AdminDetailPage />);
    await screen.findByText(/超级管理员/);
    await user.click(screen.getByRole("button", { name: "强制退出全部设备" }));
    await user.click(await screen.findByRole("button", { name: "确认执行" }));
    expect(await screen.findByText(expectedMessage as string)).toBeTruthy();
    expect(screen.queryByText(backendMessage as string)).toBeNull();
  });
});
