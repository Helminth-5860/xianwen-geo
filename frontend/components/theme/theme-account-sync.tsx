"use client";

import { useEffect } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";

import { normalizeAppearance, type AppearancePreference } from "./appearance";
import {
  APPEARANCE_ACCOUNT_SAVE_EVENT,
  type AppearanceAccountSaveRequest,
  useThemeAccountController,
} from "./app-theme-provider";

type AccountWithAppearance = Readonly<{
  appearance?: unknown;
  appearance_mode?: unknown;
  appearance_accent?: unknown;
  color_theme?: unknown;
}>;

type AppearanceUpdater = (appearance: AppearancePreference) => Promise<unknown> | unknown;

function appearanceFromAccount(user: unknown): AppearancePreference | null {
  if (typeof user !== "object" || user === null) return null;
  const account = user as AccountWithAppearance;
  if (account.appearance) {
    const normalized = normalizeAppearance(account.appearance, { mode: "system", accent: "blue" });
    const raw = account.appearance as Record<string, unknown>;
    if (raw.mode && raw.accent) return normalized;
  }
  if (account.appearance_mode && (account.appearance_accent || account.color_theme)) {
    return normalizeAppearance(
      {
        mode: account.appearance_mode,
        accent: account.appearance_accent ?? account.color_theme,
      },
      { mode: "system", accent: "blue" },
    );
  }
  return null;
}

function appearanceFromResponse(
  response: unknown,
  fallback: AppearancePreference,
): AppearancePreference {
  if (typeof response !== "object" || response === null) return fallback;
  const direct = appearanceFromAccount(response);
  if (direct) return direct;
  return normalizeAppearance(response, fallback);
}

async function saveAccountAppearance(
  appearance: AppearancePreference,
): Promise<AppearancePreference> {
  const client = (await import("@/lib/auth-client")) as unknown as {
    updateAppearance?: AppearanceUpdater;
    updateCurrentUserAppearance?: AppearanceUpdater;
  };
  const update = client.updateAppearance ?? client.updateCurrentUserAppearance;
  if (!update) return appearance;
  const response = await update(appearance);
  return appearanceFromResponse(response, appearance);
}

export function ThemeAccountSync() {
  const { user } = useSubjectWorkspace();
  const syncFromAccount = useThemeAccountController();
  const userAppearance = appearanceFromAccount(user);
  const userAppearanceMode = userAppearance?.mode;
  const userAppearanceAccent = userAppearance?.accent;

  useEffect(() => {
    if (!userAppearanceMode || !userAppearanceAccent) return;
    syncFromAccount({ mode: userAppearanceMode, accent: userAppearanceAccent });
  }, [syncFromAccount, userAppearanceAccent, userAppearanceMode]);

  useEffect(() => {
    if (!user) return;
    const handleSave = (event: Event) => {
      const detail = (event as CustomEvent<AppearanceAccountSaveRequest>).detail;
      if (!detail?.appearance || typeof detail.respondWith !== "function") return;
      detail.respondWith(saveAccountAppearance(detail.appearance));
    };
    window.addEventListener(APPEARANCE_ACCOUNT_SAVE_EVENT, handleSave);
    return () => window.removeEventListener(APPEARANCE_ACCOUNT_SAVE_EVENT, handleSave);
  }, [user]);

  return null;
}
