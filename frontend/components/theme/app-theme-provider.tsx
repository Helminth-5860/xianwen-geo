"use client";

import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { buildXwTheme } from "@/components/xw/xw-theme";

import {
  APPEARANCE_COOKIE_MAX_AGE,
  APPEARANCE_COOKIE_NAME,
  APPEARANCE_STORAGE_KEY,
  DEFAULT_APPEARANCE,
  appearanceEquals,
  isResolvedTheme,
  normalizeAppearance,
  parseAppearanceStorage,
  resolveAppearanceMode,
  serializeAppearanceCookie,
  serializeAppearanceStorage,
  type AppearancePreference,
  type ResolvedTheme,
} from "./appearance";

export const APPEARANCE_ACCOUNT_SAVE_EVENT = "xw:appearance:account-save";

export type AppearanceAccountSaveRequest = {
  readonly appearance: AppearancePreference;
  respondWith: (
    response: Promise<AppearancePreference | void> | AppearancePreference | void,
  ) => void;
};

export type AppThemeValue = Readonly<{
  mode: AppearancePreference["mode"];
  accent: AppearancePreference["accent"];
  effectiveMode: ResolvedTheme;
  savedAppearance: AppearancePreference;
  previewAppearance: (next: AppearancePreference) => void;
  saveAppearance: (next: AppearancePreference) => Promise<void>;
  resetPreview: () => void;
}>;

type ThemeControllerValue = AppThemeValue &
  Readonly<{
    syncFromAccount: (next: AppearancePreference) => void;
  }>;

type AppThemeProviderProps = Readonly<{
  children: ReactNode;
  initialAppearance?: AppearancePreference;
  initialResolvedTheme?: ResolvedTheme;
}>;

const AppThemeContext = createContext<ThemeControllerValue | null>(null);

function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

function resolveForBrowser(appearance: AppearancePreference): ResolvedTheme {
  return resolveAppearanceMode(appearance.mode, systemPrefersDark());
}

function applyDocumentAppearance(
  appearance: AppearancePreference,
  resolvedTheme: ResolvedTheme,
): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.appearanceMode = appearance.mode;
  root.dataset.resolvedTheme = resolvedTheme;
  root.dataset.colorTheme = appearance.accent;
  root.style.colorScheme = resolvedTheme;
}

function writeAppearanceCookie(
  appearance: AppearancePreference,
  resolvedTheme: ResolvedTheme,
): void {
  if (typeof document === "undefined") return;
  try {
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${APPEARANCE_COOKIE_NAME}=${encodeURIComponent(
      serializeAppearanceCookie(appearance, resolvedTheme),
    )}; Path=/; Max-Age=${APPEARANCE_COOKIE_MAX_AGE}; SameSite=Lax${secure}`;
  } catch {
    // 浏览器禁用非必要存储时，当前页面仍可继续使用主题。
  }
}

function persistAppearance(appearance: AppearancePreference, resolvedTheme: ResolvedTheme): void {
  try {
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, serializeAppearanceStorage(appearance));
  } catch {
    // 隐私模式或存储空间不可用时，保留当前会话中的主题。
  }
  writeAppearanceCookie(appearance, resolvedTheme);
}

async function requestAccountSave(appearance: AppearancePreference): Promise<AppearancePreference> {
  if (typeof window === "undefined") return appearance;
  let response: Promise<AppearancePreference | void> | null = null;
  const detail: AppearanceAccountSaveRequest = {
    appearance,
    respondWith(nextResponse) {
      if (response === null) response = Promise.resolve(nextResponse);
    },
  };
  window.dispatchEvent(
    new CustomEvent<AppearanceAccountSaveRequest>(APPEARANCE_ACCOUNT_SAVE_EVENT, { detail }),
  );
  const synchronized = response ? await response : undefined;
  return synchronized ? normalizeAppearance(synchronized, appearance) : appearance;
}

export function AppThemeProvider({
  children,
  initialAppearance = DEFAULT_APPEARANCE,
  initialResolvedTheme = resolveAppearanceMode(initialAppearance.mode, false),
}: AppThemeProviderProps) {
  const normalizedInitial = useMemo(
    () => normalizeAppearance(initialAppearance),
    [initialAppearance],
  );
  const [savedAppearance, setSavedAppearance] = useState<AppearancePreference>(normalizedInitial);
  const [activeAppearance, setActiveAppearance] = useState<AppearancePreference>(normalizedInitial);
  const [effectiveMode, setEffectiveMode] = useState<ResolvedTheme>(initialResolvedTheme);
  const savedRef = useRef(savedAppearance);
  const activeRef = useRef(activeAppearance);
  const saveSequence = useRef(0);

  const activate = useCallback((next: AppearancePreference, resolved?: ResolvedTheme) => {
    const normalized = normalizeAppearance(next);
    const effective = resolved ?? resolveForBrowser(normalized);
    activeRef.current = normalized;
    setActiveAppearance(normalized);
    setEffectiveMode(effective);
    applyDocumentAppearance(normalized, effective);
    return effective;
  }, []);

  const commitLocal = useCallback(
    (next: AppearancePreference, resolved?: ResolvedTheme) => {
      const normalized = normalizeAppearance(next);
      const effective = activate(normalized, resolved);
      savedRef.current = normalized;
      setSavedAppearance(normalized);
      persistAppearance(normalized, effective);
    },
    [activate],
  );

  useLayoutEffect(() => {
    let stored: AppearancePreference | null = null;
    try {
      stored = parseAppearanceStorage(window.localStorage.getItem(APPEARANCE_STORAGE_KEY));
    } catch {
      stored = null;
    }
    const bootstrapped = stored ?? normalizedInitial;
    const root = document.documentElement;
    const rootResolved = document.documentElement.dataset.resolvedTheme;
    const rootMatchesAppearance =
      root.dataset.appearanceMode === bootstrapped.mode &&
      root.dataset.colorTheme === bootstrapped.accent;
    const resolved =
      rootMatchesAppearance && isResolvedTheme(rootResolved)
        ? rootResolved
        : resolveForBrowser(bootstrapped);
    savedRef.current = bootstrapped;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 首屏脚本已在绘制前更新根节点，此处须在布局阶段让 React 状态与其一致。
    setSavedAppearance(bootstrapped);
    activate(bootstrapped, resolved);
  }, [activate, normalizedInitial]);

  useLayoutEffect(() => {
    const root = document.documentElement;
    if (root.dataset.themeReady !== "false") return;
    const themeHasRendered =
      root.dataset.appearanceMode === activeAppearance.mode &&
      root.dataset.colorTheme === activeAppearance.accent &&
      root.dataset.resolvedTheme === effectiveMode;
    if (themeHasRendered) root.dataset.themeReady = "true";
  }, [activeAppearance.accent, activeAppearance.mode, effectiveMode]);

  useEffect(() => {
    const receiveStoredAppearance = (rawValue: string | null) => {
      const next = parseAppearanceStorage(rawValue);
      if (!next) return;
      commitLocal(next);
    };
    const handleStorage = (event: StorageEvent) => {
      if (event.key === APPEARANCE_STORAGE_KEY) receiveStoredAppearance(event.newValue);
    };
    const handlePageShow = () => {
      try {
        receiveStoredAppearance(window.localStorage.getItem(APPEARANCE_STORAGE_KEY));
      } catch {
        // 页面从浏览器缓存恢复时，存储不可用不影响当前主题。
      }
    };
    window.addEventListener("storage", handleStorage);
    window.addEventListener("pageshow", handlePageShow);
    return () => {
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener("pageshow", handlePageShow);
    };
  }, [commitLocal]);

  useEffect(() => {
    if (activeAppearance.mode !== "system" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (event: MediaQueryListEvent) => {
      const nextResolved = event.matches ? "dark" : "light";
      activate(activeRef.current, nextResolved);
      if (appearanceEquals(activeRef.current, savedRef.current)) {
        writeAppearanceCookie(savedRef.current, nextResolved);
      }
    };
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, [activate, activeAppearance.mode]);

  const previewAppearance = useCallback(
    (next: AppearancePreference) => {
      activate(normalizeAppearance(next, activeRef.current));
    },
    [activate],
  );

  const resetPreview = useCallback(() => {
    activate(savedRef.current);
  }, [activate]);

  const saveAppearance = useCallback(
    async (next: AppearancePreference) => {
      const normalized = normalizeAppearance(next, activeRef.current);
      const previousSaved = savedRef.current;
      const sequence = ++saveSequence.current;
      activate(normalized);
      try {
        const synchronized = await requestAccountSave(normalized);
        if (sequence !== saveSequence.current) return;
        commitLocal(synchronized);
      } catch (error) {
        if (sequence === saveSequence.current) commitLocal(previousSaved);
        throw error;
      }
    },
    [activate, commitLocal],
  );

  const syncFromAccount = useCallback(
    (next: AppearancePreference) => {
      const normalized = normalizeAppearance(next, savedRef.current);
      if (appearanceEquals(normalized, savedRef.current)) return;
      const hadPreview = !appearanceEquals(activeRef.current, savedRef.current);
      savedRef.current = normalized;
      setSavedAppearance(normalized);
      const resolved = resolveForBrowser(normalized);
      persistAppearance(normalized, resolved);
      if (!hadPreview) activate(normalized, resolved);
    },
    [activate],
  );

  const themeConfig = useMemo(
    () => buildXwTheme(effectiveMode, activeAppearance.accent),
    [activeAppearance.accent, effectiveMode],
  );
  const value = useMemo<ThemeControllerValue>(
    () => ({
      mode: activeAppearance.mode,
      accent: activeAppearance.accent,
      effectiveMode,
      savedAppearance,
      previewAppearance,
      saveAppearance,
      resetPreview,
      syncFromAccount,
    }),
    [
      activeAppearance.accent,
      activeAppearance.mode,
      effectiveMode,
      previewAppearance,
      resetPreview,
      saveAppearance,
      savedAppearance,
      syncFromAccount,
    ],
  );

  return (
    <AppThemeContext.Provider value={value}>
      <ConfigProvider locale={zhCN} theme={themeConfig}>
        {children}
      </ConfigProvider>
    </AppThemeContext.Provider>
  );
}

function useThemeController(): ThemeControllerValue {
  const value = useContext(AppThemeContext);
  if (!value) throw new Error("主题功能需要在应用主题容器内使用");
  return value;
}

export function useAppTheme(): AppThemeValue {
  return useThemeController();
}

export function useThemeAccountController() {
  const { syncFromAccount } = useThemeController();
  return syncFromAccount;
}

export type { AppearanceMode, AppearancePreference, ColorTheme, ResolvedTheme } from "./appearance";
