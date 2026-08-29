import { AntdRegistry } from "@ant-design/nextjs-registry";
import type { Metadata } from "next";
import { cookies } from "next/headers";

import { UserAssistantWidget } from "@/components/assistant/user-assistant-widget";
import { ResponsiveWorkspaceShell } from "@/components/responsive-workspace-shell";
import { SubjectWorkspaceProvider } from "@/components/subject-workspace-context";
import {
  APPEARANCE_COOKIE_NAME,
  DEFAULT_APPEARANCE,
  parseAppearanceCookie,
  resolveAppearanceMode,
} from "@/components/theme/appearance";
import { AppThemeProvider } from "@/components/theme/app-theme-provider";
import { ThemeAccountSync } from "@/components/theme/theme-account-sync";
import { ThemeBootstrapScript } from "@/components/theme/theme-bootstrap-script";

import "./globals.css";
import "./product-shell.css";
import "./xw-tokens.css";
import "./assistant-widget.css";
import "./website-audit.css";

export const metadata: Metadata = {
  title: "显问 GEO 智能体系统",
  description: "帮助企业提升在主流人工智能回答中的可见度与推荐表现",
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const cookieStore = await cookies();
  const storedAppearance = parseAppearanceCookie(cookieStore.get(APPEARANCE_COOKIE_NAME)?.value);
  const initialAppearance = storedAppearance?.appearance ?? DEFAULT_APPEARANCE;
  const initialResolvedTheme =
    storedAppearance?.resolvedTheme ?? resolveAppearanceMode(initialAppearance.mode, false);

  return (
    <html
      lang="zh-CN"
      data-appearance-mode={initialAppearance.mode}
      data-resolved-theme={initialResolvedTheme}
      data-color-theme={initialAppearance.accent}
      data-theme-ready="true"
      style={{ colorScheme: initialResolvedTheme }}
      suppressHydrationWarning
    >
      <body>
        <ThemeBootstrapScript
          initialAppearance={initialAppearance}
          initialResolvedTheme={initialResolvedTheme}
        />
        <AntdRegistry>
          <AppThemeProvider
            initialAppearance={initialAppearance}
            initialResolvedTheme={initialResolvedTheme}
          >
            <SubjectWorkspaceProvider>
              <ThemeAccountSync />
              <ResponsiveWorkspaceShell>{children}</ResponsiveWorkspaceShell>
              <UserAssistantWidget />
            </SubjectWorkspaceProvider>
          </AppThemeProvider>
        </AntdRegistry>
      </body>
    </html>
  );
}
