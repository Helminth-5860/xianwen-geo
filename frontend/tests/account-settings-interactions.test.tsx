// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountMenu } from "../components/account/account-menu";
import { AccountSettingsWorkspace } from "../components/account/account-settings-workspace";

const mocks = vi.hoisted(() => ({
  router: { push: vi.fn(), refresh: vi.fn(), replace: vi.fn() },
  refreshWorkspace: vi.fn(),
  updateAccountProfile: vi.fn(),
  requestPhoneChangeCode: vi.fn(),
  changeAccountPhone: vi.fn(),
  changeAccountPassword: vi.fn(),
  revokeOtherSessions: vi.fn(),
  logoutAccount: vi.fn(),
  previewAppearance: vi.fn(),
  saveAppearance: vi.fn(),
  resetPreview: vi.fn(),
}));

const account = {
  id: "user-1",
  nickname: "显问用户",
  phone_masked: "138****8000",
  appearance: { mode: "light" as const, accent: "blue" as const },
  account_status: "active" as const,
  commercial_identity: "USER" as const,
  home_route: "/workspace" as const,
  tenant: null,
};

let workspaceState = {
  loading: false,
  user: account as typeof account | null,
  refresh: mocks.refreshWorkspace,
};

let themeState = {
  mode: "light" as "light" | "dark" | "system",
  accent: "blue" as "blue" | "green" | "purple" | "orange",
  effectiveMode: "light" as "light" | "dark",
  savedAppearance: { mode: "light" as const, accent: "blue" as const },
};

vi.mock("next/navigation", () => ({ useRouter: () => mocks.router }));
vi.mock("../components/subject-workspace-context", () => ({
  useSubjectWorkspace: () => workspaceState,
}));
vi.mock("../components/theme", () => ({
  useAppTheme: () => ({
    ...themeState,
    previewAppearance: mocks.previewAppearance,
    saveAppearance: mocks.saveAppearance,
    resetPreview: mocks.resetPreview,
  }),
}));
vi.mock("../lib/auth-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/auth-client")>("../lib/auth-client");
  return {
    ...actual,
    updateAccountProfile: mocks.updateAccountProfile,
    requestPhoneChangeCode: mocks.requestPhoneChangeCode,
    changeAccountPhone: mocks.changeAccountPhone,
    changeAccountPassword: mocks.changeAccountPassword,
    revokeOtherSessions: mocks.revokeOtherSessions,
    logoutAccount: mocks.logoutAccount,
  };
});

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  workspaceState = { loading: false, user: account, refresh: mocks.refreshWorkspace };
  themeState = {
    mode: "light",
    accent: "blue",
    effectiveMode: "light",
    savedAppearance: { mode: "light", accent: "blue" },
  };
  mocks.refreshWorkspace.mockResolvedValue(undefined);
  mocks.updateAccountProfile.mockResolvedValue({ ...account, nickname: "新昵称" });
  mocks.requestPhoneChangeCode.mockResolvedValue({ sent: true, expires_in: 300, resend_after: 60 });
  mocks.changeAccountPhone.mockResolvedValue({ changed: true, reauthentication_required: true });
  mocks.changeAccountPassword.mockResolvedValue({
    changed: true,
    reauthentication_required: true,
  });
  mocks.revokeOtherSessions.mockResolvedValue({ revoked: true });
  mocks.logoutAccount.mockResolvedValue({ logged_out: true });
  mocks.saveAppearance.mockResolvedValue(undefined);
});

afterEach(() => cleanup());

describe("顶部账号菜单", () => {
  it("展示账号入口并完成设置导航和安全退出", async () => {
    render(<AccountMenu user={account} />);

    await userEvent.click(screen.getByRole("button", { name: "打开账号菜单" }));
    expect((await screen.findAllByText("显问用户")).length).toBeGreaterThan(1);
    expect(screen.getByText("138****8000")).toBeTruthy();
    await userEvent.click(screen.getByText("账号设置"));
    expect(mocks.router.push).toHaveBeenCalledWith("/account/settings");

    await userEvent.click(screen.getByRole("button", { name: "打开账号菜单" }));
    await userEvent.click(await screen.findByText("外观设置"));
    expect(mocks.router.push).toHaveBeenCalledWith("/account/settings#appearance");

    await userEvent.click(screen.getByRole("button", { name: "打开账号菜单" }));
    await userEvent.click(await screen.findByText("退出登录"));
    await waitFor(() => expect(mocks.logoutAccount).toHaveBeenCalledTimes(1));
    expect(mocks.router.replace).toHaveBeenCalledWith("/login");
    expect(mocks.router.refresh).toHaveBeenCalled();
  });
});

describe("账号设置页面", () => {
  it("未登录时不展示设置并返回登录页", async () => {
    workspaceState = { loading: false, user: null, refresh: mocks.refreshWorkspace };
    render(<AccountSettingsWorkspace />);
    await waitFor(() => expect(mocks.router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByRole("heading", { name: "账号设置" })).toBeNull();
  });

  it("修改昵称后刷新工作区账号信息", async () => {
    render(<AccountSettingsWorkspace />);
    const nickname = screen.getByLabelText("昵称");
    await userEvent.clear(nickname);
    await userEvent.type(nickname, "新昵称");
    await userEvent.click(screen.getByRole("button", { name: "保存个人资料" }));

    await waitFor(() =>
      expect(mocks.updateAccountProfile).toHaveBeenCalledWith({ nickname: "新昵称" }),
    );
    expect(mocks.refreshWorkspace).toHaveBeenCalled();
    expect(screen.getByDisplayValue("138****8000")).toBeTruthy();
  });

  it("向新手机号发送验证码并显示倒计时", async () => {
    render(<AccountSettingsWorkspace />);
    const card = screen.getByText("更换手机号").closest(".ant-card");
    expect(card).toBeTruthy();
    const scope = within(card as HTMLElement);
    await userEvent.type(scope.getByLabelText("新手机号"), "13900139000");
    await userEvent.type(scope.getByLabelText("更换手机号当前密码"), "Current-password-2026!");
    await userEvent.click(scope.getByRole("button", { name: "发送短信验证码" }));

    await waitFor(() =>
      expect(mocks.requestPhoneChangeCode).toHaveBeenCalledWith({
        phone: "13900139000",
        currentPassword: "Current-password-2026!",
      }),
    );
    expect(
      (await scope.findByRole("button", { name: "60 秒后重新发送" })).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("更换手机号和修改密码成功后返回登录页", async () => {
    render(<AccountSettingsWorkspace />);
    const phoneCard = screen.getByText("更换手机号").closest(".ant-card") as HTMLElement;
    const phoneScope = within(phoneCard);
    await userEvent.type(phoneScope.getByLabelText("新手机号"), "13900139000");
    await userEvent.type(phoneScope.getByLabelText("更换手机号当前密码"), "Current-password-2026!");
    await userEvent.type(phoneScope.getByLabelText("更换手机号短信验证码"), "438921");
    await userEvent.click(phoneScope.getByRole("button", { name: "确认更换手机号" }));
    await waitFor(() => expect(mocks.changeAccountPhone).toHaveBeenCalled());
    expect(mocks.router.replace).toHaveBeenCalledWith("/login");

    mocks.router.replace.mockClear();
    const passwordCard = screen.getByText("修改密码").closest(".ant-card") as HTMLElement;
    const passwordScope = within(passwordCard);
    await userEvent.type(
      passwordScope.getByLabelText("修改密码当前密码"),
      "Current-password-2026!",
    );
    await userEvent.type(passwordScope.getByLabelText("新密码"), "New-password-2027!");
    await userEvent.type(passwordScope.getByLabelText("确认新密码"), "New-password-2027!");
    await userEvent.click(passwordScope.getByRole("button", { name: "确认修改密码" }));
    await waitFor(() => expect(mocks.changeAccountPassword).toHaveBeenCalled());
    expect(mocks.router.replace).toHaveBeenCalledWith("/login");
  });

  it("预览并保存个人主题，不影响安全状态色文案", async () => {
    themeState = {
      mode: "dark",
      accent: "green",
      effectiveMode: "dark",
      savedAppearance: { mode: "light", accent: "blue" },
    };
    render(<AccountSettingsWorkspace />);

    await userEvent.click(screen.getByRole("button", { name: "暖橙色" }));
    expect(mocks.previewAppearance).toHaveBeenCalledWith({ mode: "dark", accent: "orange" });
    await userEvent.click(screen.getByRole("button", { name: "保存外观设置" }));
    await waitFor(() =>
      expect(mocks.saveAppearance).toHaveBeenCalledWith({ mode: "dark", accent: "green" }),
    );
    expect(mocks.refreshWorkspace).toHaveBeenCalled();
    expect(screen.getByText(/当前预览：深色模式 · 青绿色/)).toBeTruthy();
  });

  it("退出其他设备后保留当前页面登录状态", async () => {
    render(<AccountSettingsWorkspace />);
    const card = screen.getByText("登录设备管理").closest(".ant-card") as HTMLElement;
    const scope = within(card);
    await userEvent.type(scope.getByLabelText("设备管理当前密码"), "Current-password-2026!");
    await userEvent.click(scope.getByRole("button", { name: "退出其他设备" }));
    await waitFor(() =>
      expect(mocks.revokeOtherSessions).toHaveBeenCalledWith("Current-password-2026!"),
    );
    expect(mocks.router.replace).not.toHaveBeenCalled();
  });
});
