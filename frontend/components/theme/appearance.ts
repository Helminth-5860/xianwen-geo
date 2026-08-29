export const APPEARANCE_STORAGE_KEY = "xw:appearance:v1";
export const APPEARANCE_COOKIE_NAME = "xw_appearance";
export const APPEARANCE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

export const APPEARANCE_MODES = ["light", "dark", "system"] as const;
export const COLOR_THEMES = ["blue", "green", "purple", "orange"] as const;
export const RESOLVED_THEMES = ["light", "dark"] as const;

export type AppearanceMode = (typeof APPEARANCE_MODES)[number];
export type ColorTheme = (typeof COLOR_THEMES)[number];
export type ResolvedTheme = (typeof RESOLVED_THEMES)[number];

export type AppearancePreference = Readonly<{
  mode: AppearanceMode;
  accent: ColorTheme;
}>;

export type StoredAppearance = Readonly<{
  appearance: AppearancePreference;
  resolvedTheme: ResolvedTheme;
}>;

export const DEFAULT_APPEARANCE: AppearancePreference = Object.freeze({
  mode: "system",
  accent: "blue",
});

const APPEARANCE_VERSION = 1;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isAppearanceMode(value: unknown): value is AppearanceMode {
  return typeof value === "string" && APPEARANCE_MODES.includes(value as AppearanceMode);
}

export function isColorTheme(value: unknown): value is ColorTheme {
  return typeof value === "string" && COLOR_THEMES.includes(value as ColorTheme);
}

export function isResolvedTheme(value: unknown): value is ResolvedTheme {
  return typeof value === "string" && RESOLVED_THEMES.includes(value as ResolvedTheme);
}

export function normalizeAppearance(
  value: unknown,
  fallback: AppearancePreference = DEFAULT_APPEARANCE,
): AppearancePreference {
  if (!isRecord(value)) return fallback;
  return {
    mode: isAppearanceMode(value.mode) ? value.mode : fallback.mode,
    accent: isColorTheme(value.accent) ? value.accent : fallback.accent,
  };
}

export function resolveAppearanceMode(
  mode: AppearanceMode,
  systemPrefersDark = false,
): ResolvedTheme {
  if (mode === "system") return systemPrefersDark ? "dark" : "light";
  return mode;
}

export function serializeAppearanceStorage(appearance: AppearancePreference): string {
  return JSON.stringify({
    version: APPEARANCE_VERSION,
    mode: appearance.mode,
    accent: appearance.accent,
  });
}

export function parseAppearanceStorage(
  value: string | null | undefined,
): AppearancePreference | null {
  if (!value) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    if (!isRecord(parsed) || parsed.version !== APPEARANCE_VERSION) return null;
    if (!isAppearanceMode(parsed.mode) || !isColorTheme(parsed.accent)) return null;
    return { mode: parsed.mode, accent: parsed.accent };
  } catch {
    return null;
  }
}

export function serializeAppearanceCookie(
  appearance: AppearancePreference,
  resolvedTheme: ResolvedTheme,
): string {
  return `v1:${appearance.mode}:${appearance.accent}:${resolvedTheme}`;
}

export function parseAppearanceCookie(value: string | null | undefined): StoredAppearance | null {
  if (!value) return null;
  let decoded = value;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return null;
  }
  const [version, mode, accent, resolved] = decoded.split(":");
  if (version !== "v1" || !isAppearanceMode(mode) || !isColorTheme(accent)) return null;
  const resolvedTheme = isResolvedTheme(resolved) ? resolved : resolveAppearanceMode(mode, false);
  return { appearance: { mode, accent }, resolvedTheme };
}

export function appearanceEquals(left: AppearancePreference, right: AppearancePreference): boolean {
  return left.mode === right.mode && left.accent === right.accent;
}
