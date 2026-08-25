import { AntdRegistry } from "@ant-design/nextjs-registry";
import type { Metadata } from "next";

import { UserAssistantWidget } from "@/components/assistant/user-assistant-widget";
import { UserWorkspaceNavigation } from "@/components/user-workspace-navigation";

import "./globals.css";
import "./product-shell.css";
import "./assistant-widget.css";

export const metadata: Metadata = {
  title: "显问 GEO 智能体系统",
  description: "显问 GEO 智能体系统 V1",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <AntdRegistry>
          <div className="geo-app-shell">
            <UserWorkspaceNavigation />
            <div className="geo-app-shell__content">{children}</div>
            <UserAssistantWidget />
          </div>
        </AntdRegistry>
      </body>
    </html>
  );
}
