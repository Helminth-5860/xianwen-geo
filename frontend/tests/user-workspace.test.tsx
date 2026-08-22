// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "../app/page";
import { UserWorkspaceNavigation } from "../components/user-workspace-navigation";

const getCurrentUser = vi.fn();
const getCurrentSubscription = vi.fn();
let pathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));
vi.mock("../lib/auth-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/auth-client")>("../lib/auth-client");
  return {
    ...actual,
    getCurrentUser: (...args: unknown[]) => getCurrentUser(...args),
  };
});
vi.mock("../lib/plans-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/plans-client")>("../lib/plans-client");
  return {
    ...actual,
    getCurrentSubscription: (...args: unknown[]) => getCurrentSubscription(...args),
  };
});
vi.mock("../components/plans/plan-catalog", () => ({
  PlanCatalog: () => <section>套餐目录</section>,
}));

const user = {
  id: "user-1",
  nickname: "免费体验用户",
  phone_masked: "+86 138****0001",
  approval_status: "approved" as const,
  account_status: "active" as const,
};

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

beforeEach(() => {
  pathname = "/";
  getCurrentUser.mockResolvedValue(user);
  getCurrentSubscription.mockResolvedValue({ current: null });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("无套餐用户工作台", () => {
  it("登录后始终展示功能入口和付费路径", async () => {
    render(<Home />);

    expect(await screen.findByText("免费体验用户，欢迎回来")).toBeTruthy();
    expect(screen.getByText("当前没有生效套餐，但工作台功能仍然可见")).toBeTruthy();
    expect(screen.getByText("关键词与问题库")).toBeTruthy();
    expect(screen.getByText("GEO 检测与报告")).toBeTruthy();
    expect(screen.getByText("改善策略与内容")).toBeTruthy();
    expect(
      screen
        .getAllByRole("link", { name: "进入主体工作台" })
        .every((link) => link.getAttribute("href") === "/subjects"),
    ).toBe(true);
    expect(
      screen
        .getAllByRole("link", { name: "打开 AI 助手" })
        .every((link) => link.getAttribute("href") === "/assistant"),
    ).toBe(true);
    expect(screen.getByRole("link", { name: "查看订阅与额度" }).getAttribute("href")).toBe(
      "/subscription",
    );
    expect(screen.getByText("套餐目录")).toBeTruthy();
    expect(screen.queryByText("基础设施")).toBeNull();
  });

  it("未登录访客仍看到注册登录入口而不显示用户工作台", async () => {
    getCurrentUser.mockRejectedValue(new Error("unauthenticated"));
    render(<Home />);

    expect(await screen.findByText("显问 GEO 智能体系统")).toBeTruthy();
    expect(screen.getByRole("link", { name: "创建账号" })).toBeTruthy();
    expect(screen.queryByLabelText("用户功能工作台")).toBeNull();
  });

  it("认证导航不依赖套餐，并在管理后台隐藏", async () => {
    const { rerender } = render(<UserWorkspaceNavigation />);
    expect(await screen.findByRole("navigation", { name: "用户工作台导航" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "主体与 GEO" }).getAttribute("href")).toBe("/subjects");

    pathname = "/admin";
    rerender(<UserWorkspaceNavigation />);
    await waitFor(() =>
      expect(screen.queryByRole("navigation", { name: "用户工作台导航" })).toBeNull(),
    );
  });
});
