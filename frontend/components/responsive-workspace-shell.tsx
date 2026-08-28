"use client";

import { FullscreenExitOutlined, FullscreenOutlined, MenuOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { usePathname } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import {
  SubjectWorkspaceTopbar,
  useSubjectWorkspace,
} from "@/components/subject-workspace-context";
import { UserWorkspaceNavigation } from "@/components/user-workspace-navigation";
import {
  MOBILE_NAVIGATION_BREAKPOINT,
  WORKSPACE_NAVIGATION_PREFERENCE_KEY,
  defaultDesktopNavigationMode,
  parseDesktopNavigationPreference,
  resolveWorkspaceNavigationMode,
  workspaceSidebarWidth,
  type DesktopNavigationMode,
} from "@/components/workspace-navigation-state";

type NavigationShellStyle = CSSProperties & { "--sidebar-width": string };

export function ResponsiveWorkspaceShell({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const { active } = useSubjectWorkspace();
  const [viewportWidth, setViewportWidth] = useState(1280);
  const [desktopPreference, setDesktopPreference] = useState<DesktopNavigationMode | null>(null);
  const [temporaryDesktopMode, setTemporaryDesktopMode] = useState<DesktopNavigationMode | null>(
    null,
  );
  const [focus, setFocus] = useState(false);
  const [drawerState, setDrawerState] = useState<{ pathname: string; open: boolean }>({
    pathname,
    open: false,
  });
  const preFocusMode = useRef<DesktopNavigationMode>("expanded");
  const drawerOpen = drawerState.pathname === pathname && drawerState.open;
  const setDrawerOpen = useCallback(
    (open: boolean) => setDrawerState({ pathname, open }),
    [pathname],
  );

  useEffect(() => {
    const updateViewport = () => {
      setViewportWidth(window.innerWidth);
      setTemporaryDesktopMode(null);
      setDrawerState((current) => (current.open ? { ...current, open: false } : current));
      if (window.innerWidth < MOBILE_NAVIGATION_BREAKPOINT) setFocus(false);
    };
    const closeDrawerForHistoryNavigation = () => {
      setDrawerState((current) => (current.open ? { ...current, open: false } : current));
    };
    const timer = window.setTimeout(() => {
      setDesktopPreference(
        parseDesktopNavigationPreference(
          window.localStorage.getItem(WORKSPACE_NAVIGATION_PREFERENCE_KEY),
        ),
      );
      updateViewport();
    }, 0);
    window.addEventListener("resize", updateViewport);
    window.addEventListener("popstate", closeDrawerForHistoryNavigation);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("resize", updateViewport);
      window.removeEventListener("popstate", closeDrawerForHistoryNavigation);
    };
  }, []);

  const mode = resolveWorkspaceNavigationMode({
    viewportWidth,
    desktopPreference,
    temporaryDesktopMode,
    focus,
  });
  const desktopMode: DesktopNavigationMode =
    mode === "expanded" || mode === "compact"
      ? mode
      : (temporaryDesktopMode ?? desktopPreference ?? defaultDesktopNavigationMode(viewportWidth));

  const selectDesktopMode = useCallback((nextMode: DesktopNavigationMode) => {
    setTemporaryDesktopMode(null);
    setDesktopPreference(nextMode);
    window.localStorage.setItem(WORKSPACE_NAVIGATION_PREFERENCE_KEY, nextMode);
  }, []);

  const enterFocus = useCallback(() => {
    if (viewportWidth < MOBILE_NAVIGATION_BREAKPOINT) return;
    preFocusMode.current = desktopMode;
    setDrawerOpen(false);
    setFocus(true);
  }, [desktopMode, setDrawerOpen, viewportWidth]);

  const exitFocus = useCallback(() => {
    setDrawerOpen(false);
    setFocus(false);
    setTemporaryDesktopMode(preFocusMode.current);
  }, [setDrawerOpen]);

  useEffect(() => {
    if (!drawerOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [drawerOpen]);

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (drawerOpen) {
        setDrawerOpen(false);
        return;
      }
      if (focus && viewportWidth >= MOBILE_NAVIGATION_BREAKPOINT) exitFocus();
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [drawerOpen, exitFocus, focus, setDrawerOpen, viewportWidth]);

  const shellStyle: NavigationShellStyle = {
    "--sidebar-width": active ? workspaceSidebarWidth(mode) : "0px",
  };

  const mobileTrigger =
    mode === "mobile_drawer" ? (
      <Button
        className="subject-workspace-topbar__navigation-trigger"
        type="text"
        icon={<MenuOutlined />}
        aria-label="打开工作台导航"
        aria-expanded={drawerOpen}
        onClick={() => setDrawerOpen(true)}
      />
    ) : undefined;

  const focusControl =
    mode === "mobile_drawer" ? undefined : (
      <Button
        className="subject-workspace-topbar__focus-control"
        type="text"
        icon={mode === "focus" ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
        aria-label={mode === "focus" ? "退出大屏展示" : "进入大屏展示"}
        onClick={mode === "focus" ? exitFocus : enterFocus}
      >
        {mode === "focus" ? "退出大屏" : "大屏展示"}
      </Button>
    );

  return (
    <div className="geo-app-shell" data-navigation-mode={mode} style={shellStyle}>
      <UserWorkspaceNavigation
        mode={mode}
        drawerOpen={drawerOpen}
        onCollapse={() => selectDesktopMode("compact")}
        onExpand={() => selectDesktopMode("expanded")}
        onDrawerOpen={() => setDrawerOpen(true)}
        onDrawerClose={() => setDrawerOpen(false)}
      />
      <div className="geo-app-shell__content">
        <SubjectWorkspaceTopbar navigationTrigger={mobileTrigger} focusControl={focusControl} />
        {children}
      </div>
    </div>
  );
}
