import type { ThemeConfig } from "antd";

export const XW_THEME_COLORS = Object.freeze({
  background: "#f3f6fb",
  surface: "#ffffff",
  surfaceSubtle: "#f8fafd",
  text: "#172033",
  textSecondary: "#536178",
  border: "#dfe6f0",
  primary: "#2468d8",
  primarySoft: "#eaf2ff",
  positive: "#25835a",
  positiveSoft: "#e8f5ee",
  warning: "#b66a19",
  warningSoft: "#fff2df",
  danger: "#c14d56",
  dangerSoft: "#fcebed",
  insight: "#7659c7",
  insightSoft: "#f0ecfb",
});

export const xwTheme: ThemeConfig = {
  token: {
    colorPrimary: XW_THEME_COLORS.primary,
    colorInfo: XW_THEME_COLORS.primary,
    colorSuccess: XW_THEME_COLORS.positive,
    colorWarning: XW_THEME_COLORS.warning,
    colorError: XW_THEME_COLORS.danger,
    colorBgLayout: XW_THEME_COLORS.background,
    colorBgContainer: XW_THEME_COLORS.surface,
    colorFillAlter: XW_THEME_COLORS.surfaceSubtle,
    colorText: XW_THEME_COLORS.text,
    colorTextSecondary: XW_THEME_COLORS.textSecondary,
    colorBorder: XW_THEME_COLORS.border,
    colorBorderSecondary: XW_THEME_COLORS.border,
    borderRadius: 10,
    borderRadiusLG: 14,
    controlHeight: 40,
    fontFamily:
      'Inter, "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, BlinkMacSystemFont, sans-serif',
    boxShadowSecondary: "0 18px 48px rgb(37 61 99 / 10%)",
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
      headerFontSize: 17,
      paddingLG: 20,
    },
    Menu: {
      itemBorderRadius: 10,
      itemSelectedBg: XW_THEME_COLORS.primarySoft,
      itemSelectedColor: XW_THEME_COLORS.primary,
    },
    Table: {
      headerBg: XW_THEME_COLORS.surfaceSubtle,
      headerColor: XW_THEME_COLORS.textSecondary,
      borderColor: XW_THEME_COLORS.border,
    },
  },
};

export const XW_THEME = xwTheme;
