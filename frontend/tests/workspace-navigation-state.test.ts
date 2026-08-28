import { describe, expect, it } from "vitest";

import {
  defaultDesktopNavigationMode,
  parseDesktopNavigationPreference,
  resolveWorkspaceNavigationMode,
  workspaceSidebarWidth,
} from "../components/workspace-navigation-state";

describe("工作台响应式导航状态", () => {
  it("在 768 和 1280 边界选择正确的默认状态", () => {
    expect(
      resolveWorkspaceNavigationMode({
        viewportWidth: 767,
        desktopPreference: "expanded",
        temporaryDesktopMode: null,
        focus: true,
      }),
    ).toBe("mobile_drawer");
    expect(defaultDesktopNavigationMode(768)).toBe("compact");
    expect(defaultDesktopNavigationMode(1279)).toBe("compact");
    expect(defaultDesktopNavigationMode(1280)).toBe("expanded");
  });

  it("只接受展开或精简两种持久偏好", () => {
    expect(parseDesktopNavigationPreference("expanded")).toBe("expanded");
    expect(parseDesktopNavigationPreference("compact")).toBe("compact");
    expect(parseDesktopNavigationPreference("focus")).toBeNull();
    expect(parseDesktopNavigationPreference("mobile_drawer")).toBeNull();
    expect(parseDesktopNavigationPreference("unexpected")).toBeNull();
    expect(parseDesktopNavigationPreference(null)).toBeNull();
  });

  it("桌面偏好、临时恢复状态和专注状态按优先级生效", () => {
    expect(
      resolveWorkspaceNavigationMode({
        viewportWidth: 1024,
        desktopPreference: "expanded",
        temporaryDesktopMode: null,
        focus: false,
      }),
    ).toBe("expanded");
    expect(
      resolveWorkspaceNavigationMode({
        viewportWidth: 1920,
        desktopPreference: "expanded",
        temporaryDesktopMode: "compact",
        focus: false,
      }),
    ).toBe("compact");
    expect(
      resolveWorkspaceNavigationMode({
        viewportWidth: 1920,
        desktopPreference: "compact",
        temporaryDesktopMode: null,
        focus: true,
      }),
    ).toBe("focus");
  });

  it("四种状态映射为统一的侧栏宽度", () => {
    expect(workspaceSidebarWidth("expanded")).toBe("240px");
    expect(workspaceSidebarWidth("compact")).toBe("68px");
    expect(workspaceSidebarWidth("focus")).toBe("0px");
    expect(workspaceSidebarWidth("mobile_drawer")).toBe("0px");
  });
});
