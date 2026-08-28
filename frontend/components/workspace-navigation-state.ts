export const MOBILE_NAVIGATION_BREAKPOINT = 768;
export const EXPANDED_NAVIGATION_BREAKPOINT = 1280;
export const WORKSPACE_NAVIGATION_PREFERENCE_KEY = "xianwen.workspace.navigation.v1";

export type DesktopNavigationMode = "expanded" | "compact";
export type WorkspaceNavigationMode = DesktopNavigationMode | "focus" | "mobile_drawer";

export function parseDesktopNavigationPreference(value: string | null) {
  return value === "expanded" || value === "compact" ? value : null;
}

export function defaultDesktopNavigationMode(viewportWidth: number): DesktopNavigationMode {
  return viewportWidth >= EXPANDED_NAVIGATION_BREAKPOINT ? "expanded" : "compact";
}

export function resolveWorkspaceNavigationMode({
  viewportWidth,
  desktopPreference,
  temporaryDesktopMode,
  focus,
}: Readonly<{
  viewportWidth: number;
  desktopPreference: DesktopNavigationMode | null;
  temporaryDesktopMode: DesktopNavigationMode | null;
  focus: boolean;
}>): WorkspaceNavigationMode {
  if (viewportWidth < MOBILE_NAVIGATION_BREAKPOINT) return "mobile_drawer";
  if (focus) return "focus";
  return temporaryDesktopMode ?? desktopPreference ?? defaultDesktopNavigationMode(viewportWidth);
}

export function workspaceSidebarWidth(mode: WorkspaceNavigationMode) {
  if (mode === "expanded") return "240px";
  if (mode === "compact") return "68px";
  return "0px";
}
