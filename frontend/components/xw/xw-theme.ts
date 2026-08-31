import { theme as antdTheme, type ThemeConfig } from "antd";

import type { ColorTheme, ResolvedTheme } from "@/components/theme/appearance";

const ACCENT_COLORS: Record<
  ResolvedTheme,
  Record<ColorTheme, Readonly<{ primary: string; primarySoft: string; primaryStrong: string }>>
> = {
  light: {
    blue: { primary: "#2f76df", primarySoft: "rgb(222 238 255 / 66%)", primaryStrong: "#245db6" },
    green: { primary: "#147a68", primarySoft: "#e7f6f1", primaryStrong: "#0d5f52" },
    purple: { primary: "#6d4fd1", primarySoft: "#f0ecfb", primaryStrong: "#5536b8" },
    orange: { primary: "#b9500d", primarySoft: "#fff0e3", primaryStrong: "#923b06" },
  },
  dark: {
    blue: { primary: "#6ea8ff", primarySoft: "#1c3154", primaryStrong: "#9cc3ff" },
    green: { primary: "#4bd1b2", primarySoft: "#173b37", primaryStrong: "#7be2ca" },
    purple: { primary: "#a78bfa", primarySoft: "#302752", primaryStrong: "#c5b4ff" },
    orange: { primary: "#fb9a4b", primarySoft: "#4b2c1c", primaryStrong: "#ffc18c" },
  },
};

const BASE_COLORS = {
  light: {
    background: "#f3f7fd",
    surface: "rgb(255 255 255 / 72%)",
    surfaceSubtle: "rgb(247 250 255 / 64%)",
    surfaceElevated: "rgb(255 255 255 / 90%)",
    text: "#172033",
    textSecondary: "#536178",
    textTertiary: "#7c899d",
    border: "rgb(150 177 214 / 30%)",
    borderStrong: "rgb(126 157 199 / 42%)",
    positive: "#25835a",
    warning: "#b66a19",
    danger: "#c14d56",
    shadow: "0 22px 64px rgb(46 78 122 / 10%)",
  },
  dark: {
    background: "#0b1220",
    surface: "#111b2e",
    surfaceSubtle: "#162238",
    surfaceElevated: "#18253c",
    text: "#edf3ff",
    textSecondary: "#b4c1d4",
    textTertiary: "#8493a9",
    border: "#2a3850",
    borderStrong: "#3a4a64",
    positive: "#59d39b",
    warning: "#f3ad62",
    danger: "#ff8a95",
    shadow: "0 20px 52px rgb(0 0 0 / 34%)",
  },
} as const;

export const XW_THEME_COLORS = Object.freeze({
  ...BASE_COLORS.light,
  primary: ACCENT_COLORS.light.blue.primary,
  primarySoft: ACCENT_COLORS.light.blue.primarySoft,
  insight: "#7659c7",
  insightSoft: "#f0ecfb",
});

export function buildXwTheme(resolvedTheme: ResolvedTheme, colorTheme: ColorTheme): ThemeConfig {
  const base = BASE_COLORS[resolvedTheme];
  const accent = ACCENT_COLORS[resolvedTheme][colorTheme];
  const dark = resolvedTheme === "dark";

  return {
    algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    cssVar: { prefix: "xw-ant", key: `${resolvedTheme}-${colorTheme}` },
    token: {
      colorPrimary: accent.primary,
      colorInfo: accent.primary,
      colorLink: accent.primary,
      colorLinkHover: accent.primaryStrong,
      colorSuccess: base.positive,
      colorWarning: base.warning,
      colorError: base.danger,
      colorBgBase: base.background,
      colorBgLayout: base.background,
      colorBgContainer: base.surface,
      colorBgElevated: base.surfaceElevated,
      colorFillAlter: base.surfaceSubtle,
      colorFillSecondary: dark ? "rgb(255 255 255 / 8%)" : "rgb(23 32 51 / 6%)",
      colorText: base.text,
      colorTextSecondary: base.textSecondary,
      colorTextTertiary: base.textTertiary,
      colorBorder: base.border,
      colorBorderSecondary: base.border,
      borderRadius: 12,
      borderRadiusLG: 18,
      controlHeight: 40,
      fontFamily:
        'Inter, "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, BlinkMacSystemFont, sans-serif',
      boxShadow: base.shadow,
      boxShadowSecondary: base.shadow,
      motionDurationFast: "0.17s",
      motionDurationMid: "0.22s",
      motionEaseInOut: "cubic-bezier(0.2, 0.8, 0.2, 1)",
    },
    components: {
      Button: {
        controlHeight: 40,
        fontWeight: 600,
        primaryShadow: "none",
      },
      Card: {
        colorBgContainer: base.surface,
        colorBorderSecondary: base.border,
        headerBg: "transparent",
        headerFontSize: 17,
        paddingLG: 20,
      },
      Drawer: {
        colorBgElevated: base.surfaceElevated,
      },
      Input: {
        colorBgContainer: base.surface,
        activeBorderColor: accent.primary,
        hoverBorderColor: accent.primary,
      },
      Menu: {
        itemBg: "transparent",
        subMenuItemBg: "transparent",
        itemBorderRadius: 10,
        itemSelectedBg: accent.primarySoft,
        itemSelectedColor: accent.primaryStrong,
        itemHoverBg: accent.primarySoft,
        itemHoverColor: accent.primaryStrong,
      },
      Modal: {
        contentBg: base.surfaceElevated,
        headerBg: base.surfaceElevated,
      },
      Select: {
        colorBgContainer: base.surface,
        optionSelectedBg: accent.primarySoft,
      },
      Table: {
        colorBgContainer: base.surface,
        headerBg: base.surfaceSubtle,
        headerColor: base.textSecondary,
        borderColor: base.border,
        rowHoverBg: accent.primarySoft,
      },
      Tooltip: {
        colorBgSpotlight: dark ? "#263550" : "#172033",
      },
    },
  };
}

export const xwTheme: ThemeConfig = buildXwTheme("light", "blue");
export const XW_THEME = xwTheme;
