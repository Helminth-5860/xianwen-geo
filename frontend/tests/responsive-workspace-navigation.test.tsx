// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ResponsiveWorkspaceShell } from "../components/responsive-workspace-shell";
import { SubjectWorkspaceProvider } from "../components/subject-workspace-context";
import { WORKSPACE_NAVIGATION_PREFERENCE_KEY } from "../components/workspace-navigation-state";

const getCurrentUser = vi.fn();
const getSubjects = vi.fn();
const router = { push: vi.fn(), replace: vi.fn(), refresh: vi.fn() };
let pathname = "/workspace";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => router,
}));
vi.mock("next/link", () => ({
  default: ({ href, onClick, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a
      {...props}
      href={String(href)}
      onClick={(event) => {
        event.preventDefault();
        onClick?.(event);
      }}
    />
  ),
}));
vi.mock("../lib/auth-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/auth-client")>("../lib/auth-client");
  return { ...actual, getCurrentUser: (...args: unknown[]) => getCurrentUser(...args) };
});
vi.mock("../lib/subjects-client", async () => {
  const actual =
    await vi.importActual<typeof import("../lib/subjects-client")>("../lib/subjects-client");
  return {
    ...actual,
    getSubjects: (...args: unknown[]) => getSubjects(...args),
  };
});

const account = {
  id: "user-1",
  nickname: "预览用户",
  phone_masked: "masked",
  appearance: { mode: "light" as const, accent: "blue" as const },
  account_status: "active" as const,
  commercial_identity: "USER" as const,
  home_route: "/workspace" as const,
  tenant: {
    id: "tenant-1",
    key: "preview",
    display_name: "预览租户",
    brand_name: "显问 GEO",
    logo_reference: "",
  },
};

const subject = {
  id: "subject-1",
  subject_type: { id: "type-1", key: "company", name: "企业", icon_key: "company" },
  status: "active" as const,
  version: 3,
  is_current: true,
  current_version_no: 2,
  official_name: "显问科技",
  service_regions: JSON.stringify({ version: 1, nationwide: true, areas: [] }),
  retest_required: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};

function setViewport(width: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
}

function renderShell() {
  return render(
    <SubjectWorkspaceProvider>
      <ResponsiveWorkspaceShell>
        <main data-testid="workspace-content">工作区内容</main>
      </ResponsiveWorkspaceShell>
    </SubjectWorkspaceProvider>,
  );
}

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({
      matches: false,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
  const nativeGetComputedStyle = window.getComputedStyle.bind(window);
  Object.defineProperty(window, "getComputedStyle", {
    configurable: true,
    value: (element: Element) => nativeGetComputedStyle(element),
  });
});

beforeEach(() => {
  pathname = "/workspace";
  window.localStorage.clear();
  document.body.style.overflow = "";
  getCurrentUser.mockResolvedValue(account);
  getSubjects.mockResolvedValue({
    subjects: [subject],
    context: { current_subject_id: subject.id, version: 1 },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("四态工作台导航", () => {
  it("宽屏默认展开，可切为精简并在重新挂载后恢复偏好", async () => {
    setViewport(1440);
    const firstRender = renderShell();
    const shell = firstRender.container.querySelector<HTMLElement>(".geo-app-shell");

    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("expanded"));
    await userEvent.click(await screen.findByRole("button", { name: "收起为精简导航" }));
    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("compact"));
    expect(window.localStorage.getItem(WORKSPACE_NAVIGATION_PREFERENCE_KEY)).toBe("compact");
    expect(screen.queryByText("当前主体")).toBeTruthy();
    expect(screen.getByRole("button", { name: "展开完整导航" })).toBeTruthy();

    firstRender.unmount();
    const secondRender = renderShell();
    const restoredShell = secondRender.container.querySelector<HTMLElement>(".geo-app-shell");
    await waitFor(() => expect(restoredShell?.dataset.navigationMode).toBe("compact"));
  });

  it("中等宽度默认精简，悬浮只显示提示，点击后才打开二级菜单", async () => {
    setViewport(1024);
    pathname = "/geo/data-center/negative-index";
    renderShell();

    const dataCenter = await screen.findByRole("button", { name: "数据中心" });
    expect(screen.queryByRole("dialog", { name: "数据中心二级导航" })).toBeNull();
    await userEvent.hover(dataCenter);
    expect((await screen.findByRole("tooltip")).textContent).toContain("数据中心");
    expect(screen.queryByRole("dialog", { name: "数据中心二级导航" })).toBeNull();

    await userEvent.click(dataCenter);
    const flyout = await screen.findByRole("dialog", { name: "数据中心二级导航" });
    const activeLink = screen.getByRole("link", { name: "负面信息指数" });
    expect(activeLink.getAttribute("href")).toBe("/geo/data-center/negative-index");
    expect(activeLink.getAttribute("aria-current")).toBe("page");
    expect(flyout).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "优化中心" }));
    expect(screen.queryByRole("dialog", { name: "数据中心二级导航" })).toBeNull();
    expect(await screen.findByRole("dialog", { name: "优化中心二级导航" })).toBeTruthy();

    await userEvent.click(dataCenter);
    expect(await screen.findByRole("dialog", { name: "数据中心二级导航" })).toBeTruthy();
    await userEvent.click(screen.getByRole("link", { name: "负面信息指数" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "数据中心二级导航" })).toBeNull(),
    );

    await userEvent.click(dataCenter);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "数据中心二级导航" })).toBeNull(),
    );
    expect(document.activeElement).toBe(dataCenter);
  });

  it("专注模式隐藏侧栏，以覆盖抽屉打开并按两次 Esc 恢复原状态", async () => {
    setViewport(1920);
    const view = renderShell();
    const shell = view.container.querySelector<HTMLElement>(".geo-app-shell");
    const content = view.container.querySelector<HTMLElement>(".geo-app-shell__content");

    await userEvent.click(await screen.findByRole("button", { name: "进入大屏展示" }));
    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("focus"));
    expect(shell?.style.getPropertyValue("--sidebar-width")).toBe("0px");
    expect(screen.queryByRole("complementary")).toBeNull();

    const widthBeforeDrawer = content?.getBoundingClientRect().width;
    await userEvent.click(screen.getByRole("button", { name: "打开专注模式导航" }));
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(content?.getBoundingClientRect().width).toBe(widthBeforeDrawer);
    expect(shell?.style.getPropertyValue("--sidebar-width")).toBe("0px");

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(shell?.dataset.navigationMode).toBe("focus");
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("expanded"));
  });

  it("从精简状态进入专注后仍恢复精简状态", async () => {
    setViewport(1440);
    window.localStorage.setItem(WORKSPACE_NAVIGATION_PREFERENCE_KEY, "compact");
    const view = renderShell();
    const shell = view.container.querySelector<HTMLElement>(".geo-app-shell");
    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("compact"));

    await userEvent.click(await screen.findByRole("button", { name: "进入大屏展示" }));
    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("focus"));
    await userEvent.click(screen.getByRole("button", { name: "退出大屏展示" }));
    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("compact"));
  });

  it("手机默认隐藏侧栏，汉堡按钮打开覆盖抽屉并锁定底层滚动", async () => {
    setViewport(390);
    pathname = "/subjects/subject-1/keywords";
    const view = renderShell();
    const shell = view.container.querySelector<HTMLElement>(".geo-app-shell");

    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("mobile_drawer"));
    expect(shell?.style.getPropertyValue("--sidebar-width")).toBe("0px");
    expect(screen.queryByRole("complementary")).toBeNull();
    const trigger = await screen.findByRole("button", { name: "打开工作台导航" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    await userEvent.click(trigger);
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(document.querySelector<HTMLElement>(".geo-navigation-drawer")?.style.zIndex).toBe(
      "1300",
    );
    expect(document.body.style.overflow).toBe("hidden");
    expect(screen.getByRole("menuitem", { name: /智能关键词/ }).className).toContain(
      "ant-menu-item-selected",
    );
    expect(screen.getAllByLabelText("切换当前主体").length).toBeGreaterThan(1);

    await userEvent.click(screen.getByRole("button", { name: "关闭导航" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.body.style.overflow).toBe("");

    await userEvent.click(trigger);
    expect(await screen.findByRole("dialog")).toBeTruthy();
    const mask = document.querySelector<HTMLElement>(".ant-drawer-mask");
    expect(mask).toBeTruthy();
    fireEvent.click(mask!);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await userEvent.click(trigger);
    expect(await screen.findByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.body.style.overflow).toBe("");
  });

  it("767 像素进入手机抽屉，768 像素进入精简导航", async () => {
    setViewport(767);
    const view = renderShell();
    const shell = view.container.querySelector<HTMLElement>(".geo-app-shell");
    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("mobile_drawer"));

    setViewport(768);
    fireEvent(window, new Event("resize"));
    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("compact"));
    expect(await screen.findByRole("button", { name: "展开完整导航" })).toBeTruthy();
  });

  it("跨越移动端断点时关闭旧抽屉，返回手机宽度后不会自动重开", async () => {
    setViewport(390);
    const view = renderShell();
    const shell = view.container.querySelector<HTMLElement>(".geo-app-shell");
    const trigger = await screen.findByRole("button", { name: "打开工作台导航" });

    await userEvent.click(trigger);
    expect(await screen.findByRole("dialog")).toBeTruthy();

    setViewport(1024);
    fireEvent(window, new Event("resize"));
    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("compact"));
    expect(screen.queryByRole("dialog")).toBeNull();

    setViewport(390);
    fireEvent(window, new Event("resize"));
    await waitFor(() => expect(shell?.dataset.navigationMode).toBe("mobile_drawer"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(
      (await screen.findByRole("button", { name: "打开工作台导航" })).getAttribute("aria-expanded"),
    ).toBe("false");
  });
});
