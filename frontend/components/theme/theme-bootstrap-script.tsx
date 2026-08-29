import Script from "next/script";

import {
  APPEARANCE_COOKIE_MAX_AGE,
  APPEARANCE_COOKIE_NAME,
  APPEARANCE_STORAGE_KEY,
  type AppearancePreference,
  type ResolvedTheme,
} from "./appearance";

type ThemeBootstrapScriptProps = Readonly<{
  initialAppearance: AppearancePreference;
  initialResolvedTheme: ResolvedTheme;
}>;

export function buildThemeBootstrapSource({
  initialAppearance,
  initialResolvedTheme,
}: ThemeBootstrapScriptProps): string {
  const initial = JSON.stringify({
    mode: initialAppearance.mode,
    accent: initialAppearance.accent,
    resolvedTheme: initialResolvedTheme,
  });

  return `
(function () {
  var initial = ${initial};
  var preference = { mode: initial.mode, accent: initial.accent };
  var modes = { light: true, dark: true, system: true };
  var accents = { blue: true, green: true, purple: true, orange: true };
  try {
    var raw = window.localStorage.getItem(${JSON.stringify(APPEARANCE_STORAGE_KEY)});
    if (raw) {
      var stored = JSON.parse(raw);
      if (stored && stored.version === 1 && modes[stored.mode] && accents[stored.accent]) {
        preference = { mode: stored.mode, accent: stored.accent };
      }
    }
  } catch (_) {}

  var resolved = preference.mode === "system"
    ? (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : preference.mode;
  if (preference.mode === initial.mode && preference.mode === "system" && !window.matchMedia) {
    resolved = initial.resolvedTheme;
  }

  var root = document.documentElement;
  var differsFromServer = preference.mode !== initial.mode ||
    preference.accent !== initial.accent || resolved !== initial.resolvedTheme;
  root.dataset.themeReady = differsFromServer ? "false" : "true";
  root.dataset.appearanceMode = preference.mode;
  root.dataset.resolvedTheme = resolved;
  root.dataset.colorTheme = preference.accent;
  root.style.colorScheme = resolved;

  try {
    var secure = window.location.protocol === "https:" ? "; Secure" : "";
    var cookie = "v1:" + preference.mode + ":" + preference.accent + ":" + resolved;
    document.cookie = ${JSON.stringify(APPEARANCE_COOKIE_NAME)} + "=" + encodeURIComponent(cookie) +
      "; Path=/; Max-Age=${APPEARANCE_COOKIE_MAX_AGE}; SameSite=Lax" + secure;
  } catch (_) {}
})();`;
}

export function ThemeBootstrapScript(props: ThemeBootstrapScriptProps) {
  return (
    // App Router 允许在根布局中使用 beforeInteractive，规则提示仍沿用 Pages Router 的限制。
    // eslint-disable-next-line @next/next/no-before-interactive-script-outside-document
    <Script id="xw-appearance-bootstrap" strategy="beforeInteractive">
      {buildThemeBootstrapSource(props)}
    </Script>
  );
}
