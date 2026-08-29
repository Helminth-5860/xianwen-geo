// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  APPEARANCE_COOKIE_NAME,
  APPEARANCE_STORAGE_KEY,
  DEFAULT_APPEARANCE,
  parseAppearanceCookie,
  parseAppearanceStorage,
  serializeAppearanceStorage,
  type AppearancePreference,
} from "../components/theme/appearance";
import {
  APPEARANCE_ACCOUNT_SAVE_EVENT,
  AppThemeProvider,
  type AppearanceAccountSaveRequest,
  useAppTheme,
} from "../components/theme/app-theme-provider";
import { buildThemeBootstrapSource } from "../components/theme/theme-bootstrap-script";

type SchemeListener = (event: MediaQueryListEvent) => void;

function installMatchMedia(initiallyDark: boolean) {
  let matches = initiallyDark;
  const listeners = new Set<SchemeListener>();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({
      get matches() {
        return matches;
      },
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addEventListener: (_type: string, listener: SchemeListener) => listeners.add(listener),
      removeEventListener: (_type: string, listener: SchemeListener) => listeners.delete(listener),
      addListener: (listener: SchemeListener) => listeners.add(listener),
      removeListener: (listener: SchemeListener) => listeners.delete(listener),
      dispatchEvent: () => true,
    }),
  });
  return {
    change(nextDark: boolean) {
      matches = nextDark;
      const event = { matches: nextDark } as MediaQueryListEvent;
      listeners.forEach((listener) => listener(event));
    },
  };
}

function ThemeProbe() {
  const theme = useAppTheme();
  return (
    <div>
      <output data-testid="theme-state">
        {theme.mode}:{theme.accent}:{theme.effectiveMode}:{theme.savedAppearance.mode}:
        {theme.savedAppearance.accent}
      </output>
      <button
        type="button"
        onClick={() => theme.previewAppearance({ mode: "dark", accent: "purple" })}
      >
        预览
      </button>
      <button type="button" onClick={theme.resetPreview}>
        取消预览
      </button>
      <button
        type="button"
        onClick={() => {
          void theme.saveAppearance({ mode: "dark", accent: "green" }).catch(() => undefined);
        }}
      >
        保存
      </button>
    </div>
  );
}

function renderTheme(initialAppearance: AppearancePreference = DEFAULT_APPEARANCE) {
  return render(
    <AppThemeProvider initialAppearance={initialAppearance} initialResolvedTheme="light">
      <ThemeProbe />
    </AppThemeProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  document.cookie = `${APPEARANCE_COOKIE_NAME}=; Path=/; Max-Age=0`;
  document.documentElement.removeAttribute("data-appearance-mode");
  document.documentElement.removeAttribute("data-resolved-theme");
  document.documentElement.removeAttribute("data-color-theme");
  document.documentElement.removeAttribute("data-theme-ready");
  installMatchMedia(false);
});

afterEach(() => cleanup());

describe("外观偏好数据边界", () => {
  it("只接受当前版本和白名单值", () => {
    expect(DEFAULT_APPEARANCE).toEqual({ mode: "system", accent: "blue" });
    expect(parseAppearanceStorage('{"version":1,"mode":"dark","accent":"orange"}')).toEqual({
      mode: "dark",
      accent: "orange",
    });
    expect(parseAppearanceStorage('{"version":1,"mode":"dark","accent":"danger"}')).toBeNull();
    expect(parseAppearanceStorage('{"version":2,"mode":"dark","accent":"orange"}')).toBeNull();
    expect(parseAppearanceCookie("v1:system:green:dark")).toEqual({
      appearance: { mode: "system", accent: "green" },
      resolvedTheme: "dark",
    });
  });

  it("首屏脚本读取白名单内的本地偏好并在主题不同时等待容器就绪", () => {
    installMatchMedia(true);
    window.localStorage.setItem(
      APPEARANCE_STORAGE_KEY,
      serializeAppearanceStorage({ mode: "light", accent: "orange" }),
    );
    const source = buildThemeBootstrapSource({
      initialAppearance: DEFAULT_APPEARANCE,
      initialResolvedTheme: "light",
    });

    Function(source)();

    expect(document.documentElement.dataset.appearanceMode).toBe("light");
    expect(document.documentElement.dataset.resolvedTheme).toBe("light");
    expect(document.documentElement.dataset.colorTheme).toBe("orange");
    expect(document.documentElement.dataset.themeReady).toBe("false");
    expect(document.cookie).toContain(`${APPEARANCE_COOKIE_NAME}=`);
  });

  it("首屏主题与服务端一致时直接显示，并忽略非白名单存储", () => {
    window.localStorage.setItem(
      APPEARANCE_STORAGE_KEY,
      '{"version":1,"mode":"dark","accent":"danger"}',
    );
    const source = buildThemeBootstrapSource({
      initialAppearance: { mode: "light", accent: "blue" },
      initialResolvedTheme: "light",
    });

    Function(source)();

    expect(document.documentElement.dataset.appearanceMode).toBe("light");
    expect(document.documentElement.dataset.resolvedTheme).toBe("light");
    expect(document.documentElement.dataset.colorTheme).toBe("blue");
    expect(document.documentElement.dataset.themeReady).toBe("true");
  });
});

describe("全局外观容器", () => {
  it("支持即时预览、取消预览和保存", async () => {
    renderTheme({ mode: "light", accent: "blue" });

    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    expect(screen.getByTestId("theme-state").textContent).toBe("dark:purple:dark:light:blue");
    expect(document.documentElement.dataset.colorTheme).toBe("purple");

    fireEvent.click(screen.getByRole("button", { name: "取消预览" }));
    expect(screen.getByTestId("theme-state").textContent).toBe("light:blue:light:light:blue");

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(screen.getByTestId("theme-state").textContent).toBe("dark:green:dark:dark:green"),
    );
    expect(parseAppearanceStorage(window.localStorage.getItem(APPEARANCE_STORAGE_KEY))).toEqual({
      mode: "dark",
      accent: "green",
    });
  });

  it("本地偏好与服务端初始值不同时采用本地实际模式并在重绘后显示", async () => {
    window.localStorage.setItem(
      APPEARANCE_STORAGE_KEY,
      serializeAppearanceStorage({ mode: "dark", accent: "orange" }),
    );
    document.documentElement.dataset.appearanceMode = "dark";
    document.documentElement.dataset.resolvedTheme = "dark";
    document.documentElement.dataset.colorTheme = "orange";
    document.documentElement.dataset.themeReady = "false";

    renderTheme({ mode: "light", accent: "blue" });

    await waitFor(() =>
      expect(screen.getByTestId("theme-state").textContent).toBe("dark:orange:dark:dark:orange"),
    );
    expect(document.documentElement.dataset.themeReady).toBe("true");
  });

  it("跟随系统的首屏实际模式变化后等待正确主题重绘再显示", async () => {
    installMatchMedia(true);
    Function(
      buildThemeBootstrapSource({
        initialAppearance: DEFAULT_APPEARANCE,
        initialResolvedTheme: "light",
      }),
    )();
    expect(document.documentElement.dataset.themeReady).toBe("false");

    renderTheme();

    await waitFor(() =>
      expect(screen.getByTestId("theme-state").textContent).toBe("system:blue:dark:system:blue"),
    );
    expect(document.documentElement.dataset.themeReady).toBe("true");
  });

  it("跟随系统时实时响应系统深浅色变化", () => {
    const media = installMatchMedia(false);
    renderTheme();
    expect(screen.getByTestId("theme-state").textContent).toBe("system:blue:light:system:blue");

    act(() => media.change(true));

    expect(screen.getByTestId("theme-state").textContent).toBe("system:blue:dark:system:blue");
    expect(document.documentElement.dataset.resolvedTheme).toBe("dark");
  });

  it("账号同步失败时回滚到保存前的外观", async () => {
    const rejectSave = (event: Event) => {
      const detail = (event as CustomEvent<AppearanceAccountSaveRequest>).detail;
      detail.respondWith(Promise.reject(new Error("保存失败")));
    };
    window.addEventListener(APPEARANCE_ACCOUNT_SAVE_EVENT, rejectSave);
    renderTheme({ mode: "light", accent: "blue" });

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() =>
      expect(screen.getByTestId("theme-state").textContent).toBe("light:blue:light:light:blue"),
    );
    window.removeEventListener(APPEARANCE_ACCOUNT_SAVE_EVENT, rejectSave);
  });

  it("其他标签页保存后同步当前页面", async () => {
    renderTheme({ mode: "light", accent: "blue" });
    const next = serializeAppearanceStorage({ mode: "dark", accent: "orange" });

    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: APPEARANCE_STORAGE_KEY,
          newValue: next,
        }),
      );
    });

    await waitFor(() =>
      expect(screen.getByTestId("theme-state").textContent).toBe("dark:orange:dark:dark:orange"),
    );
  });
});
